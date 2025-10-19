# インタラクティブ音声チャット

コマンドライン上でスペースキーを押している間だけマイクから音声を入力し、AIの応答音声を自動再生するクライアントです（Push-to-Talk方式）。

## セットアップ

### 1. 依存パッケージのインストール

macOSでは、まず`portaudio`をインストールする必要があります:

```bash
brew install portaudio
```

次に、Pythonパッケージをインストール:

```bash
pip install -r requirements.txt
```

または`uv`を使用している場合:

```bash
uv add pyaudio pynput
```

### 2. サーバーの起動

別のターミナルでサーバーを起動しておきます:

```bash
cd apps/server
uvicorn main:app --reload
```

## 使い方

### 基本的な使い方

```bash
uv run python apps/server/interactive_voice_chat.py
```

実行すると、以下のように動作します:

1. AIが最初に挨拶してくれる
2. **スペースキーを押している間だけ録音される**（Push-to-Talk）
3. スペースキーを離すと自動的にサーバーに送信
4. AIの応答テキストが表示される
5. AIの応答音声が自動再生される
6. 続けて会話可能（セッションは保持されます）
7. `Ctrl+C`で終了

### オプション

```bash
# サーバーURLを指定
python apps/server/interactive_voice_chat.py --server http://localhost:8000

# 言語を指定
python apps/server/interactive_voice_chat.py --language en-US
```

### 環境変数での設定

`.env`ファイルや環境変数でデフォルト値を設定できます:

```bash
export SERVER_URL="http://localhost:8000"
export LANGUAGE_CODE="ja-JP"
python apps/server/interactive_voice_chat.py
```

## 実行例

```
============================================================
🎙️  インタラクティブ音声チャット (Push-to-Talk)
============================================================
サーバー: http://localhost:8000
言語: ja-JP

使い方:
  - スペースキーを押している間だけ録音されます
  - スペースキーを離すと自動送信されます
  - Ctrl+C で終了
============================================================

🤖 AIが会話を始めます...
📤 セッションを開始中（AIから会話開始）...
🤖 AI: こんにちは！今日はどのようなお手伝いができますか？
✅ セッション開始: f241b28a4bf24ca785eb05673f9bcab3
🔊 音声を再生中...
✅ 再生完了

------------------------------------------------------------

🎤 スペースキーを押している間録音されます...
🔴 録音中... (スペースキーを離すと送信)
✅ 録音完了
📤 サーバーに送信中...
📝 あなた: 今日の天気はどうですか
🤖 AI: 申し訳ございませんが、私はリアルタイムの天気情報にアクセスできません。
🔊 音声を再生中...
✅ 再生完了

------------------------------------------------------------
```

## トラブルシューティング

### マイクが認識されない

PyAudioのデバイス設定を確認:

```python
import pyaudio
p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    print(f"{i}: {info['name']}")
```

### スペースキーが反応しない

- macOSでは、アクセシビリティの権限が必要な場合があります
- システム環境設定 → セキュリティとプライバシー → アクセシビリティ → ターミナル/iTerm2を許可

### 音声が再生されない

- macOS以外では`afplay`が使えません。他のOSでは音声再生部分の実装を変更する必要があります
- 音声出力デバイスが正しく設定されているか確認してください

### サーバーに接続できない

- サーバーが起動しているか確認: `http://localhost:8000/docs`
- ファイアウォール設定を確認
- `--server`オプションで正しいURLを指定

## 従来の方法との比較

### 従来（ファイルベース）

```bash
# 録音
say -o test_audio3.aiff "とても楽しかったです"
afconvert test_audio2.aiff test_audio2.wav -d LEI16

# 送信
curl -X POST "http://localhost:8000/voice-chat/session/SESSION_ID/continue" \
  -F "audio=@test_audio2.wav" \
  -F "language_code=ja-JP" \
  --output response3.mp3

# 再生
afplay response3.mp3
```

### 新しい方法（インタラクティブ + Push-to-Talk）

```bash
python apps/server/interactive_voice_chat.py
# スペースキーを押して話すだけ！
```

## 技術詳細

- **音声録音**: PyAudio を使用してマイクから直接録音
- **Push-to-Talk**: pynput を使用してスペースキーの押下を検知
- **音声形式**: 16kHz, 16-bit, モノラル WAV
- **セッション管理**: 自動的にセッションIDを保持し、会話履歴を維持
- **音声再生**: macOSの`afplay`コマンドを使用（他のOSでは要変更）

## 主な機能

### Push-to-Talk方式
- スペースキーを押している間だけ録音
- 話し終わったらスペースキーを離すだけで自動送信
- 録音時間の制限なし（話したい分だけ話せる）

### AIからの会話開始
- プログラム起動時にAIが最初に挨拶
- 自然な会話の流れを実現

### セッション管理
- 会話履歴を自動保存
- 文脈を理解した対話が可能
