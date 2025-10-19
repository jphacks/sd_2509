"""VOICEVOX を利用した音声チャット統合エンドポイント。"""

from __future__ import annotations

import base64
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from apps.server.chat.random_chat import (
    ChatRequest,
    continue_session,
    start_session,
)
from apps.server.tts.speech_service import get_speech_service
from apps.server.tts.voicevox_service import get_voicevox_service
from packages.shared_schemas import SessionContinueRequest, SessionResponse, SessionStartRequest

router = APIRouter(prefix="/voice-chat-voicevox", tags=["voice-chat-voicevox"])


def _encode_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _synthesize_voice(text: str, speaker: int, language_code: str) -> bytes:
    # VOICEVOX は日本語のみ対応のため language_code は現状無視
    service = get_voicevox_service()
    return service.synthesize(text=text or " ", speaker=speaker)


@router.post("/session/start", response_class=Response)
async def voice_session_start(
    audio: Optional[UploadFile] = File(None, description="音声ファイル（省略時はAIから会話開始）"),
    language_code: str = Form("ja-JP", description="言語コード"),
    system_prompt: Optional[str] = Form(None, description="システムプロンプト"),
    session_id: Optional[str] = Form(None, description="セッションID（省略時は自動生成）"),
    speaker: int = Form(1, description="VOICEVOXのスピーカーID"),
) -> Response:
    """VOICEVOX版のセッション開始。"""

    user_text: Optional[str] = None
    speech_service = get_speech_service()

    if audio is not None:
        audio_content = await audio.read()
        user_text = speech_service.speech_to_text(
            audio_content=audio_content,
            language_code=language_code,
        )

    session_request = SessionStartRequest(
        message=user_text,
        system_prompt=system_prompt,
        session_id=session_id,
    )
    session_response: SessionResponse = await start_session(session_request)

    response_audio = _synthesize_voice(session_response.reply or "", speaker, language_code)

    return Response(
        content=response_audio,
        media_type="audio/wav",
        headers={
            "Content-Disposition": "attachment; filename=response.wav",
            "X-Session-Id": session_response.session_id or "",
            "X-Original-Text-Base64": _encode_text(user_text),
            "X-Response-Text-Base64": _encode_text(session_response.reply),
        },
    )


@router.post("/session/{session_id}/continue", response_class=Response)
async def voice_session_continue(
    session_id: str,
    audio: UploadFile = File(..., description="音声ファイル"),
    language_code: str = Form("ja-JP", description="言語コード"),
    system_prompt: Optional[str] = Form(None, description="システムプロンプト"),
    speaker: int = Form(1, description="VOICEVOXのスピーカーID"),
) -> Response:
    """VOICEVOX版のセッション継続。"""

    speech_service = get_speech_service()
    audio_content = await audio.read()
    user_text = speech_service.speech_to_text(
        audio_content=audio_content,
        language_code=language_code,
    )

    continue_request = SessionContinueRequest(
        message=user_text,
        system_prompt=system_prompt,
        session_id=session_id,
    )
    session_response: SessionResponse = await continue_session(session_id, continue_request)

    response_audio = _synthesize_voice(session_response.reply or "", speaker, language_code)

    return Response(
        content=response_audio,
        media_type="audio/wav",
        headers={
            "Content-Disposition": "attachment; filename=response.wav",
            "X-Original-Text-Base64": _encode_text(user_text),
            "X-Response-Text-Base64": _encode_text(session_response.reply),
        },
    )
