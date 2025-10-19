#!/usr/bin/env python3
"""
VOICEVOX 版インタラクティブ音声チャットクライアント。

Push-to-Talk 方式で録音し、サーバー（/voice-chat-voicevox/...）へ送信すると
GPT 応答を VOICEVOX で音声化したデータが返ってきます。
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

import httpx
import pyaudio
from pynput import keyboard

# 設定
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "ja-JP")
VOICEVOX_SPEAKER = int(os.getenv("VOICEVOX_SPEAKER", "1"))
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16


class InteractiveVoiceChatVoiceVox:
    """インタラクティブ音声チャットクライアント（VOICEVOX版）。"""

    def __init__(self, server_url: str = SERVER_URL, language_code: str = LANGUAGE_CODE, speaker: int = VOICEVOX_SPEAKER):
        self.server_url = server_url
        self.language_code = language_code
        self.speaker = speaker
        self.session_id: Optional[str] = None

        self.audio_interface = pyaudio.PyAudio()
        self.frames: list[bytes] = []
        self.stream: Optional[pyaudio.Stream] = None
        self.is_recording = False
        self.recording_complete = threading.Event()

    def __del__(self) -> None:
        if hasattr(self, "audio_interface"):
            self.audio_interface.terminate()

    # ----------------------- 録音関連 ----------------------- #
    def record_audio_push_to_talk(self) -> bytes:
        print("🎤 スペースキーを押している間だけ録音されます...")

        self.frames = []
        self.is_recording = False
        self.recording_complete.clear()

        self.stream = self.audio_interface.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
            stream_callback=self._audio_callback,
        )

        def on_press(key):
            if key == keyboard.Key.space and not self.is_recording:
                self.is_recording = True
                print("🔴 録音中... (スペースキーを離すと送信)")

        def on_release(key):
            if key == keyboard.Key.space and self.is_recording:
                self.is_recording = False
                print("✅ 録音完了")
                self.recording_complete.set()
                return False

        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            self.stream.start_stream()
            self.recording_complete.wait()
            listener.join()

        self.stream.stop_stream()
        self.stream.close()
        self.stream = None

        if not self.frames:
            raise ValueError("音声が録音されませんでした")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.audio_interface.get_sample_size(FORMAT))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b"".join(self.frames))
        with open(tmp_path, "rb") as f:
            audio_data = f.read()
        os.unlink(tmp_path)
        return audio_data

    def _audio_callback(self, in_data, frame_count, time_info, status):
        if self.is_recording:
            self.frames.append(in_data)
        return (in_data, pyaudio.paContinue)

    # ----------------------- 再生 ----------------------- #
    def play_audio(self, audio_data: bytes) -> None:
        print("🔊 音声を再生中...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(audio_data)
        try:
            subprocess.run(["afplay", tmp_path], check=True)
            print("✅ 再生完了")
        except subprocess.CalledProcessError as exc:
            print(f"❌ 音声再生エラー: {exc}")
        except FileNotFoundError:
            print("❌ afplay が見つかりません（macOS以外では別コマンドを利用してください）")
        finally:
            os.unlink(tmp_path)

    # ----------------------- サーバー通信 ----------------------- #
    def start_session(self, audio_data: Optional[bytes] = None) -> dict:
        url = f"{self.server_url}/voice-chat-voicevox/session/start"
        data = {
            "language_code": self.language_code,
            "speaker": str(self.speaker),
        }
        files = {"audio": ("audio.wav", audio_data, "audio/wav")} if audio_data else None

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, data=data, files=files)
            resp.raise_for_status()

        self.session_id = resp.headers.get("X-Session-Id")
        user_text = base64.b64decode(resp.headers.get("X-Original-Text-Base64", "") or b"").decode("utf-8") if resp.headers.get("X-Original-Text-Base64") else ""
        reply_text = base64.b64decode(resp.headers.get("X-Response-Text-Base64", "") or b"").decode("utf-8") if resp.headers.get("X-Response-Text-Base64") else ""

        if user_text:
            print(f"📝 あなた: {user_text}")
        print(f"🤖 AI: {reply_text}")

        return {
            "audio": resp.content,
            "user_text": user_text,
            "response_text": reply_text,
            "session_id": self.session_id,
        }

    def continue_session(self, audio_data: bytes) -> dict:
        if not self.session_id:
            raise ValueError("セッションが開始されていません")

        url = f"{self.server_url}/voice-chat-voicevox/session/{self.session_id}/continue"
        data = {
            "language_code": self.language_code,
            "speaker": str(self.speaker),
        }
        files = {"audio": ("audio.wav", audio_data, "audio/wav")}

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, data=data, files=files)
            resp.raise_for_status()

        user_text = base64.b64decode(resp.headers.get("X-Original-Text-Base64", "") or b"").decode("utf-8") if resp.headers.get("X-Original-Text-Base64") else ""
        reply_text = base64.b64decode(resp.headers.get("X-Response-Text-Base64", "") or b"").decode("utf-8") if resp.headers.get("X-Response-Text-Base64") else ""

        print(f"📝 あなた: {user_text}")
        print(f"🤖 AI: {reply_text}")

        return {
            "audio": resp.content,
            "user_text": user_text,
            "response_text": reply_text,
        }

    # ----------------------- メインループ ----------------------- #
    def chat_loop(self) -> None:
        print("=" * 60)
        print("🎙️  VOICEVOX インタラクティブ音声チャット (Push-to-Talk)")
        print("=" * 60)
        print(f"サーバー: {self.server_url}")
        print(f"言語: {self.language_code}")
        print(f"VOICEVOX speaker: {self.speaker}")
        print()
        print("使い方: スペースキーで録音、離すと送信。Ctrl+C で終了。")
        print("=" * 60)
        print()

        try:
            print("🤖 AIが会話を始めます...")
            result = self.start_session(audio_data=None)
            if result["session_id"]:
                print(f"✅ セッション開始: {result['session_id']}")
            self.play_audio(result["audio"])
            print("\n" + "-" * 60 + "\n")
        except Exception as exc:
            print(f"❌ セッション開始エラー: {exc}")
            return

        while True:
            try:
                audio_data = self.record_audio_push_to_talk()
                result = self.continue_session(audio_data)
                self.play_audio(result["audio"])
                print("\n" + "-" * 60 + "\n")
            except KeyboardInterrupt:
                print("\n👋 チャットを終了します")
                break
            except ValueError as exc:
                print(f"⚠️ {exc}\n")
            except Exception as exc:
                print(f"❌ エラー: {exc}\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="VOICEVOX インタラクティブ音声チャットクライアント (Push-to-Talk)")
    parser.add_argument("--server", default=SERVER_URL, help=f"サーバーURL (デフォルト: {SERVER_URL})")
    parser.add_argument("--language", default=LANGUAGE_CODE, help=f"言語コード (デフォルト: {LANGUAGE_CODE})")
    parser.add_argument("--speaker", type=int, default=VOICEVOX_SPEAKER, help=f"VOICEVOXスピーカーID (デフォルト: {VOICEVOX_SPEAKER})")
    args = parser.parse_args()

    client = InteractiveVoiceChatVoiceVox(server_url=args.server, language_code=args.language, speaker=args.speaker)
    try:
        client.chat_loop()
    except Exception as exc:
        print(f"❌ 予期しないエラー: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
