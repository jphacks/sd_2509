"""音声を使ったチャット統合エンドポイント"""

import base64
from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from typing import Optional
from fastapi.responses import Response

from apps.server.chat.random_chat import (
    _call_openrouter,
    start_session,
    continue_session,
    ChatRequest,
)
from apps.server.tts.speech_service import get_speech_service
from packages.shared_schemas import (
    SessionStartRequest,
    SessionContinueRequest,
    SessionResponse,
)

router = APIRouter(prefix="/random-voice-chat", tags=["random-voice-chat"])


class VoiceChatResponse(BaseModel):
    """音声チャットのレスポンス（テキストと音声の両方を返す）"""

    text: str = Field(..., description="GPTの応答テキスト")
    audio_base64: Optional[str] = Field(None, description="音声データ（Base64エンコード）")


@router.post("/voice-to-voice", response_class=Response)
async def voice_to_voice_chat(
    audio: UploadFile = File(..., description="音声ファイル（質問）"),
    language_code: str = Form("ja-JP", description="言語コード"),
    system_prompt: Optional[str] = Form(None, description="システムプロンプト"),
) -> Response:
    """
    音声を受け取り、GPTに処理させて、音声で返す

    1. 音声 → テキスト変換（Speech-to-Text）
    2. テキスト → GPT処理（gpt_chat.py）
    3. GPT応答 → 音声変換（Text-to-Speech）

    Args:
        audio: 音声ファイル
        language_code: 言語コード
        system_prompt: カスタムシステムプロンプト（省略可）

    Returns:
        GPTの応答音声（MP3形式）
    """
    # 音声ファイルを読み込み
    audio_content = await audio.read()

    # 1. 音声からテキストに変換
    service = get_speech_service()
    user_text = service.speech_to_text(
        audio_content=audio_content,
        language_code=language_code,
    )

    # 2. GPTで処理
    chat_request = ChatRequest(
        message=user_text,
        history=[],
        system_prompt=system_prompt,
    )
    chat_response = await _call_openrouter(chat_request)

    # 3. GPTの応答をテキストから音声に変換
    response_audio = service.text_to_speech(
        text=chat_response.reply,
        language_code=language_code,
    )

    # 日本語テキストをBase64エンコード（HTTPヘッダーはlatin-1のみサポート）
    user_text_encoded = base64.b64encode(user_text.encode("utf-8")).decode("ascii")
    response_text_encoded = base64.b64encode(chat_response.reply.encode("utf-8")).decode("ascii")

    return Response(
        content=response_audio,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=response.mp3",
            "X-Original-Text-Base64": user_text_encoded,  # Base64エンコードされた認識テキスト
            "X-Response-Text-Base64": response_text_encoded,  # Base64エンコードされた応答テキスト
        },
    )


@router.post("/voice-to-text-chat")
async def voice_to_text_chat(
    audio: UploadFile = File(..., description="音声ファイル（質問）"),
    language_code: str = Form("ja-JP", description="言語コード"),
    system_prompt: Optional[str] = Form(None, description="システムプロンプト"),
) -> dict:
    """
    音声を受け取り、GPTに処理させて、テキストで返す

    1. 音声 → テキスト変換（Speech-to-Text）
    2. テキスト → GPT処理（gpt_chat.py）

    Args:
        audio: 音声ファイル
        language_code: 言語コード
        system_prompt: カスタムシステムプロンプト（省略可）

    Returns:
        認識したテキストとGPTの応答テキスト
    """
    # 音声ファイルを読み込み
    audio_content = await audio.read()

    # 1. 音声からテキストに変換
    service = get_speech_service()
    user_text = service.speech_to_text(
        audio_content=audio_content,
        language_code=language_code,
    )

    # 2. GPTで処理
    chat_request = ChatRequest(
        message=user_text,
        history=[],
        system_prompt=system_prompt,
    )
    chat_response = await _call_openrouter(chat_request)

    return {
        "user_text": user_text,
        "gpt_response": chat_response.reply,
        "model": chat_response.model,
    }


# ==================== セッション管理付き音声チャット ====================


@router.post("/session/start", response_class=Response)
async def voice_session_start(
    audio: Optional[UploadFile] = File(None, description="音声ファイル（省略時は相手から会話開始）"),
    language_code: str = Form("ja-JP", description="言語コード"),
    system_prompt: Optional[str] = Form(None, description="システムプロンプト"),
    session_id: Optional[str] = Form(None, description="セッションID（省略時は自動生成）"),
) -> Response:
    """
    音声でセッションを開始し、音声で返す

    1. 音声 → テキスト変換（Speech-to-Text）※音声ファイルがある場合
    2. セッション開始（gpt_chat.start_session）
    3. GPT応答 → 音声変換（Text-to-Speech）

    Args:
        audio: 音声ファイル（省略可。省略時は相手から会話を始める）
        language_code: 言語コード
        system_prompt: カスタムシステムプロンプト（省略可）
        session_id: セッションID（省略時は自動生成）

    Returns:
        GPTの応答音声（MP3形式）
        ヘッダーにセッションIDと認識テキストを含む
    """
    user_text: Optional[str] = None
    
    # 1. 音声ファイルがある場合は、音声からテキストに変換
    if audio is not None:
        audio_content = await audio.read()
        service = get_speech_service()
        user_text = service.speech_to_text(
            audio_content=audio_content,
            language_code=language_code,
        )

    # 2. セッション開始
    session_request = SessionStartRequest(
        message=user_text,  # Noneの場合、相手から会話を始める
        system_prompt=system_prompt,
        session_id=session_id,
    )
    session_response: SessionResponse = await start_session(session_request)

    # 3. GPTの応答をテキストから音声に変換
    service = get_speech_service()
    response_audio = service.text_to_speech(
        text=session_response.reply or "",
        language_code=language_code,
    )

    # 日本語テキストをBase64エンコード
    user_text_encoded = base64.b64encode((user_text or "").encode("utf-8")).decode("ascii")
    response_text_encoded = base64.b64encode(
        (session_response.reply or "").encode("utf-8")
    ).decode("ascii")

    return Response(
        content=response_audio,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=response.mp3",
            "X-Session-Id": session_response.session_id,
            "X-Original-Text-Base64": user_text_encoded,
            "X-Response-Text-Base64": response_text_encoded,
            "X-Model": session_response.model,
        },
    )


@router.post("/session/{session_id}/continue", response_class=Response)
async def voice_session_continue(
    session_id: str,
    audio: UploadFile = File(..., description="音声ファイル（続きの質問）"),
    language_code: str = Form("ja-JP", description="言語コード"),
    system_prompt: Optional[str] = Form(None, description="システムプロンプト"),
) -> Response:
    """
    既存セッションで音声会話を継続し、音声で返す

    1. 音声 → テキスト変換（Speech-to-Text）
    2. セッション継続（gpt_chat.continue_session）
    3. GPT応答 → 音声変換（Text-to-Speech）

    Args:
        session_id: セッションID
        audio: 音声ファイル
        language_code: 言語コード
        system_prompt: カスタムシステムプロンプト（省略可）

    Returns:
        GPTの応答音声（MP3形式）
        ヘッダーに認識テキストと会話履歴数を含む
    """
    # 音声ファイルを読み込み
    audio_content = await audio.read()

    # 1. 音声からテキストに変換
    service = get_speech_service()
    user_text = service.speech_to_text(
        audio_content=audio_content,
        language_code=language_code,
    )

    # 2. セッション継続
    continue_request = SessionContinueRequest(
        message=user_text,
        system_prompt=system_prompt,
    )
    session_response: SessionResponse = await continue_session(
        session_id, continue_request
    )

    # 3. GPTの応答をテキストから音声に変換
    response_audio = service.text_to_speech(
        text=session_response.reply or "",
        language_code=language_code,
    )

    # 日本語テキストをBase64エンコード
    user_text_encoded = base64.b64encode(user_text.encode("utf-8")).decode("ascii")
    response_text_encoded = base64.b64encode(
        (session_response.reply or "").encode("utf-8")
    ).decode("ascii")

    return Response(
        content=response_audio,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "attachment; filename=response.mp3",
            "X-Session-Id": session_response.session_id,
            "X-Original-Text-Base64": user_text_encoded,
            "X-Response-Text-Base64": response_text_encoded,
            "X-Model": session_response.model,
            "X-History-Count": str(len(session_response.history)),
        },
    )


@router.post("/session/start/text-response", response_model=SessionResponse)
async def voice_session_start_text(
    audio: UploadFile = File(..., description="音声ファイル（最初の質問）"),
    language_code: str = Form("ja-JP", description="言語コード"),
    system_prompt: Optional[str] = Form(None, description="システムプロンプト"),
    session_id: Optional[str] = Form(None, description="セッションID（省略時は自動生成）"),
) -> SessionResponse:
    """
    音声でセッションを開始し、テキストで返す（デバッグ用）

    Args:
        audio: 音声ファイル
        language_code: 言語コード
        system_prompt: カスタムシステムプロンプト（省略可）
        session_id: セッションID（省略時は自動生成）

    Returns:
        セッション情報と応答テキスト
    """
    # 音声ファイルを読み込み
    audio_content = await audio.read()

    # 音声からテキストに変換
    service = get_speech_service()
    user_text = service.speech_to_text(
        audio_content=audio_content,
        language_code=language_code,
    )

    # セッション開始
    session_request = SessionStartRequest(
        message=user_text,
        system_prompt=system_prompt,
        session_id=session_id,
    )
    return await start_session(session_request)


@router.post("/session/{session_id}/continue/text-response", response_model=SessionResponse)
async def voice_session_continue_text(
    session_id: str,
    audio: UploadFile = File(..., description="音声ファイル（続きの質問）"),
    language_code: str = Form("ja-JP", description="言語コード"),
    system_prompt: Optional[str] = Form(None, description="システムプロンプト"),
) -> SessionResponse:
    """
    既存セッションで音声会話を継続し、テキストで返す（デバッグ用）

    Args:
        session_id: セッションID
        audio: 音声ファイル
        language_code: 言語コード
        system_prompt: カスタムシステムプロンプト（省略可）

    Returns:
        セッション情報と応答テキスト
    """
    # 音声ファイルを読み込み
    audio_content = await audio.read()

    # 音声からテキストに変換
    service = get_speech_service()
    user_text = service.speech_to_text(
        audio_content=audio_content,
        language_code=language_code,
    )

    # セッション継続
    continue_request = SessionContinueRequest(
        message=user_text,
        system_prompt=system_prompt,
    )
    return await continue_session(session_id, continue_request)
