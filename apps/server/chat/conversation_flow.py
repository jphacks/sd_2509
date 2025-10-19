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


class DialogueStep(str, Enum):
    """会話フローの各ステップを列挙。"""

    INTRO = "INTRO"
    TOPIC = "TOPIC"
    EMOTION = "EMOTION"
    PROBE = "PROBE"
    SUMMARY = "SUMMARY"
    END = "END"


SYSTEM_PROMPT: SystemPrompt = (
    "あなたは音声対話アプリ「AI Call」の会話AIです。\n"
    "目的：ユーザーの「今日の出来事」と「その時の感情」を短いやり取りで引き出す。\n"
    "話し方：親しみやすく、1〜2文、質問は必ず1つ。共感→質問の順番で話す。\n"
    "禁止：長文、複数質問、押し付け助言、高リスク助言。\n"
    "ルール：各Stepで与えられるDeveloper指示に厳密に従い、指定形式のみで返答する。\n"
)


DEVELOPER_PROMPTS: Dict[DialogueStep, DeveloperPrompt] = {
    DialogueStep.INTRO: (
        "【Step=INTRO】1〜2文で軽い導入を行う。まだ質問はしないでください。"
        "「おつかれー！今日の日記インタビューで電話かけたよ。」 質問・要約・助言は禁止。"
    ),
    DialogueStep.TOPIC: (
        "【Step=TOPIC】1〜2文でユーザーの話を受け止めつつ、"
        "「一番の出来事を1つだけ挙げると？」と単一の質問で尋ねる。"
    ),
    DialogueStep.EMOTION: (
        "【Step=EMOTION】1〜2文で共感を示したあと、"
        "「それ、どんな気持ち？」と質問する。"
    ),
    DialogueStep.PROBE: (
        "【Step=PROBE】1〜2文で反応し、事実か感情のどちらか一方を深掘りする質問を1つだけ投げる。"
        "例：事実なら「どの瞬間がピークだった？」、感情なら「その気持ちになった決め手は何？」。"
    ),
    DialogueStep.SUMMARY: (
        "【Step=SUMMARY】1文で出来事と感情をまとめたうえで、"
        "「他にもはなしたいことある？」と質問する。"
        "話は掘り下げずに必ず「他にもはなしたいことある？」と言うこと。"
    ),
    DialogueStep.END: (
        "【Step=END】1文で今日の会話を短く要約し、"
        "最後に「また聞かせてね。」などの短いフックで締める。質問はしない。"
    ),
}


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
    loop_limit: int = 2
    loops_completed: int = 0
    topics: List[TopicRecord] = field(default_factory=list)

    def current_topic(self) -> TopicRecord:
        if not self.topics:
            self.topics.append(TopicRecord())
        return self.topics[-1]

    async def advance(self, user_reply: str) -> None:
        """ユーザーの返答に応じて次のステップへ遷移。"""

        if self.step == DialogueStep.INTRO:
            self.step = DialogueStep.TOPIC
            return

        if self.step == DialogueStep.TOPIC:
            self.step = DialogueStep.EMOTION
            return

        if self.step == DialogueStep.EMOTION:
            self.step = DialogueStep.PROBE
            return

        if self.step == DialogueStep.PROBE:
            self.step = DialogueStep.SUMMARY
            return

        if self.step == DialogueStep.SUMMARY:
            decision = await classify_yes_no(user_reply)
            logger.info("SUMMARY decision: %s (loops_completed=%s)", decision, self.loops_completed)
            if decision is True:
                if self.loops_completed + 1 < self.loop_limit:
                    self.loops_completed += 1
                    self.topics.append(TopicRecord())
                    self.step = DialogueStep.TOPIC
                else:
                    logger.info("Loop limit reached; moving to END")
                    self.step = DialogueStep.END
            else:
                self.step = DialogueStep.END
            return

        if self.step == DialogueStep.END:
            # 終了状態では遷移しない
            return

    def to_dict(self) -> Dict[str, object]:
        return {
            "step": self.step.value,
            "loop_limit": self.loop_limit,
            "loops_completed": self.loops_completed,
            "topics": [asdict(topic) for topic in self.topics],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "DialogueState":
        step_value = data.get("step", DialogueStep.INTRO.value)
        loop_limit = int(data.get("loop_limit", 2))
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


def get_developer_prompt(step: DialogueStep) -> DeveloperPrompt:
    """ステップに応じたDeveloperプロンプトを返す。"""

    try:
        return DEVELOPER_PROMPTS[step]
    except KeyError as exc:
        raise ValueError(f"未知のステップ: {step}") from exc


__all__ = [
    "DialogueStep",
    "DialogueState",
    "TopicRecord",
    "get_system_prompt",
    "get_developer_prompt",
    "classify_yes_no",
]
