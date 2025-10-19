#!/usr/bin/env python3
"""
インタラクティブ音声チャットクライアント

マイクから直接音声を入力し、サーバーに送信して応答音声を自動再生します。
スペースキーを押している間録音し、離すと送信されます。
"""

import os
import sys
import tempfile
import wave
import base64
import subprocess
import threading
from pathlib import Path

import httpx
import pyaudio
from pynput import keyboard

# 設定
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "ja-JP")
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16


class InteractiveVoiceChat:
    """インタラクティブ音声チャットクライアント"""

    def __init__(self, server_url: str = SERVER_URL, language_code: str = LANGUAGE_CODE):
        self.server_url = server_url.rstrip("/")
        self.language_code = language_code
        self.session_id = None
        self.audio_interface = pyaudio.PyAudio()
        
        # 録音制御用フラグ
        self.is_recording = False
        self.recording_complete = threading.Event()
        self.frames = []
        self.stream = None

    def __del__(self):
        """クリーンアップ"""
        if hasattr(self, "audio_interface"):
            self.audio_interface.terminate()

    def record_audio_push_to_talk(self) -> bytes:
        """
        スペースキーを押している間だけマイクから音声を録音（Push-to-Talk方式）

        Returns:
            WAV形式の音声データ
        """
        print("🎤 スペースキーを押している間録音されます...")
        
        self.frames = []
        self.is_recording = False
        self.recording_complete.clear()
        
        # 音声ストリームを開く
        self.stream = self.audio_interface.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
            stream_callback=self._audio_callback,
        )
        
        # キーボードリスナーを開始
        def on_press(key):
            if key == keyboard.Key.space and not self.is_recording:
                self.is_recording = True
                print("🔴 録音中... (スペースキーを離すと送信)")
        
        def on_release(key):
            if key == keyboard.Key.space and self.is_recording:
                self.is_recording = False
                print("✅ 録音完了")
                self.recording_complete.set()
                return False  # リスナーを停止
        
        # キーボードイベントをリッスン
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            self.stream.start_stream()
            # スペースキーが離されるまで待機
            self.recording_complete.wait()
            listener.join()
        
        # ストリームを停止
        self.stream.stop_stream()
        self.stream.close()
        self.stream = None
        
        if not self.frames:
            raise ValueError("音声が録音されませんでした")
        
        # WAVファイルとしてメモリに保存
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_path = temp_file.name
            with wave.open(temp_path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.audio_interface.get_sample_size(FORMAT))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b"".join(self.frames))
            
            # ファイルから読み込み
            with open(temp_path, "rb") as f:
                audio_data = f.read()
        
        # 一時ファイルを削除
        os.unlink(temp_path)
        
        return audio_data
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """録音中のみデータを保存するコールバック"""
        if self.is_recording:
            self.frames.append(in_data)
        return (in_data, pyaudio.paContinue)

    def play_audio(self, audio_data: bytes):
        """
        音声を再生（macOSのafplayを使用）

        Args:
            audio_data: 音声データ（MP3形式）
        """
        print("🔊 音声を再生中...")

        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
            temp_path = temp_file.name
            temp_file.write(audio_data)

        try:
            # afplayで再生
            subprocess.run(["afplay", temp_path], check=True)
            print("✅ 再生完了")
        except subprocess.CalledProcessError as e:
            print(f"❌ 音声再生エラー: {e}")
        except FileNotFoundError:
            print("❌ afplayコマンドが見つかりません（macOS以外では動作しません）")
        finally:
            # 一時ファイルを削除
            os.unlink(temp_path)

    def start_session(self, audio_data: bytes = None) -> dict:
        """
        新しいセッションを開始

        Args:
            audio_data: 音声データ（Noneの場合、AIから会話を開始）

        Returns:
            レスポンス情報
        """
        url = f"{self.server_url}/voice-chat/session/start"
        
        data = {"language_code": self.language_code}
        
        # audio_dataがある場合のみファイルを送信
        if audio_data:
            files = {"audio": ("audio.wav", audio_data, "audio/wav")}
            print("📤 サーバーに送信中...")
        else:
            files = None
            print("📤 セッションを開始中（AIから会話開始）...")
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, files=files, data=data)
            response.raise_for_status()

            # ヘッダーから情報を取得
            self.session_id = response.headers.get("X-Session-Id")
            user_text_b64 = response.headers.get("X-Original-Text-Base64", "")
            response_text_b64 = response.headers.get("X-Response-Text-Base64", "")

            # Base64デコード
            user_text = base64.b64decode(user_text_b64).decode("utf-8") if user_text_b64 else ""
            response_text = base64.b64decode(response_text_b64).decode("utf-8") if response_text_b64 else ""

            if user_text:
                print(f"📝 あなた: {user_text}")
            print(f"🤖 AI: {response_text}")

            return {
                "audio": response.content,
                "user_text": user_text,
                "response_text": response_text,
                "session_id": self.session_id,
            }

    def continue_session(self, audio_data: bytes) -> dict:
        """
        既存のセッションを継続

        Args:
            audio_data: 音声データ

        Returns:
            レスポンス情報
        """
        if not self.session_id:
            raise ValueError("セッションが開始されていません")

        url = f"{self.server_url}/voice-chat/session/{self.session_id}/continue"
        
        files = {"audio": ("audio.wav", audio_data, "audio/wav")}
        data = {"language_code": self.language_code}

        print("📤 サーバーに送信中...")
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, files=files, data=data)
            response.raise_for_status()

            # ヘッダーから情報を取得
            user_text_b64 = response.headers.get("X-Original-Text-Base64", "")
            response_text_b64 = response.headers.get("X-Response-Text-Base64", "")

            # Base64デコード
            user_text = base64.b64decode(user_text_b64).decode("utf-8") if user_text_b64 else ""
            response_text = base64.b64decode(response_text_b64).decode("utf-8") if response_text_b64 else ""

            print(f"📝 あなた: {user_text}")
            print(f"🤖 AI: {response_text}")

            return {
                "audio": response.content,
                "user_text": user_text,
                "response_text": response_text,
            }

    def chat_loop(self):
        """
        インタラクティブな音声チャットループ（Push-to-Talk方式）
        """
        print("=" * 60)
        print("🎙️  インタラクティブ音声チャット (Push-to-Talk)")
        print("=" * 60)
        print(f"サーバー: {self.server_url}")
        print(f"言語: {self.language_code}")
        print()
        print("使い方:")
        print("  - スペースキーを押している間だけ録音されます")
        print("  - スペースキーを離すと自動送信されます")
        print("  - Ctrl+C で終了")
        print("=" * 60)
        print()

        # 最初にAIから会話を開始
        try:
            print("🤖 AIが会話を始めます...")
            result = self.start_session(audio_data=None)
            print(f"✅ セッション開始: {result['session_id']}")
            
            # AIの最初の挨拶を再生
            self.play_audio(result["audio"])
            
            print()
            print("-" * 60)
            print()
        except Exception as e:
            print(f"❌ セッション開始エラー: {e}")
            return

        while True:
            try:
                # スペースキーを押して録音
                audio_data = self.record_audio_push_to_talk()

                # サーバーに送信（セッション継続）
                result = self.continue_session(audio_data)

                # 音声を再生
                self.play_audio(result["audio"])
                
                print()
                print("-" * 60)
                print()

            except KeyboardInterrupt:
                print("\n👋 チャットを終了します")
                break
            except ValueError as e:
                print(f"⚠️  {e}")
                print()
            except Exception as e:
                print(f"❌ エラー: {e}")
                print()


def main():
    """メイン関数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="インタラクティブ音声チャットクライアント (Push-to-Talk)"
    )
    parser.add_argument(
        "--server",
        default=SERVER_URL,
        help=f"サーバーURL (デフォルト: {SERVER_URL})",
    )
    parser.add_argument(
        "--language",
        default=LANGUAGE_CODE,
        help=f"言語コード (デフォルト: {LANGUAGE_CODE})",
    )

    args = parser.parse_args()

    # チャットクライアントを起動
    client = InteractiveVoiceChat(
        server_url=args.server,
        language_code=args.language,
    )
    
    try:
        client.chat_loop()
    except Exception as e:
        print(f"❌ 予期しないエラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
