"""会話フローに沿ってプロンプトを切り替えるための補助モジュール。

現在のAPI（/chat/session/...）には影響を与えず、裏側でシステム/デベロッパー
プロンプトを組み立てる用途で利用することを想定している。
"""

from __future__ import annotations

import os

import httpx
import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional

SystemPrompt = str
DeveloperPrompt = str

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class DialogueStep(str, Enum):
    """おかんチェックセッションのステップ。"""

    INTRO = "INTRO"
    TASK_LOOP = "TASK_LOOP"
    CARRYOVER = "CARRYOVER"
    SUMMARY = "SUMMARY"
    END = "END"


SYSTEM_PROMPT: SystemPrompt = (
    """あなたは「おかん」キャラの会話AI。対象は大学生〜社会人の息子（ユーザー）。口うるさいが根は優しい“日本のおかん”として、毎回「やることやった？」を短く確認し、必要なら軽く背中を押す。

キャラクター核：
- 口調：親しみ＋ちょい圧。やや説教臭い。大阪弁。
- スタンス：お節介8割、共感2割。
- 温度感：やや厳しめ。ただし常にラストは励ましで締める。
- NG：恥をかかせる、詰問、持論の押し付け、医療/法律/危険行為の助長。\n"""

"""目的：今日するべきだったことができたかを問いただす。タスクは外部で定義されたリスト（current_task.md）を基準にし、未達タスクは理由を軽く確認して明日に回させる。

会話原則：
- 一度に質問は1つまで。タスク名を必ず呼ぶ。
- ユーザーが達成と答えたら素直に褒め、素早く次へ進む。
- 未達/部分達成なら、責めずに「なんでや？」を大阪弁で一言ヒアリングし、深掘りしすぎない。
- 最終まとめでは「できたこと」を再確認し、残タスクは明日のTODOとして励ましを添える。

ルール：各Stepと state に基づく Developer 指示に厳密に従うこと。\n"""
)


POSITIVE_CHOICES = {"はい", "はい！", "うん", "yes", "まだある", "ある", "ok", "そうする", "そうだよ"}
NEGATIVE_CHOICES = {"いいえ", "いえ", "ない", "no", "もうない", "終わり"}

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.propagate = False


@dataclass
class TopicRecord:
    """1トピック分の出来事と感情を保持。"""

    event: Optional[str] = None
    emotion: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Optional[str]]) -> "TopicRecord":
        return cls(event=data.get("event"), emotion=data.get("emotion"))


@dataclass
class DialogueState:
    """会話の進行状況を保持し、ループ制御を担当。"""

    step: DialogueStep = DialogueStep.INTRO
    tasks: List[str] = field(default_factory=list)
    current_index: int = 0
    loops_completed: int = 0
    loop_limit: int = 5
    topics: List[TopicRecord] = field(default_factory=list)
    completed_tasks: List[str] = field(default_factory=list)
    deferred_tasks: List[str] = field(default_factory=list)
    awaiting_reason: bool = False
    last_reason: Optional[str] = None
    reason_map: Dict[str, str] = field(default_factory=dict)
    tasks_introduced: bool = False
    carryover_selected: List[str] = field(default_factory=list)

    def current_topic(self) -> TopicRecord:
        if not self.topics:
            self.topics.append(TopicRecord())
        return self.topics[-1]

    def current_task(self) -> Optional[str]:
        if 0 <= self.current_index < len(self.tasks):
            return self.tasks[self.current_index]
        return None

    def remaining_tasks(self) -> List[str]:
        return self.tasks[self.current_index :]

    def render_guidance(self, with_status: bool = True) -> str:
        lines: List[str] = []
        if with_status:
            lines.append("【チェックするタスク】")
            for idx, task in enumerate(self.tasks):
                if task in self.completed_tasks:
                    status = "済"
                elif task in self.deferred_tasks and idx < self.current_index:
                    status = "未完"
                elif idx == self.current_index:
                    status = "進行中"
                else:
                    status = "未チェック"
                lines.append(f"- {task} ({status})")
            if self.awaiting_reason and self.current_task():
                lines.append(f"※ 今は『{self.current_task()}』が未達。理由を一言で聞きたい。")
        else:
            for task in self.tasks:
                lines.append(f"- {task}")
        return "\n".join(lines)

    def _advance_task_pointer(self) -> None:
        self.current_index += 1
        self.awaiting_reason = False
        self.last_reason = None
        if self.current_index < len(self.tasks):
            self.step = DialogueStep.TASK_LOOP
        else:
            if self.deferred_tasks:
                self.step = DialogueStep.CARRYOVER
            else:
                self.carryover_selected = []
                self.step = DialogueStep.SUMMARY

    async def advance(self, user_reply: str) -> None:
        """ユーザーの返答に応じて次のステップへ遷移。"""

        if self.step == DialogueStep.INTRO:
            self.step = DialogueStep.TASK_LOOP
            return

        if self.step == DialogueStep.TASK_LOOP:
            current = self.current_task()
            if current is None:
                if self.deferred_tasks:
                    self.step = DialogueStep.CARRYOVER
                else:
                    self.carryover_selected = []
                    self.step = DialogueStep.SUMMARY
                return

            if self.awaiting_reason:
                self.last_reason = user_reply.strip()
                logger.info("Received reason for %s: %s", current, self.last_reason)
                if current not in self.deferred_tasks:
                    self.deferred_tasks.append(current)
                if self.last_reason:
                    self.reason_map[current] = self.last_reason
                self._advance_task_pointer()
                return

            decision = await classify_yes_no(user_reply)
            logger.info("TASK_LOOP decision: %s for task '%s'", decision, current)

            if decision is True:
                if current not in self.completed_tasks:
                    self.completed_tasks.append(current)
                self._advance_task_pointer()
            else:
                if current not in self.deferred_tasks:
                    self.deferred_tasks.append(current)
                self.awaiting_reason = True
                self.reason_map.setdefault(current, "")
            return

        if self.step == DialogueStep.CARRYOVER:
            text = user_reply.strip()
            selection: List[str] = []
            if text:
                lowered = text.lower()
                if any(keyword in lowered for keyword in ["なし", "いら", "要ら", "不要", "no"]):
                    selection = []
                elif any(keyword in text for keyword in ["全部", "全て", "全部とも", "全部残す"]):
                    selection = list(self.deferred_tasks)
                else:
                    selection = await classify_carryover(self.deferred_tasks, text) or []
            self.carryover_selected = selection
            self.step = DialogueStep.SUMMARY
            return

        if self.step == DialogueStep.SUMMARY:
            self.step = DialogueStep.END
            return

        if self.step == DialogueStep.END:
            return

    def to_dict(self) -> Dict[str, object]:
        return {
            "step": self.step.value,
            "loop_limit": self.loop_limit,
            "loops_completed": self.loops_completed,
            "topics": [asdict(topic) for topic in self.topics],
            "tasks": self.tasks,
            "current_index": self.current_index,
            "completed_tasks": self.completed_tasks,
            "deferred_tasks": self.deferred_tasks,
            "awaiting_reason": self.awaiting_reason,
            "last_reason": self.last_reason,
            "reason_map": self.reason_map,
            "tasks_introduced": self.tasks_introduced,
            "carryover_selected": self.carryover_selected,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "DialogueState":
        step_value = data.get("step", DialogueStep.INTRO.value)
        loop_limit = int(data.get("loop_limit", 5))
        loops_completed = int(data.get("loops_completed", 0))
        topics_data = data.get("topics", [])

        topics: List[TopicRecord] = []
        for item in topics_data:
            if isinstance(item, dict):
                topics.append(TopicRecord.from_dict(item))

        state = cls(
            step=DialogueStep(step_value),
            loop_limit=loop_limit,
            loops_completed=loops_completed,
            topics=topics or [TopicRecord()],
            tasks=list(data.get("tasks", [])),
            current_index=int(data.get("current_index", 0)),
            completed_tasks=list(data.get("completed_tasks", [])),
            deferred_tasks=list(data.get("deferred_tasks", [])),
            awaiting_reason=bool(data.get("awaiting_reason", False)),
            last_reason=data.get("last_reason"),
            reason_map=dict(data.get("reason_map", {})),
            tasks_introduced=bool(data.get("tasks_introduced", False)),
            carryover_selected=list(data.get("carryover_selected", [])),
        )
        return state


def get_developer_prompt(state: DialogueState) -> DeveloperPrompt:
    current_task = state.current_task()

    if state.step == DialogueStep.INTRO:
        return (
            "【Step=INTRO】1〜2文で挨拶。「おかん」が息子に声をかける体で、"
            "これから今日のタスクチェックを始めることを伝える。質問はしない。"
        )
    if state.step == DialogueStep.TASK_LOOP:
        if not state.tasks_introduced and current_task:
            task_list = state.render_guidance(with_status=False)
            return (
                "【Step=TASK_LOOP(初回)】今日チェックする「タスク一覧」を全部言い聞かせてから、"
                f"先頭のタスク『{current_task}』ができたか大阪弁で問いただす。理由はまだ聞かない。"
                f"\nタスク一覧:\n{task_list}"
                f"例：「今日は{task_list}が今日やることやったな。ほな、最初の『{current_task}』、できたんか？」"
            )
        if state.awaiting_reason and current_task:
            return (
                f"【Step=TASK_LOOP(理由確認)】タスク『{current_task}』がしっかりできていなかった。"
                "責めすぎず「なんでや？」とできなかった理由を聞いてください。"
                "絶対に次のタスクの質問はしないでください"
            )
        if current_task:
            remaining = len(state.tasks) - state.current_index
            return (
                f"【Step=TASK_LOOP】タスク『{current_task}』ができたか大阪弁で問いただす。"
                "達成ならしっかり褒め、未達なら一度だけ理由確認に移る前振りをする。"
                f" 残りタスク数: {remaining}"
            )
        return "【Step=TASK_LOOP】タスクがすべて終わっていればその旨を伝え、まとめに進む。"
    if state.step == DialogueStep.CARRYOVER:
        task_lines = "\n".join(f"- {task}" for task in state.deferred_tasks)
        return (
            "【Step=CARRYOVER】未達だったタスクのうち、明日に残すものを息子に選ばせる。"
            "具体的なタスク名を復唱しつつ、複数まとめて答えてもらっても良い。『なし』なら全て完了扱い。\n"
            f"持ち越し候補:\n{task_lines}"
            "例：「今日できなかったものの中で明日やることを教えてや」"
        )
    if state.step == DialogueStep.SUMMARY:
        done = state.completed_tasks or ["なし"]
        leftover = state.carryover_selected or []
        lines = [
            "【Step=SUMMARY】今日できたことを短く再読し、残タスクがあれば『明日やったらええ』と励ます。",
            f"できたこと: {', '.join(done)}",
            f"明日へ回す: {', '.join(leftover) if leftover else 'なし'}",
        ]
        for task in leftover:
            reason = state.reason_map.get(task)
            if reason:
                lines.append(f"理由メモ({task}): {reason}")
        lines.append("最後に明日への気合いを一言。")
        return "\n".join(lines)
    if state.step == DialogueStep.END:
        return "【Step=END】締めの一言。大阪のおかんらしく温かく、質問はしない。"
    return ""


async def classify_yes_no(reply: str) -> Optional[bool]:
    """OpenRouterのモデルに問い合わせてYes/No判定を行う。"""

    normalized = reply.strip().lower()
    if normalized in POSITIVE_CHOICES:
        logger.info("classify_yes_no local match: YES (%s)", reply)
        return True
    if normalized in NEGATIVE_CHOICES:
        logger.info("classify_yes_no local match: NO (%s)", reply)
        return False
    if any(token in reply for token in ("はい", "うん", "ある", "そうする", "そうだよ", "お願い")):
        logger.info("classify_yes_no local partial match: YES (%s)", reply)
        return True
    if any(token in reply for token in ("いいえ", "いえ", "ない", "もういい")):
        logger.info("classify_yes_no local partial match: NO (%s)", reply)
        return False

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.debug("classify_yes_no: OPENROUTER_API_KEY not set, returning None")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    referer = os.environ.get("OPENROUTER_SITE_URL")
    if referer:
        headers["HTTP-Referer"] = referer

    title = os.environ.get("OPENROUTER_APP_NAME")
    if title:
        headers["X-Title"] = title

    body = {
        "model": os.environ.get("CHAT_CLASSIFIER_MODEL", "openai/gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a Japanese assistant that classifies user replies. "
                    "Return a JSON object like {\"result\": \"yes\"}, {\"result\": \"no\"}, "
                    "or {\"result\": \"unknown\"} depending on whether the reply agrees to continue talking."
                ),
            },
            {
                "role": "user",
                "content": f"ユーザーの返答: {reply}",
            },
        ],
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15)) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=body,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.RequestError as exc:
        logger.warning("classify_yes_no: request error %s", exc)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "classify_yes_no: HTTP error %s %s",
            exc.response.status_code,
            exc.response.text,
        )
        return None

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        result = parsed.get("result")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        logger.warning("classify_yes_no: failed to parse response %s", data)
        return None

    logger.info("classify_yes_no LLM result: %s (%s)", result, reply)
    if result == "yes":
        return True
    if result == "no":
        return False
    logger.info("classify_yes_no result unknown (%s)", reply)
    return None


async def classify_carryover(selections: List[str], reply: str) -> Optional[List[str]]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    referer = os.environ.get("OPENROUTER_SITE_URL")
    if referer:
        headers["HTTP-Referer"] = referer

    title = os.environ.get("OPENROUTER_APP_NAME")
    if title:
        headers["X-Title"] = title

    task_list = "\n".join(f"- {task}" for task in selections)
    system_prompt = (
        "You are a Japanese assistant that extracts which tasks should be carried over. "
        "Return JSON {\"tasks\": [taskName...]}. The tasks must come from the provided list."
    )
    user_prompt = (
        "タスク一覧:\n"
        f"{task_list}\n\n"
        "ユーザーの返答:\n"
        f"{reply}"
    )

    body = {
        "model": os.environ.get("CHAT_CLASSIFIER_MODEL", "openai/gpt-4o"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15)) as client:
            response = await client.post(
                OPENROUTER_URL,
                json=body,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.RequestError as exc:  # pragma: no cover - runtime guard
        logger.warning("classify_carryover: request error %s", exc)
        return None
    except httpx.HTTPStatusError as exc:  # pragma: no cover - runtime guard
        logger.warning(
            "classify_carryover: HTTP error %s %s",
            exc.response.status_code,
            exc.response.text,
        )
        return None

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        tasks = parsed.get("tasks", [])
        return [task for task in tasks if task in selections]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        logger.warning("classify_carryover: failed to parse response %s", data)
        return None


def get_system_prompt() -> SystemPrompt:
    """固定のシステムプロンプトを取得。"""

    return SYSTEM_PROMPT


__all__ = [
    "DialogueStep",
    "DialogueState",
    "TopicRecord",
    "get_system_prompt",
    "get_developer_prompt",
    "classify_yes_no",
]
