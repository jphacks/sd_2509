# Dev Server Code Overview

## 概要
- ファイル: `apps/dev_server/main.py`
- 役割: 開発中に通知挙動を確認するための FastAPI ベースの簡易サーバー。
- 主な責務:
  - ローカル通知テスト用のイベント登録とポーリング。
  - FCM デバイストークンの登録と管理。
  - FCM HTTP v1 API を介したバックグラウンド通知送信。

## 使用ライブラリ
- `fastapi`: ルーティング・バリデーション (`FastAPI`, `HTTPException`, `Query`, `status`)。
- `pydantic`: 入出力スキーマ定義 (`BaseModel`, `Field`)。
- `httpx`: FCM HTTP v1 API への非同期 HTTP POST。
- `google-auth`: サービスアカウント資格情報を元にアクセストークンを取得。
- `collections.deque`: メモリで最大 100 件まで通知イベント履歴を保持。
- `datetime`: UTC タイムスタンプ発行 (登録・更新時刻)。

## メモリ内ストア
- `_EVENT_HISTORY`: `NotificationEvent` の `deque`。最新 100 件まで保持。
- `_LAST_EVENT_ID`: 通知イベントの連番を管理。
- `REGISTERED_TOKENS`: FCM デバイストークンをキーに `RegisteredDevice` 情報を保持。
- `_CACHED_CREDENTIALS`: サービスアカウント資格情報をキャッシュ。
- `_FIREBASE_PROJECT_ID`: サービスアカウント JSON から取得した Firebase プロジェクト ID。

## データモデル
| モデル | 用途 |
| --- | --- |
| `NotificationPublishRequest` | `/notifications/publish` の入力。タイトルと本文を 280 文字以内で受け取る。 |
| `NotificationEvent` | 登録された通知イベントを表現。ID/タイトル/本文/作成日時を保持。 |
| `NotificationPollResponse` | ポーリング応答。新着イベント配列と `latest_id` を返す。 |
| `RegisterDeviceRequest` | FCM デバイストークンと任意の端末情報を登録するリクエスト。 |
| `RegisteredDevice` | 登録済み端末。トークン・プラットフォーム・アプリバージョン・登録/最終更新時刻を保持。 |
| `PushSendRequest` | FCM 送信に必要なタイトル・本文・任意のデータ・送信トークンリスト。追加で Android 系オプション（タイムアウト、バイブパターン、サウンド、画像 URL）を指定可能。 |
| `PushSendResponse` | FCM HTTP v1 の応答（各トークンごとのレスポンス）と送信対象トークン。 |

## エンドポイント
### ヘルスチェック
- `GET /health`
- 返却: `{"status": "ok"}`

### ローカル通知ポーリング
- `POST /notifications/publish`
  - 入力: `NotificationPublishRequest`
  - 処理: ID を採番し、UTC 時刻を付与した `NotificationEvent` を `_EVENT_HISTORY` に追加。
  - 返却: 登録された `NotificationEvent` (201 Created)
- `GET /notifications/poll`
  - クエリ: `after`（既知の最新 ID。0 で全件）
  - 返却: `NotificationPollResponse`
    - `events`: `after` より大きい ID のイベント一覧
    - `latest_id`: 履歴最後の ID（イベントが無い場合は `after` か `None`）

### FCM デバイストークン管理
- `_normalize_token(token)`
  - 文字列が空でないか確認。空文字は 400 エラー。
- `POST /push/register`
  - 入力: `RegisterDeviceRequest`（FCM デバイストークン必須）
  - 処理: 既存登録があれば `registered_at` を維持しつつ `last_seen_at` を更新。プラットフォームやバージョン情報は最新の値で上書き。
  - 返却: `RegisteredDevice`
- `GET /push/devices`
  - 返却: 登録済み `RegisteredDevice` の一覧

### FCM HTTP v1 送信
- `_load_service_account()`
  - 環境変数 `GOOGLE_SERVICE_ACCOUNT_JSON` から JSON またはファイルパスを読み込み、`google.oauth2.service_account.Credentials` を生成する。
- `_send_fcm(tokens, payload)`
  - `Credentials` からアクセストークンを取得し、`https://fcm.googleapis.com/v1/projects/<project-id>/messages:send` に POST。
  - トークンごとにリクエストを送り、レスポンス JSON を配列に蓄積。`PushSendRequest` の Android オプション（`timeout_after`、サウンド、バイブパターン、画像）を `android.notification` に変換。
- `POST /push/send`
  - 入力: `PushSendRequest`（`tokens` 未指定の場合は登録済みトークン全件）
  - `tokens` 空の場合は 400 エラー。
  - 返却: `PushSendResponse`（FCM のレスポンス一覧と送信対象トークン）

## 実行例
```bash
# サーバー起動（他端末からもアクセス可能にする）
uv run uvicorn apps.dev_server.main:app --reload --host 0.0.0.0 --port 8000

# 通知イベント登録
curl -X POST http://localhost:8000/notifications/publish \
  -H "Content-Type: application/json" \
  -d '{"title":"テスト通知","body":"イベント登録"}'

# FCM トークン登録
curl -X POST http://localhost:8000/push/register \
  -H "Content-Type: application/json" \
  -d '{"token":"fcm-device-token","platform":"android"}'

# FCM 送信
curl -X POST http://localhost:8000/push/send \
  -H "Content-Type: application/json" \
  -d '{
        "title":"バックグラウンド通知",
        "body":"FCM テスト",
        "android_vibrate_pattern":[0,800,400,800,400,800],
        "android_ttl_seconds":60,
        "android_image_url":"https://example.com/sample.png",
        "data":{"origin":"dev_server"}
      }'
```

## 注意点
- すべてメモリ保持のため、サーバーを再起動するとイベント履歴およびトークン登録情報は消失する。
- FCM トークンは Dev Client / EAS Build など実機環境でのみ取得可能。Expo Go では取得不可。
- FCM HTTP v1 にアクセスするため、事前に Firebase サービスアカウントと `google-auth` を準備しておく必要がある。
