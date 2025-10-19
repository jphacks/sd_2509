"""VOICEVOX を利用した簡易 Text-to-Speech ラッパー。"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, status


VOICEVOX_BASE_URL = os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021")


class VoiceVoxService:
    """VOICEVOX サーバーへのアクセスをラップするサービス。"""

    def __init__(self, base_url: str = VOICEVOX_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.request(
                method=method,
                url=url,
                params=params,
                data=data,
                headers=headers,
                timeout=httpx.Timeout(15.0),
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"VOICEVOX API error ({exc.response.status_code}): {exc.response.text}",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"VOICEVOX サーバーに接続できませんでした: {exc}",
            ) from exc

    def synthesize(
        self,
        text: str,
        speaker: int = 1,
        *,
        enable_interrogative_upspeak: bool = False,
        output_format: str = "wav",
    ) -> bytes:
        """テキストから音声を生成して返す。"""

        audio_query_params = {
            "speaker": speaker,
            "text": text,
        }
        if enable_interrogative_upspeak:
            audio_query_params["enable_interrogative_upspeak"] = "true"

        # audio_query
        query_resp = self._request(
            "POST",
            "/audio_query",
            params=audio_query_params,
        )
        audio_query = query_resp.json()

        # synthesis
        synthesis_params = {
            "speaker": speaker,
        }
        if enable_interrogative_upspeak:
            synthesis_params["enable_interrogative_upspeak"] = "true"
        synthesis_params["outputFormat"] = output_format
        synth_resp = self._request(
            "POST",
            "/synthesis",
            params=synthesis_params,
            data=query_resp.content,
            headers={"Content-Type": "application/json"},
        )
        return synth_resp.content


_voicevox_service: Optional[VoiceVoxService] = None


def get_voicevox_service() -> VoiceVoxService:
    global _voicevox_service
    if _voicevox_service is None:
        _voicevox_service = VoiceVoxService()
    return _voicevox_service


__all__ = ["VoiceVoxService", "get_voicevox_service"]
