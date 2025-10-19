from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """過去のメッセージを保持するシンプルなチャット履歴要素。"""

    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    """ユーザーから受け取るチャット問い合わせ。"""

    message: str = Field(..., min_length=1)
    history: List[ChatMessage] = Field(default_factory=list)
    system_prompt: Optional[str] = None


class ChatResponse(BaseModel):
    """チャット応答をフロントエンドへ返す際のフォーマット。"""

    reply: str
    model: str = "openai/gpt-4o-mini"


class SessionStartRequest(BaseModel):
    """チャットセッションを初期化する際の入力。"""

    session_id: Optional[str] = None
    message: Optional[str] = None
    system_prompt: Optional[str] = None


class SessionContinueRequest(BaseModel):
    """既存セッションでユーザーから新規発話を受け取る際の入力。"""

    message: str = Field(..., min_length=1)
    system_prompt: Optional[str] = None


class SessionResponse(BaseModel):
    """セッション状態と最新応答をまとめたレスポンス。"""

    session_id: str
    history: List[ChatMessage]
    model: str
    reply: Optional[str] = None
