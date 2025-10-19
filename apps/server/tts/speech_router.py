"""音声変換用のAPIルーター"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional

from .speech_service import get_speech_service


router = APIRouter(prefix="/speech", tags=["speech"])


class TextToSpeechRequest(BaseModel):
    """テキストから音声への変換リクエスト"""

    text: str = Field(..., description="音声に変換するテキスト")
    language_code: str = Field("ja-JP", description="言語コード")
    voice_name: Optional[str] = Field(None, description="使用する音声の名前")
    speaking_rate: float = Field(1.0, ge=0.25, le=4.0, description="話速")
    pitch: float = Field(0.0, ge=-20.0, le=20.0, description="ピッチ")


class SpeechToTextResponse(BaseModel):
    """音声からテキストへの変換レスポンス"""

    text: str = Field(..., description="認識されたテキスト")


@router.post("/text-to-speech", response_class=Response)
async def text_to_speech(request: TextToSpeechRequest) -> Response:
    """
    テキストを音声に変換

    Args:
        request: 変換リクエスト

    Returns:
        音声データ（MP3形式）
    """
    service = get_speech_service()
    audio_content = service.text_to_speech(
        text=request.text,
        language_code=request.language_code,
        voice_name=request.voice_name,
        speaking_rate=request.speaking_rate,
        pitch=request.pitch,
    )

    return Response(
        content=audio_content,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=speech.mp3",
        },
    )


@router.post("/speech-to-text", response_model=SpeechToTextResponse)
async def speech_to_text(
    audio: UploadFile = File(..., description="音声ファイル"),
    language_code: str = Form("ja-JP", description="言語コード"),
) -> SpeechToTextResponse:
    """
    音声をテキストに変換

    Args:
        audio: 音声ファイル（WAV、FLAC、MP3など）
        language_code: 言語コード

    Returns:
        認識されたテキスト
    """
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="音声ファイルをアップロードしてください。",
        )

    # 音声ファイルを読み込み
    audio_content = await audio.read()

    service = get_speech_service()
    text = service.speech_to_text(
        audio_content=audio_content,
        language_code=language_code,
    )

    return SpeechToTextResponse(text=text)
