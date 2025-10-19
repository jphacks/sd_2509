# AI Diary Call

このリポジトリは、音声日記アプリ「AI Diary Call」のモノレポ構成を管理します。

- `apps/mobile`: Expo（React Native）で実装するモバイルアプリ。UI、録音、通知、日記一覧などを担当します。
- `apps/server`: FastAPI と SQLite を利用したバックエンド。音声データの受信、要約、保存、API 提供を担当します。
- `packages/shared_schemas`: OpenAPI 仕様から TypeScript クライアントを自動生成するための共有スキーマ群（任意で利用）。
- `turbo.json`: Turborepo 設定ファイル（任意）。

## チャットお試し

1. `apps/server/.env`（または任意の `.env`）に `OPENROUTER_API_KEY=...` を設定し、必要であれば `OPENROUTER_MODEL` や `OPENROUTER_SYSTEM_PROMPT_FILE` も記入する。
2. サーバーを開発モードで起動する。
   ```bash
   uv run python -m apps.server.dev_server
   ```
3. セッションを開始してログを初期化しつつ最初のメッセージを送る。
   ```bash
   curl -X POST http://127.0.0.1:8000/chat/session/start \
        -H "Content-Type: application/json" \
        -d '{"session_id":"demo"}'
   ```
4. 継続メッセージを送ると、保存された履歴を読み込みながら応答が返る。
   ```bash
   curl -X POST http://127.0.0.1:8000/chat/session/demo/continue \
        -H "Content-Type: application/json" \
        -d '{"message":"今日の予定を教えて"}'
   ```
   セッションIDを省略して開始した場合は、レスポンスの `session_id` をそのまま継続リクエストに使用する。

## セッション要約（Markdown出力）

- セッションログは `db/<当日日付>/session_logs/<session_id>.json` に、自動生成されたMarkdownは `db/<当日日付>/session_summaries/<session_id>.md` に保存されます。必要に応じて環境変数 `CHAT_SESSION_DIR` / `CHAT_SUMMARY_DIR` で保存先を変更できます。
- 要約は OpenRouter の `CHAT_SUMMARY_MODEL`（デフォルト `openai/gpt-4o-mini`）を用いて毎回生成されるため、`OPENROUTER_API_KEY` の設定が必須です。必要に応じて `.env` に `CHAT_SUMMARY_MODEL` を追加してください。

要約を生成する:
```bash
curl http://127.0.0.1:8000/chat/session/demo/summary
```
レスポンスにはMarkdown本文と保存先パスが含まれ、生成されたファイルはフロントエンドやドキュメント向けにそのまま利用できます。
