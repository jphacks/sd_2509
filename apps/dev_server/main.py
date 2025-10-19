from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Sequence

import httpx
from fastapi import FastAPI, HTTPException, Query, status
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from pydantic import BaseModel, Field

from apps.dev_server.mock_voice import router as mock_voice_router


class NotificationPublishRequest(BaseModel):
    title: str = Field(default="サーバー通知", max_length=100)
    body: str = Field(..., max_length=280)


class NotificationEvent(BaseModel):
    id: int
    title: str
    body: str
    created_at: datetime


class NotificationPollResponse(BaseModel):
    events: List[NotificationEvent] = Field(default_factory=list)
    latest_id: Optional[int] = None


app = FastAPI(title="AI Call Dev Server", version="0.1.0")
app.include_router(mock_voice_router)

_EVENT_HISTORY: Deque[NotificationEvent] = deque(maxlen=100)
_LAST_EVENT_ID = 0
REGISTERED_TOKENS: Dict[str, "RegisteredDevice"] = {}
_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]
_CACHED_CREDENTIALS: Optional[service_account.Credentials] = None
_FIREBASE_PROJECT_ID: Optional[str] = None


class RegisterDeviceRequest(BaseModel):
    token: str = Field(..., description="FCM デバイストークン")
    platform: Optional[str] = Field(default=None)
    app_version: Optional[str] = Field(default=None)


class RegisteredDevice(BaseModel):
    token: str
    platform: Optional[str] = None
    app_version: Optional[str] = None
    registered_at: datetime
    last_seen_at: datetime


class PushSendRequest(BaseModel):
    title: str = Field(default="📬 Dev Server Push")
    body: str = Field(..., max_length=280)
    data: Optional[dict] = None
    tokens: Optional[Sequence[str]] = Field(
        default=None, description="省略時は登録済みトークン全件へ送信"
    )
    android_vibrate_pattern: Optional[Sequence[int]] = Field(
        default=None,
        description="Android 通知のバイブパターン (ミリ秒の配列)",
    )
    android_sound: Optional[str] = Field(
        default="default",
        description="Android 通知で再生するサウンド名 (raw/ などに配置したファイル)",
    )
    android_image_url: Optional[str] = Field(
        default=None, description="Android 通知で表示する画像 URL (HTTPS)"
    )
    android_ttl_seconds: Optional[int] = Field(
        default=None, description="通知メッセージの有効期間（秒）"
    )


class PushSendResponse(BaseModel):
    responses: List[dict]
    target_tokens: List[str]


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}


@app.post(
    "/notifications/publish",
    response_model=NotificationEvent,
    status_code=status.HTTP_201_CREATED,
)
async def publish_notification(
    payload: NotificationPublishRequest,
) -> NotificationEvent:
    global _LAST_EVENT_ID
    _LAST_EVENT_ID += 1
    event = NotificationEvent(
        id=_LAST_EVENT_ID,
        title=payload.title,
        body=payload.body,
        created_at=datetime.now(timezone.utc),
    )
    _EVENT_HISTORY.append(event)
    return event


@app.get("/notifications/poll", response_model=NotificationPollResponse)
async def poll_notifications(
    after: int = Query(default=0, ge=0),
) -> NotificationPollResponse:
    events = [event for event in _EVENT_HISTORY if event.id > after]
    latest_id: Optional[int]
    if _EVENT_HISTORY:
        latest_id = _EVENT_HISTORY[-1].id
    elif after > 0:
        latest_id = after
    else:
        latest_id = None
    return NotificationPollResponse(events=events, latest_id=latest_id)


def _normalize_token(token: str) -> str:
    token = token.strip()
    if not token:
        raise ValueError("空のトークンは登録できません。")
    return token


@app.post("/push/register", response_model=RegisteredDevice)
async def register_device(payload: RegisterDeviceRequest) -> RegisteredDevice:
    try:
        token = _normalize_token(payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    now = datetime.now(timezone.utc)
    existing = REGISTERED_TOKENS.get(token)
    device = RegisteredDevice(
        token=token,
        platform=payload.platform or (existing.platform if existing else None),
        app_version=payload.app_version or (existing.app_version if existing else None),
        registered_at=existing.registered_at if existing else now,
        last_seen_at=now,
    )
    REGISTERED_TOKENS[token] = device
    return device


@app.get("/push/devices", response_model=List[RegisteredDevice])
async def list_devices() -> List[RegisteredDevice]:
    return list(REGISTERED_TOKENS.values())


def _load_service_account() -> service_account.Credentials:
    global _CACHED_CREDENTIALS, _FIREBASE_PROJECT_ID
    if _CACHED_CREDENTIALS is not None:
        return _CACHED_CREDENTIALS

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "環境変数 GOOGLE_SERVICE_ACCOUNT_JSON が設定されていません。"
                "JSON 文字列またはファイルパスを指定してください。"
            ),
        )

    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        path = os.path.expanduser(raw)
        try:
            with open(path, "r", encoding="utf-8") as fp:
                info = json.load(fp)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"サービスアカウント JSON ファイルが見つかりません: {path}",
            ) from exc

    try:
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=_SCOPES
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"サービスアカウント情報が不正です: {exc}",
        ) from exc

    _CACHED_CREDENTIALS = credentials
    _FIREBASE_PROJECT_ID = info.get("project_id")
    return credentials


def _get_project_id() -> str:
    if _FIREBASE_PROJECT_ID:
        return _FIREBASE_PROJECT_ID
    credentials = _load_service_account()
    if credentials.project_id:
        return credentials.project_id
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="サービスアカウント JSON に project_id が含まれていません。",
    )


async def _send_fcm(tokens: Sequence[str], payload: PushSendRequest) -> List[dict]:
    credentials = _load_service_account()
    request = Request()
    credentials.refresh(request)
    project_id = _get_project_id()
    endpoint = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    results: List[dict] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        for token in tokens:
            android_notification = {
                "channel_id": "default",
                "sound": payload.android_sound,
                "default_sound": payload.android_sound == "default",
                "default_vibrate_timings": payload.android_vibrate_pattern is None,
                "notification_priority": "PRIORITY_HIGH",
                "visibility": "PUBLIC",
            }
            if payload.android_vibrate_pattern:
                android_notification["vibrate_timings"] = [
                    f"{value / 1000:.3f}s" for value in payload.android_vibrate_pattern
                ]
            if payload.android_image_url:
                android_notification["image"] = payload.android_image_url

            android_options = {
                "priority": "HIGH",
                "notification": android_notification,
                "ttl": "3600s",
            }
            if payload.android_ttl_seconds and payload.android_ttl_seconds > 0:
                android_options["ttl"] = f"{payload.android_ttl_seconds}s"

            body = {
                "message": {
                    "token": token,
                    "notification": {
                        "title": payload.title,
                        "body": payload.body,
                    },
                    "data": payload.data or {},
                    "android": {
                        **android_options,
                    }
                }
            }
            headers = {
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            }
            response = await client.post(endpoint, json=body, headers=headers)
            if response.status_code == 401:
                # アクセストークン期限切れ（まれに発生） → リフレッシュして再試行
                credentials.refresh(request)
                headers["Authorization"] = f"Bearer {credentials.token}"
                response = await client.post(endpoint, json=body, headers=headers)

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=exc.response.status_code,
                    detail=f"FCM HTTP v1 エラー: {exc.response.text}",
                ) from exc

            results.append(response.json())

    return results


@app.post("/push/send", response_model=PushSendResponse)
async def send_push(payload: PushSendRequest) -> PushSendResponse:
    if payload.tokens:
        target_tokens = [_normalize_token(token) for token in payload.tokens]
    else:
        target_tokens = list(REGISTERED_TOKENS.keys())

    if not target_tokens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="送信対象のトークンが登録されていません。",
        )

    try:
        responses = await _send_fcm(target_tokens, payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FCM HTTP v1 への接続に失敗しました。",
        ) from exc

    return PushSendResponse(responses=responses, target_tokens=target_tokens)
