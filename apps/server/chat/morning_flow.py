"""会話フローに沿ってプロンプトを切り替えるための補助モジュール。

現在のAPI（/chat/session/...）には影響を与えず、裏側でシステム/デベロッパー
プロンプトを組み立てる用途で利用することを想定している。
"""

from __future__ import annotations

import os

import httpx
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

SystemPrompt = str
DeveloperPrompt = str


class DialogueStep(str, Enum):
    """会話フローの各ステップを列挙。"""

    INTRO = "INTRO"
    REMAINING_TASKS = "REMAINING_TASKS"
    ASK_TODAY_TASKS = "ASK_TODAY_TASKS"
    CONFIRM_TODAY_TASKS = "CONFIRM_TODAY_TASKS"
    END = "END"


SYSTEM_PROMPT: SystemPrompt = (
    """あなたは「おかん」キャラの会話AI。対象は大学生〜社会人の息子（ユーザー）。口うるさいが根は優しい"日本のおかん"として、毎回「やることやった？」を短く確認し、必要なら軽く背中を押す。

キャラクター核：
- 口調：親しみ＋ちょい圧。やや説教臭い。大阪弁。
- スタンス：お節介8割、共感2割。
- 温度感：やや厳しめ。ただし常にラストは励ましで締める。
- NG：恥をかかせる、詰問、持論の押し付け、医療/法律/危険行為の助長。\n"""

    """目的：朝に今日やるタスクを聞き出して整理する。残っているタスク（current_task.md）があれば確認し、今日のタスクを決めて保存する。

会話原則：
- 一度に質問は1つまで。
- ユーザーが答えたら素直に受け止め、素早く次へ進む。
- タスクは箇条書き形式で整理する。
- 最終確認で「合ってる？」と念押しし、承認されたら終了。

ルール：各Stepとstateに基づくDeveloper指示に厳密に従うこと。\n"""
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
    """1トピック分のタスク情報を保持。"""

    tasks: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "TopicRecord":
        tasks = data.get("tasks", [])
        if isinstance(tasks, list):
            return cls(tasks=[str(t) for t in tasks])
        return cls(tasks=[])


@dataclass
class DialogueState:
    """会話の進行状況を保持し、ループ制御を担当。"""

    step: DialogueStep = DialogueStep.INTRO
    remaining_tasks: List[str] = field(default_factory=list)
    today_tasks: List[str] = field(default_factory=list)
    loop_limit: int = 2
    loops_completed: int = 0
    tasks_introduced: bool = False

    async def advance(self, user_reply: str) -> None:
        """ユーザーの返答に応じて次のステップへ遷移。"""

        if self.step == DialogueStep.INTRO:
            # 残タスクがある場合はREMAINING_TASKSへ、ない場合は直接ASK_TODAY_TASKSへ
            if self.remaining_tasks:
                self.step = DialogueStep.REMAINING_TASKS
            else:
                self.step = DialogueStep.ASK_TODAY_TASKS
            return

        if self.step == DialogueStep.REMAINING_TASKS:
            self.step = DialogueStep.ASK_TODAY_TASKS
            return

        if self.step == DialogueStep.ASK_TODAY_TASKS:
            self.step = DialogueStep.CONFIRM_TODAY_TASKS
            return

        if self.step == DialogueStep.CONFIRM_TODAY_TASKS:
            decision = await classify_yes_no(user_reply)
            logger.info("CONFIRM_TODAY_TASKS decision: %s", decision)
            if decision is True:
                self.step = DialogueStep.END
            else:
                # 修正が必要な場合は ASK_TODAY_TASKS に戻る
                self.step = DialogueStep.ASK_TODAY_TASKS
                self.today_tasks = []
            return

        if self.step == DialogueStep.END:
            # 終了状態では遷移しない
            return

    def to_dict(self) -> Dict[str, object]:
        return {
            "step": self.step.value,
            "remaining_tasks": self.remaining_tasks,
            "today_tasks": self.today_tasks,
            "loop_limit": self.loop_limit,
            "loops_completed": self.loops_completed,
            "tasks_introduced": self.tasks_introduced,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "DialogueState":
        step_value = data.get("step", DialogueStep.INTRO.value)
        loop_limit = int(data.get("loop_limit", 2))
        loops_completed = int(data.get("loops_completed", 0))
        remaining_tasks = data.get("remaining_tasks", [])
        today_tasks = data.get("today_tasks", [])
        tasks_introduced = bool(data.get("tasks_introduced", False))

        if not isinstance(remaining_tasks, list):
            remaining_tasks = []
        if not isinstance(today_tasks, list):
            today_tasks = []

        state = cls(
            step=DialogueStep(step_value),
            loop_limit=loop_limit,
            loops_completed=loops_completed,
            remaining_tasks=[str(t) for t in remaining_tasks],
            today_tasks=[str(t) for t in today_tasks],
            tasks_introduced=tasks_introduced,
        )
        return state


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


def get_system_prompt() -> SystemPrompt:
    """固定のシステムプロンプトを取得。"""

    return SYSTEM_PROMPT


def get_developer_prompt(state: DialogueState) -> DeveloperPrompt:
    """ステップとstateに応じたDeveloperプロンプトを返す。"""

    if state.step == DialogueStep.INTRO:
        return (
            "【Step=INTRO】1文で挨拶。大阪弁のおかんが息子に声をかける体で。"
            "「おはよう！ちゃんと起きれたか？」「おはようさん。今日も元気そうやな」など。質問はしない。"
        )

    if state.step == DialogueStep.REMAINING_TASKS:
        if state.remaining_tasks:
            task_list = "\n".join([f"- {task}" for task in state.remaining_tasks])
            return (
                "【Step=REMAINING_TASKS】残っているタスクをリスト形式で伝え、"
                "「これ、今日ちゃんとやるんか？」「これ放っといたらあかんで？」とやや厳しめに質問する。\n"
                f"残タスク一覧:\n{task_list}"
            )
        else:
            return (
                "【Step=REMAINING_TASKS】残っているタスクはない。"
                "「ほな、残ってるタスクはないみたいやな。今日は何やるつもりや？」と質問する。"
            )

    if state.step == DialogueStep.ASK_TODAY_TASKS:
        return (
            "【Step=ASK_TODAY_TASKS】1〜2文で反応したあと、"
            "「ほな、今日は何やるつもりなんや？ちゃんと教えてや」「今日やること、ちゃんと言うてみ？」と質問する。"
            "ユーザーが複数のタスクを挙げた場合は全て受け止める。話は掘り下げない。"
        )

    if state.step == DialogueStep.CONFIRM_TODAY_TASKS:
        if state.today_tasks:
            task_list = "\n".join([f"- {task}" for task in state.today_tasks])
            return (
                "【Step=CONFIRM_TODAY_TASKS】ユーザーが挙げた今日のタスクを箇条書き（「-」で始まる形式）で確認し、"
                "「これで全部か？ほんまにこれでええんやな？」と念押しして質問する。\n"
                f"今日のタスク:\n{task_list}\n"
                "必ず箇条書き形式で表示すること。"
            )
        else:
            return (
                "【Step=CONFIRM_TODAY_TASKS】タスクが挙げられていない。"
                "「何もないん？ほんまに大丈夫か？」と確認する。"
            )

    if state.step == DialogueStep.END:
        return (
            "【Step=END】1文で励ましの言葉を伝える。"
            "「ほな、今日もしっかり頑張りや！」「ちゃんとやるんやで！応援しとるで」など。質問はしない。"
        )

    return ""


__all__ = [
    "DialogueStep",
    "DialogueState",
    "TopicRecord",
    "get_system_prompt",
    "get_developer_prompt",
    "classify_yes_no",
]
