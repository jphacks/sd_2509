"""セッションログから出来事と感情を抽出してMarkdown化するユーティリティ。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import httpx

from .conversation_flow import (
    DialogueState as DiaryDialogueState,
    DialogueStep as DiaryDialogueStep,
    classify_yes_no as diary_classify_yes_no,
)
from .random_flow import DialogueState as MomDialogueState


ROOT_DIR = Path(__file__).resolve().parents[3]

SUMMARY_MODEL = os.environ.get("CHAT_SUMMARY_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def _load_session_data(session_id: str) -> dict:
    file_path = _resolve_session_dir() / f"{session_id}.json"
    if not file_path.exists():
        raise FileNotFoundError(f"session log not found: {file_path}")
    with file_path.open(encoding="utf-8") as fp:
        return json.load(fp)


@dataclass
class TopicSummary:
    event: Optional[str] = None
    emotion: Optional[str] = None
    details: List[str] = field(default_factory=list)

    def to_markdown(self, index: int) -> List[str]:
        lines = [f"## トピック {index}"]
        lines.append(f"- 出来事: {self.event or '未記入'}")
        lines.append(f"- 気持ち: {self.emotion or '未記入'}")
        if self.details:
            lines.append("- メモ:")
            for detail in self.details:
                lines.append(f"  - {detail}")
        return lines


async def _build_diary_summary(session_id: str, messages: List[dict]) -> str:
    state = DiaryDialogueState()
    topics: List[TopicSummary] = []
    current_topic: Optional[TopicSummary] = None

    for message in messages:
        if message.get("role") != "user":
            continue

        content = (message.get("content") or "").strip()
        step = state.step

        if step == DiaryDialogueStep.TOPIC:
            current_topic = TopicSummary(event=content)
        elif step == DiaryDialogueStep.EMOTION:
            if current_topic is None:
                current_topic = TopicSummary()
            current_topic.emotion = content
        elif step == DiaryDialogueStep.PROBE:
            if current_topic is None:
                current_topic = TopicSummary()
            current_topic.details.append(content)
        elif step == DiaryDialogueStep.SUMMARY:
            if current_topic:
                topics.append(current_topic)
                current_topic = None
            decision = await diary_classify_yes_no(content)
            if decision is not True:
                await state.advance(content)
                break
        elif step == DiaryDialogueStep.END:
            break

        await state.advance(content)

    if current_topic and current_topic not in topics:
        topics.append(current_topic)

    lines: List[str] = [f"# セッション {session_id} のまとめ"]

    if not topics:
        lines.append("")
        lines.append("記録された出来事が見つかりませんでした。")
        return "\n".join(lines)

    lines.append("")
    for index, topic in enumerate(topics, start=1):
        lines.extend(topic.to_markdown(index))
        lines.append("")

    return "\n".join(line.rstrip() for line in lines).rstrip()


def _build_mom_summary(session_id: str, state: MomDialogueState) -> str:
    completed = state.completed_tasks or ["なし"]
    carryover = state.carryover_selected or []

    lines: List[str] = [f"# セッション {session_id} のまとめ", ""]
    lines.append("## 今日できたこと")
    for task in completed:
        lines.append(f"- {task}")
    if not state.completed_tasks:
        lines.append("- なし")

    lines.append("")
    lines.append("## 明日へ回すこと")
    if carryover:
        for task in carryover:
            reason = state.reason_map.get(task)
            if reason:
                lines.append(f"- {task}（理由: {reason}）")
            else:
                lines.append(f"- {task}")
    else:
        lines.append("- なし")

    return "\n".join(line.rstrip() for line in lines).rstrip()


async def _build_template_summary(session_id: str) -> str:
    data = _load_session_data(session_id)
    state_data = data.get("state", {})

    if "tasks" in state_data:
        mom_state = MomDialogueState.from_dict(state_data)
        return _build_mom_summary(session_id, mom_state)

    messages = data.get("messages", [])
    return await _build_diary_summary(session_id, messages)


def _write_markdown(session_id: str, markdown: str) -> Path:
    output_path = _resolve_summary_dir() / f"{session_id}.md"
    output_path.write_text(markdown + "\n", encoding="utf-8")
    return output_path


async def generate_session_markdown_via_model(session_id: str) -> str:
    """OpenRouterの4o-miniを用いて柔軟なMarkdownサマリーを生成。"""

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY が設定されていません。")

    transcript_data = _load_session_data(session_id).get("messages", [])
    transcript_lines = []
    for message in transcript_data:
        role = message.get("role", "").upper()
        content = (message.get("content") or "").strip()
        if not content:
            continue
        transcript_lines.append(f"{role}: {content}")

    base_markdown = await _build_template_summary(session_id)

    system_prompt = (
        "You are an empathetic diary assistant crafting concise Japanese summaries. "
        "Generate Markdown that keeps the heading '# セッション <ID> のまとめ' and "
        "includes one '## トピック n' section per topic with bullet points for 出来事, 気持ち, "
        "and optional メモ list. Feel free to rephrase details naturally."
    )

    user_prompt = (
        f"Session ID: {session_id}\n\n"
        "Conversation transcript:\n"
        + "\n".join(transcript_lines)
        + "\n\n"
        "Existing template summary:\n"
        + base_markdown
        + "\n\n"
        "Please refine the summary to sound natural and warm while keeping the Markdown structure."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    site_url = os.environ.get("OPENROUTER_SITE_URL")
    if site_url:
        headers["HTTP-Referer"] = site_url

    app_name = os.environ.get("OPENROUTER_APP_NAME")
    if app_name:
        headers["X-Title"] = app_name

    body = {
        "model": SUMMARY_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(OPENROUTER_URL, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"OpenRouterエラー: {exc.response.status_code} {exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError("OpenRouterへの接続に失敗しました。") from exc

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("OpenRouterから適切なサマリーが返りませんでした。") from exc


async def write_session_markdown_via_model(session_id: str) -> Path:
    markdown = await generate_session_markdown_via_model(session_id)
    return _write_markdown(session_id, markdown)


async def generate_session_markdown(session_id: str) -> str:
    """常にLLMを利用してサマリーを生成。"""

    return await generate_session_markdown_via_model(session_id)


async def write_session_markdown(session_id: str, markdown: Optional[str] = None) -> Path:
    content = markdown or await generate_session_markdown(session_id)
    return _write_markdown(session_id, content)


__all__ = [
    "generate_session_markdown",
    "generate_session_markdown_via_model",
    "write_session_markdown",
    "write_session_markdown_via_model",
    "TopicSummary",
]
def _resolve_session_dir() -> Path:
    env_path = os.environ.get("CHAT_SESSION_DIR")
    if env_path:
        session_dir = Path(env_path).expanduser().resolve()
    else:
        from datetime import date

        session_dir = ROOT_DIR / "db" / date.today().isoformat() / "session_logs"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _resolve_summary_dir() -> Path:
    env_path = os.environ.get("CHAT_SUMMARY_DIR")
    if env_path:
        summary_dir = Path(env_path).expanduser().resolve()
    else:
        from datetime import date

        summary_dir = ROOT_DIR / "db" / date.today().isoformat() / "session_summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    return summary_dir
