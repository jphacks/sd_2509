from __future__ import annotations

import base64
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status

router = APIRouter(prefix="/mock-voice", tags=["mock-voice"])

_AUDIO_FILE = (
    Path(__file__)
    .resolve()
    .parent
    / "assets"
    / "audio"
    / "ohayo.mp3"
)

_SESSIONS: Dict[str, int] = {}


@router.get("/static", response_class=Response)
async def get_static_voice() -> Response:
    try:
        audio_bytes = _AUDIO_FILE.read_bytes()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="モック音声ファイルが見つかりません。",
        ) from exc

    mock_text = "おはようございます。今日も良い一日をお過ごしください。"
    response_text_base64 = base64.b64encode(mock_text.encode("utf-8")).decode("ascii")

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=mock-ohayo.mp3",
            "X-Session-Id": "mock-session",
            "X-Response-Text-Base64": response_text_base64,
        },
    )


def _build_response(
    *,
    session_id: str,
    response_text: str,
    user_text: Optional[str],
    model: str = "mock-voice-v1",
) -> Response:
    try:
        response_audio = _AUDIO_FILE.read_bytes()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="モック音声ファイルが見つかりません。",
        ) from exc
    response_text_base64 = base64.b64encode(response_text.encode("utf-8")).decode("ascii")
    user_text_base64 = base64.b64encode((user_text or "").encode("utf-8")).decode("ascii")

    history_count = _SESSIONS.get(session_id, 0)

    headers = {
        "Content-Disposition": "attachment; filename=mock-ohayo.mp3",
        "X-Session-Id": session_id,
        "X-Response-Text-Base64": response_text_base64,
        "X-Original-Text-Base64": user_text_base64,
        "X-Model": model,
        "X-History-Count": str(history_count),
    }
    return Response(content=response_audio, media_type="audio/mpeg", headers=headers)


@router.post("/session/start", response_class=Response)
async def mock_session_start(
    audio: Optional[UploadFile] = File(None),
    language_code: str = Form("ja-JP"),
    system_prompt: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
) -> Response:
    if audio:
        await audio.read()

    session = session_id or str(uuid4())
    _SESSIONS[session] = 1

    if language_code.startswith("ja"):
        response_text = "おはようございます。モックセッションを開始します。"
    else:
        response_text = "Hello! Mock session started."

    user_text = "（音声入力を受信しました）" if audio else None
    return _build_response(session_id=session, response_text=response_text, user_text=user_text)


@router.post("/session/{session_id}/continue", response_class=Response)
async def mock_session_continue(
    session_id: str,
    audio: UploadFile = File(...),
    language_code: str = Form("ja-JP"),
    system_prompt: Optional[str] = Form(None),
) -> Response:
    if session_id not in _SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="セッションが見つかりません。"
        )

    await audio.read()

    _SESSIONS[session_id] += 1
    turn = _SESSIONS[session_id]

    if language_code.startswith("ja"):
        response_text = f"こちらはモック応答です。{turn} 回目のメッセージを受け取りました。"
    else:
        response_text = f"This is a mock response. Received your message #{turn}."

    user_text = "（続きの音声入力を受信しました）"
    return _build_response(session_id=session_id, response_text=response_text, user_text=user_text)
