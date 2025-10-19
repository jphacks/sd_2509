# AI Call Dev Server

開発時にモバイルアプリへ通知イベントを送るための簡易 FastAPI サーバーです。HTTP v1 の FCM 送信に対応しています。

## 起動方法

```bash
uvicorn apps.dev_server.main:app --reload
```

環境変数 `GOOGLE_SERVICE_ACCOUNT_JSON` に Firebase サービスアカウントの JSON（文字列もしくはファイルパス）を設定してください。

```bash
# 例: ファイルパスを指定する場合
export GOOGLE_SERVICE_ACCOUNT_JSON=./credentials/service-account.json
# 例: JSON 文字列を直接渡す場合
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account", ... }'
```

`google-auth` が必要です。未導入の場合は `uv add google-auth` などで追加してください。

## エンドポイント

- `GET /health` — ヘルスチェック
- `POST /notifications/publish` — 通知イベントの登録
- `GET /notifications/poll` — 新着通知イベントの取得（`after` クエリで最後に取得した ID を指定）
- `POST /push/register` — FCM デバイストークンを登録
- `GET /push/devices` — 登録済みデバイスの一覧取得
- `POST /push/send` — 登録済みデバイス（または指定したトークン）へ FCM HTTP v1 通知を送信  
  - オプションフィールド（任意）:
    - `android_vibrate_pattern`: バイブレーションパターン（ミリ秒の配列）
    - `android_sound`: サウンド名（`default` で標準の着信音）
    - `android_image_url`: 通知に表示する HTTPS 画像 URL（例: Gyazo の場合は `https://.../raw`）
    - `android_ttl_seconds`: 通知メッセージの有効期間（秒）
