"""音声変換（Speech-to-Text / Text-to-Speech）モジュール"""

from .speech_router import router
from .speech_service import get_speech_service

__all__ = ["router", "get_speech_service"]
