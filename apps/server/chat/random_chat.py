import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, status

from packages.shared_schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    SessionContinueRequest,
    SessionResponse,
    SessionStartRequest,
)

from .random_flow import (
    DialogueState,
    DialogueStep,
    get_developer_prompt,
    get_system_prompt as get_flow_system_prompt,
)
from .log_summary import (
    generate_session_markdown,
    write_session_markdown,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o")

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_PROMPT_CANDIDATES = [
    PROMPT_DIR / "system_prompt.txt",
    PROMPT_DIR / "system_prompt.example.txt",
]

ROOT_DIR = Path(__file__).resolve().parents[3]
CURRENT_TASK_FILE = ROOT_DIR / "db" / "current" / "current_task.md"
DEFAULT_SESSION_ID = "random_session"

router = APIRouter(prefix="/chat", tags=["chat"])


def _resolve_session_dir() -> Path:
    env_path = os.environ.get("CHAT_SESSION_DIR")
    if env_path:
        session_dir = Path(env_path).expanduser().resolve()
    else:
        from datetime import date

        session_dir = ROOT_DIR / "db" / date.today().isoformat() / "session_logs"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _load_current_tasks() -> List[str]:
    if not CURRENT_TASK_FILE.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="current_task.md が見つかりません。",
        )

    tasks: List[str] = []
    for line in CURRENT_TASK_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("- "):
            task = line[2:].strip()
        else:
            task = line.strip("- ")
        if task:
            tasks.append(task)

    if not tasks:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="current_task.md にタスクが定義されていません。",
        )

    return tasks


def _write_current_tasks(tasks: List[str]) -> None:
    CURRENT_TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"- {task}" for task in tasks if task]
    content = "\n".join(lines)
    if content:
        content += "\n"
    CURRENT_TASK_FILE.write_text(content, encoding="utf-8")


def _load_base_system_prompt() -> Optional[str]:
    """環境変数または雛形ファイルからカスタムシステムプロンプトを読み込む。"""

    env_path = os.environ.get("OPENROUTER_SYSTEM_PROMPT_FILE")
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        try:
            return candidate.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None

    for candidate in DEFAULT_PROMPT_CANDIDATES:
        try:
            return candidate.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
    return None


@lru_cache(maxsize=1)
def _get_cached_base_prompt() -> Optional[str]:
    """カスタムシステムプロンプトの読み込みをキャッシュ。"""

    return _load_base_system_prompt()


def _compose_system_prompt(
    state: Optional[DialogueState],
    base_prompt: Optional[str],
) -> Optional[str]:
    """会話フローのステップ情報を組み合わせたシステムプロンプトを生成。"""

    components: List[str] = []
    flow_prompt = get_flow_system_prompt()
    if flow_prompt:
        components.append(flow_prompt)
    if base_prompt:
        components.append(base_prompt)
    if state:
        components.append(get_developer_prompt(state))
    return "\n\n".join(components) if components else None


def _build_messages(payload: ChatRequest) -> List[Dict[str, str]]:
    """OpenRouterに渡すメッセージ配列を生成。"""

    messages: List[Dict[str, str]] = []
    system_prompt = payload.system_prompt or _get_cached_base_prompt()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for item in payload.history:
        messages.append({"role": item.role, "content": item.content})
    messages.append({"role": "user", "content": payload.message})
    return messages


def _get_openrouter_headers() -> Dict[str, str]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OpenRouterのAPIキーが設定されていません。",
        )

    headers: Dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    referer = os.environ.get("OPENROUTER_SITE_URL")
    if referer:
        headers["HTTP-Referer"] = referer

    title = os.environ.get("OPENROUTER_APP_NAME")
    if title:
        headers["X-Title"] = title

    return headers


async def _call_openrouter(payload: ChatRequest) -> ChatResponse:
    request_body = {
        "model": MODEL_ID,
        "messages": _build_messages(payload),
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        try:
            response = await client.post(
                OPENROUTER_URL,
                json=request_body,
                headers=_get_openrouter_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"OpenRouterからエラー応答: {exc.response.text}",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenRouterへの接続に失敗しました。",
            ) from exc

    try:
        data = response.json()
        reply_text = data["choices"][0]["message"]["content"]
        model_name = data.get("model", MODEL_ID)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenRouterから有効な応答を取得できませんでした。",
        ) from exc

    return ChatResponse(reply=reply_text, model=model_name)


def _session_file(_: str = DEFAULT_SESSION_ID) -> Path:
    return _resolve_session_dir() / f"{DEFAULT_SESSION_ID}.json"


def _write_session_log(
    session_id: str,
    history: List[ChatMessage],
    base_system_prompt: Optional[str],
    state: DialogueState,
) -> None:
    payload = {
        "base_system_prompt": base_system_prompt,
        "messages": [message.model_dump() for message in history],
        "state": state.to_dict(),
    }

    try:
        _session_file(session_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="セッションログの書き込みに失敗しました。",
        ) from exc


def _load_session_log(session_id: str) -> Tuple[List[ChatMessage], Optional[str], DialogueState]:
    try:
        raw = _session_file(session_id).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたセッションが存在しません。",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="セッションログの読み込みに失敗しました。",
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="セッションログの形式が不正です。",
        ) from exc

    history_data = data.get("messages", [])
    history = [ChatMessage(**message) for message in history_data]

    base_prompt = data.get("base_system_prompt") or data.get("system_prompt")
    state_data = data.get("state")
    if isinstance(state_data, dict):
        state = DialogueState.from_dict(state_data)
    else:
        state = DialogueState()

    return history, base_prompt, state


def _reset_session_log(session_id: str) -> None:
    target = _session_file(session_id)
    if target.exists():
        try:
            target.unlink()
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="セッションログの初期化に失敗しました。",
            ) from exc


@router.post("", response_model=ChatResponse)
async def create_chat_completion(payload: ChatRequest) -> ChatResponse:
    if not payload.system_prompt:
        payload.system_prompt = _compose_system_prompt(None, _get_cached_base_prompt())
    return await _call_openrouter(payload)


@router.post("/random_session/start", response_model=SessionResponse)
async def start_session(payload: SessionStartRequest) -> SessionResponse:
    session_id = DEFAULT_SESSION_ID
    _reset_session_log(session_id)

    tasks = _load_current_tasks()
    base_prompt = payload.system_prompt or _get_cached_base_prompt()
    state = DialogueState(
        tasks=tasks,
        loop_limit=max(len(tasks), 1),
    )

    history: List[ChatMessage] = []
    reply: Optional[str] = None
    model_name = MODEL_ID
    trigger_message = payload.message or "会話を始めてください。"

    response = await _call_openrouter(
        ChatRequest(
            message=trigger_message,
            history=history,
            system_prompt=_compose_system_prompt(state, base_prompt),
        )
    )
    reply = response.reply
    model_name = response.model

    if payload.message:
        history.append(ChatMessage(role="user", content=payload.message))
        await state.advance(payload.message)
    history.append(ChatMessage(role="assistant", content=reply))
    if state.step == DialogueStep.TASK_LOOP and not state.tasks_introduced:
        state.tasks_introduced = True

    _write_session_log(DEFAULT_SESSION_ID, history, base_prompt, state)

    return SessionResponse(
        session_id=DEFAULT_SESSION_ID,
        history=history,
        model=model_name,
        reply=reply,
    )


@router.post("/random_session/{session_id}/continue", response_model=SessionResponse)
async def continue_session(
    session_id: str, payload: SessionContinueRequest
) -> SessionResponse:
    history, stored_prompt, state = _load_session_log(DEFAULT_SESSION_ID)
    if not state.tasks:
        state.tasks = _load_current_tasks()
        state.loop_limit = max(len(state.tasks), 1)
    base_prompt = payload.system_prompt or stored_prompt or _get_cached_base_prompt()

    await state.advance(payload.message)

    response = await _call_openrouter(
        ChatRequest(
            message=payload.message,
            history=history,
            system_prompt=_compose_system_prompt(state, base_prompt),
        )
    )

    history.append(ChatMessage(role="user", content=payload.message))
    history.append(ChatMessage(role="assistant", content=response.reply))
    if state.step == DialogueStep.TASK_LOOP and not state.tasks_introduced:
        state.tasks_introduced = True

    _write_session_log(DEFAULT_SESSION_ID, history, base_prompt, state)

    return SessionResponse(
        session_id=DEFAULT_SESSION_ID,
        history=history,
        model=response.model,
        reply=response.reply,
    )


@router.get("/random_session/{session_id}/summary")
async def get_session_summary(session_id: str) -> Dict[str, str]:
    try:
        markdown = await generate_session_markdown(DEFAULT_SESSION_ID)
        output_path = await write_session_markdown(DEFAULT_SESSION_ID, markdown)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたセッションログが見つかりません。",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="セッションログの読み取りに失敗しました。",
        ) from exc

    return {
        "session_id": DEFAULT_SESSION_ID,
        "markdown": markdown,
        "file_path": str(output_path),
    }


@router.get("/random_session/{session_id}/carryover")
async def get_carryover_tasks(session_id: str) -> Dict[str, List[Dict[str, Optional[str]]]]:
    try:
        _, _, state = _load_session_log(DEFAULT_SESSION_ID)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"セッション状態の取得に失敗しました: {exc}",
        ) from exc

    tasks = []
    for task in state.carryover_selected:
        tasks.append({
            "task": task,
            "reason": state.reason_map.get(task),
        })

    try:
        _write_current_tasks(state.carryover_selected)
    except OSError as exc:  # pragma: no cover - filesystem issues
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"current_task.md の更新に失敗しました: {exc}",
        ) from exc

    return {"carryover_tasks": tasks}
