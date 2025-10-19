# AI Call - 音声対話型日記アプリ

音声でAIと会話しながら日記をつけるアプリのバックエンドサーバー

## 機能

- 🎤 **音声入力** → テキスト変換 → GPT処理 → 音声出力
- 💬 **会話履歴の保存** - セッション管理で継続的な対話
- 🤖 **AI**: GPT-4o-mini (OpenRouter)
- 🔊 **音声処理**: Google Cloud Speech-to-Text / Text-to-Speech

## クイックスタート

### 1. 必要なもの
- Python 3.8+
- [Google Cloud Platform](https://console.cloud.google.com/) アカウント
- [OpenRouter](https://openrouter.ai/) APIキー

### 2. Google Cloud設定
1. GCPで以下のAPIを有効化:
   - [Cloud Speech-to-Text API](https://console.cloud.google.com/apis/library/speech.googleapis.com)
   - [Cloud Text-to-Speech API](https://console.cloud.google.com/apis/library/texttospeech.googleapis.com)
2. サービスアカウントを作成してJSONキーをダウンロード

### 3. インストール
```bash
# 依存パッケージをインストール
pip install -r requirements.txt
```

### 4. 環境変数を設定
`.env`ファイルを作成:
```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
OPENROUTER_API_KEY=sk-or-v1-xxxxx
```

### 5. サーバー起動
```bash
python -m apps.server.dev_server
```

→ http://localhost:8000/docs でAPIドキュメントを確認

## 使い方

### 基本: 音声で会話

```bash
# テスト音声を作成
say -o test.aiff "今日はとても良い天気でした"
afconvert test.aiff test.wav -d LEI16

# 音声→音声で返答
curl -X POST "http://localhost:8000/voice-chat/voice-to-voice" \
  -F "audio=@test.wav" \
  -F "language_code=ja-JP" \
  --output response.mp3

afplay response.mp3
```

### セッション管理（会話履歴を保持）

```bash
# 1. セッション開始
say -o input1.aiff "今日は友達とカフェに行きました"
afconvert input1.aiff input1.wav -d LEI16

curl -v -X POST "http://localhost:8000/voice-chat/session/start" \
  -F "audio=@input1.wav" \
  -F "language_code=ja-JP" \
  --output response1.mp3

# レスポンスヘッダーからセッションIDをコピー
# 例: X-Session-Id: abc123def456

afplay response1.mp3
# AIの応答: 「それは楽しそうですね！どんなカフェでしたか？」

# 2. 会話を継続（セッションIDを使用）
say -o input2.aiff "駅前の新しいカフェで、とても落ち着いた雰囲気でした"
afconvert input2.aiff input2.wav -d LEI16

curl -X POST "http://localhost:8000/voice-chat/session/abc123def456/continue" \
  -F "audio=@input2.wav" \
  -F "language_code=ja-JP" \
  --output response2.mp3

afplay response2.mp3
# AIの応答: 「落ち着いた雰囲気、いいですね！友達とどんな話をしましたか？」

# 3. さらに継続
say -o input3.aiff "最近の仕事の話や趣味の話をして盛り上がりました"
afconvert input3.aiff input3.wav -d LEI16

curl -X POST "http://localhost:8000/voice-chat/session/abc123def456/continue" \
  -F "audio=@input3.wav" \
  -F "language_code=ja-JP" \
  --output response3.mp3

afplay response3.mp3
# AIの応答: 「盛り上がって良かったですね！どんな趣味の話をしたんですか？」

# 4. 会話履歴を確認
cat apps/server/chat/session_logs/abc123def456.json
# 全ての会話がJSON形式で保存されている
```

**ポイント:**
- セッションIDを使えば、過去の会話を覚えたまま対話を続けられる
- 会話履歴は自動的に`session_logs/`に保存される
- 何回でも同じセッションIDで会話を継続できる

## 主なエンドポイント

### 基本エンドポイント
| エンドポイント | 説明 |
|---|---|
| `POST /voice-chat/voice-to-voice` | 音声→音声（単発） |
| `POST /voice-chat/session/start` | セッション開始（音声→音声） |
| `POST /voice-chat/session/{id}/continue` | セッション継続（音声→音声） |
| `POST /chat` | テキストチャット（単発） |
| `POST /chat/session/start` | セッション開始（テキスト） |

### モーニングコール機能（morning_voice_chat.py）
朝の会話に特化したエンドポイント

| エンドポイント | 説明 |
|---|---|
| `POST /morning-voice-chat/session/start` | モーニングセッション開始（音声→音声） |
| `POST /morning-voice-chat/session/{id}/continue` | モーニングセッション継続（音声→音声） |
| `POST /morning-voice-chat/voice-to-voice` | モーニング音声チャット（単発） |

**使い方例:**
```bash
# モーニングセッション開始
curl -X POST "http://localhost:8000/morning-voice-chat/session/start" \
  -F "audio=@morning_greeting.wav" \
  -F "language_code=ja-JP" \
  --output morning_response.mp3
```

### ランダム会話機能（random_voice_chat.py）
ランダムな話題での会話エンドポイント

| エンドポイント | 説明 |
|---|---|
| `POST /random-voice-chat/session/start` | ランダムセッション開始（音声→音声） |
| `POST /random-voice-chat/session/{id}/continue` | ランダムセッション継続（音声→音声） |
| `POST /random-voice-chat/voice-to-voice` | ランダム音声チャット（単発） |

**使い方例:**
```bash
# ランダムセッション開始
curl -X POST "http://localhost:8000/random-voice-chat/session/start" \
  -F "audio=@random_topic.wav" \
  -F "language_code=ja-JP" \
  --output random_response.mp3
```

詳細: http://localhost:8000/docs

## トラブルシューティング

### Google Cloud APIエラー
```bash
# APIを有効化して数分待つ
# https://console.cloud.google.com/apis/dashboard
```

### 環境変数エラー
```bash
# .envファイルを確認
echo $GOOGLE_APPLICATION_CREDENTIALS
```

### 依存パッケージエラー
```bash
pip install -r requirements.txt
```

## 参考

- [APIドキュメント](http://localhost:8000/docs)
- [Google Cloud Speech API](https://cloud.google.com/speech-to-text/docs)
- [OpenRouter](https://openrouter.ai/docs)
