from fastapi import FastAPI

from apps.server.chat.random_chat import router as chat_router

app = FastAPI(title="AI Call Server")

# まずはテキストチャットAPIのみ提供。音声連携は別途実装予定。
app.include_router(chat_router)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}
