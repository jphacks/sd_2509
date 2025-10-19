# 音声変換API（Speech-to-Text / Text-to-Speech）

Google Cloud Speech-to-Text / Text-to-Speech APIを使用した音声とテキストの双方向変換機能を提供します。

## セットアップ

### 1. Google Cloud Platform（GCP）の設定

1. [Google Cloud Console](https://console.cloud.google.com/)にアクセス
2. プロジェクトを作成または選択
3. 以下のAPIを有効化:
   - Cloud Speech-to-Text API
   - Cloud Text-to-Speech API
4. サービスアカウントを作成し、JSONキーをダウンロード
5. ダウンロードしたJSONキーファイルのパスを環境変数に設定

### 2. 環境変数の設定

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account-key.json"
```

または、`.env`ファイルに記載:

```
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account-key.json
```

### 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

## API エンドポイント

### 基本的な音声変換API

#### 1. テキストから音声への変換（Text-to-Speech）

**エンドポイント:** `POST /speech/text-to-speech`

**リクエスト例:**
```json
{
  "text": "こんにちは、今日はいい天気ですね。",
  "language_code": "ja-JP",
  "speaking_rate": 1.0,
  "pitch": 0.0
}
```

**レスポンス:** MP3形式の音声ファイル

**curlでのテスト:**
```bash
curl -X POST "http://localhost:8000/speech/text-to-speech" \
  -H "Content-Type: application/json" \
  -d '{"text": "こんにちは"}' \
  -o output.mp3
```

#### 2. 音声からテキストへの変換（Speech-to-Text）

**エンドポイント:** `POST /speech/speech-to-text`

**リクエスト:** マルチパートフォームデータ
- `audio`: 音声ファイル（WAV、MP3、FLACなど）
- `language_code`: 言語コード（デフォルト: ja-JP）

**レスポンス例:**
```json
{
  "text": "こんにちは、今日はいい天気ですね。"
}
```

**curlでのテスト:**
```bash
curl -X POST "http://localhost:8000/speech/speech-to-text" \
  -F "audio=@your_audio.wav" \
  -F "language_code=ja-JP"
```

### 音声チャット統合API（GPT連携）

#### 1. 音声入力 → GPT → 音声出力

**エンドポイント:** `POST /voice-chat/voice-to-voice`

**機能フロー:**
1. 音声ファイルをテキストに変換（Speech-to-Text）
2. テキストをGPTで処理
3. GPTの応答を音声に変換（Text-to-Speech）

**リクエスト:** マルチパートフォームデータ
- `audio`: 音声ファイル
- `language_code`: 言語コード（デフォルト: ja-JP）
- `system_prompt`: カスタムシステムプロンプト（省略可）

**レスポンス:** MP3形式の音声ファイル（GPTの応答音声）

**curlでのテスト:**
```bash
curl -X POST "http://localhost:8000/voice-chat/voice-to-voice" \
  -F "audio=@question.wav" \
  -F "language_code=ja-JP" \
  -o gpt_response.mp3
```

#### 2. 音声入力 → GPT → テキスト出力

**エンドポイント:** `POST /voice-chat/voice-to-text-chat`

**機能フロー:**
1. 音声ファイルをテキストに変換（Speech-to-Text）
2. テキストをGPTで処理
3. GPTの応答をテキストで返す

**リクエスト:** マルチパートフォームデータ
- `audio`: 音声ファイル
- `language_code`: 言語コード（デフォルト: ja-JP）
- `system_prompt`: カスタムシステムプロンプト（省略可）

**レスポンス例:**
```json
{
  "user_text": "今日の天気は？",
  "gpt_response": "申し訳ありませんが、私はリアルタイムの天気情報にアクセスできません...",
  "model": "openai/gpt-4o-mini"
}
```

**curlでのテスト:**
```bash
curl -X POST "http://localhost:8000/voice-chat/voice-to-text-chat" \
  -F "audio=@question.wav" \
  -F "language_code=ja-JP"
```

## パラメータの詳細

### Text-to-Speech パラメータ

- `text`: 音声に変換するテキスト（必須）
- `language_code`: 言語コード（デフォルト: `ja-JP`）
- `voice_name`: 音声の名前（省略可、デフォルト音声を使用）
- `speaking_rate`: 話速（0.25～4.0、デフォルト: 1.0）
- `pitch`: ピッチ（-20.0～20.0、デフォルト: 0.0）

### Speech-to-Text パラメータ

- `audio`: 音声ファイル（必須）
- `language_code`: 言語コード（デフォルト: `ja-JP`）

### サポートされている言語コード

- `ja-JP`: 日本語
- `en-US`: 英語（アメリカ）
- `en-GB`: 英語（イギリス）
- その他、Google Cloud Speech-to-Text/Text-to-Speechがサポートする言語

## 使用例（Python）

### Text-to-Speech

```python
import requests

response = requests.post(
    "http://localhost:8000/speech/text-to-speech",
    json={
        "text": "こんにちは、世界！",
        "language_code": "ja-JP",
        "speaking_rate": 1.2,
    }
)

with open("output.mp3", "wb") as f:
    f.write(response.content)
```

### Speech-to-Text

```python
import requests

with open("audio.wav", "rb") as f:
    response = requests.post(
        "http://localhost:8000/speech/speech-to-text",
        files={"audio": f},
        data={"language_code": "ja-JP"}
    )

print(response.json()["text"])
```

### 音声チャット（Voice-to-Voice）

```python
import requests

with open("question.wav", "rb") as f:
    response = requests.post(
        "http://localhost:8000/voice-chat/voice-to-voice",
        files={"audio": f},
        data={"language_code": "ja-JP"}
    )

# GPTの応答音声を保存
with open("gpt_response.mp3", "wb") as f:
    f.write(response.content)

# デバッグ用ヘッダーで認識したテキストと応答テキストを確認
print("認識したテキスト:", response.headers.get("X-Original-Text"))
print("GPTの応答テキスト:", response.headers.get("X-Response-Text"))
```

## トラブルシューティング

### 認証エラー

```
ValueError: 環境変数GOOGLE_APPLICATION_CREDENTIALSが設定されていません。
```

→ GCPのサービスアカウントキーのパスを環境変数に設定してください。

### 音声認識できない

```
HTTPException: 音声を認識できませんでした。
```

→ 音声ファイルの形式、品質、言語コードを確認してください。

### APIが有効化されていない

→ Google Cloud Consoleで以下のAPIを有効化してください:
- Cloud Speech-to-Text API
- Cloud Text-to-Speech API

## 料金

Google Cloud Speech-to-Text / Text-to-Speech APIは従量課金制です。
詳細は[公式ドキュメント](https://cloud.google.com/speech-to-text/pricing)を参照してください。

## 参考リンク

- [Google Cloud Speech-to-Text ドキュメント](https://cloud.google.com/speech-to-text/docs)
- [Google Cloud Text-to-Speech ドキュメント](https://cloud.google.com/text-to-speech/docs)
