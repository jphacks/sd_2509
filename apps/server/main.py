from fastapi import FastAPI

from apps.server.chat.random_chat import router as chat_router
from apps.server.chat.morning_chat import router as morning_router
from apps.server.tts import router as speech_router
from apps.server.voice_chat import router as voice_chat_router
from apps.server.random_voice_chat import router as random_voice_chat_router
from apps.server.morning_voice_chat import router as morning_voice_chat_router
from apps.server.voice_chat_voicevox import router as voice_chat_voicevox_router

app = FastAPI(title="AI Call Server")

# テキストチャットAPI
app.include_router(chat_router)
app.include_router(morning_router)

# 音声変換API（Speech-to-Text / Text-to-Speech）
app.include_router(speech_router)

# 音声チャット統合API（音声入力 → GPT → 音声出力）
app.include_router(voice_chat_router) # Voice Chat(random,morning分離前)
app.include_router(random_voice_chat_router) # Random Voice Chat
app.include_router(morning_voice_chat_router) # Morning Voice Chat
app.include_router(voice_chat_voicevox_router)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}
