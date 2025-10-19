"""Google Cloud Speech-to-Text/Text-to-Speechサービス"""

import contextlib
import os
import wave
from io import BytesIO
from typing import Optional, Tuple

from google.cloud import speech_v1 as speech
from google.cloud import texttospeech
from fastapi import HTTPException, status


class SpeechService:
    """音声認識と音声合成を提供するサービスクラス"""

    def __init__(self):
        """GCP認証情報を設定"""
        # GOOGLE_APPLICATION_CREDENTIALS環境変数でjsonキーファイルのパスを指定
        credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not credentials_path:
            raise ValueError(
                "環境変数GOOGLE_APPLICATION_CREDENTIALSが設定されていません。"
            )

        self.speech_client = speech.SpeechClient()
        self.tts_client = texttospeech.TextToSpeechClient()

    def _infer_wav_parameters(self, audio_content: bytes) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """WAVヘッダからサンプリングレート等を推測する。"""
        try:
            with contextlib.closing(wave.open(BytesIO(audio_content))) as wav_reader:
                sample_rate = wav_reader.getframerate()
                channels = wav_reader.getnchannels()
                sample_width = wav_reader.getsampwidth()
                return sample_rate or None, channels or None, sample_width or None
        except (wave.Error, EOFError):
            return None, None, None

    def speech_to_text(
        self,
        audio_content: bytes,
        language_code: str = "ja-JP",
        sample_rate_hertz: Optional[int] = None,
        encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.LINEAR16,
    ) -> str:
        """
        音声データをテキストに変換

        Args:
            audio_content: 音声データ（バイト列）
            language_code: 言語コード（デフォルト: ja-JP）
            sample_rate_hertz: サンプリングレート（省略可）
            encoding: オーディオエンコーディング（デフォルト: LINEAR16）

        Returns:
            認識されたテキスト

        Raises:
            HTTPException: 音声認識に失敗した場合
        """
        try:
            inferred_rate = sample_rate_hertz
            inferred_channels: Optional[int] = None
            inferred_width: Optional[int] = None

            if sample_rate_hertz is None:
                inferred_rate, inferred_channels, inferred_width = self._infer_wav_parameters(audio_content)

            if inferred_rate is None:
                # Google Cloud Speech APIへのエラーを避けるためのデフォルト値
                inferred_rate = 16000

            if encoding == speech.RecognitionConfig.AudioEncoding.LINEAR16 and inferred_width is not None:
                # 16bit 以外なら自動判別に任せる
                if inferred_width != 2:
                    encoding = speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED

            if inferred_channels is not None and inferred_channels > 1:
                # マルチチャンネルのまま扱うと認識精度が落ちる可能性があるため警告的に400を返す
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="2チャンネル以上の音声は現在サポートされていません。モノラル音声を送信してください。",
                )

            audio = speech.RecognitionAudio(content=audio_content)

            config = speech.RecognitionConfig(
                encoding=encoding,
                sample_rate_hertz=inferred_rate,
                language_code=language_code,
                enable_automatic_punctuation=True,  # 自動句読点
            )

            response = self.speech_client.recognize(config=config, audio=audio)

            if not response.results:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="音声を認識できませんでした。",
                )

            # 最も信頼度の高い結果を返す
            transcript = response.results[0].alternatives[0].transcript
            return transcript

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"音声認識エラー: {str(exc)}",
            ) from exc

    def text_to_speech(
        self,
        text: str,
        language_code: str = "ja-JP",
        voice_name: Optional[str] = "ja-JP-Chirp3-HD-Achernar",
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
    ) -> bytes:
        """
        テキストを音声データに変換

        Args:
            text: 変換するテキスト
            language_code: 言語コード（デフォルト: ja-JP）
            voice_name: 音声の名前（デフォルト: ja-JP-Neural2-B）
            speaking_rate: 話速（0.25～4.0、デフォルト: 1.0）
            pitch: ピッチ（-20.0～20.0、デフォルト: 0.0）

        Returns:
            音声データ（MP3形式のバイト列）

        Raises:
            HTTPException: 音声合成に失敗した場合
        """
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)

            # 音声の設定
            if voice_name:
                voice = texttospeech.VoiceSelectionParams(
                    language_code=language_code,
                    name=voice_name,
                )
            else:
                # デフォルト音声を使用
                voice = texttospeech.VoiceSelectionParams(
                    language_code=language_code,
                    ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
                )

            # オーディオ設定
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=speaking_rate,
                pitch=pitch,
            )

            response = self.tts_client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )

            return response.audio_content

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"音声合成エラー: {str(exc)}",
            ) from exc


# グローバルインスタンス（遅延初期化）
_speech_service: Optional[SpeechService] = None


def get_speech_service() -> SpeechService:
    """SpeechServiceのシングルトンインスタンスを取得"""
    global _speech_service
    if _speech_service is None:
        _speech_service = SpeechService()
    return _speech_service
