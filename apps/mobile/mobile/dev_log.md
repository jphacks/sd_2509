# 開発ログ

## 2025-10-18

### 通知ハンドラの警告解消と基本動作確認
- 依頼: 「今のコードの警告部分を無くしてもらえますか？」（`app/(tabs)/index.tsx` の `alert` や非推奨プロパティの警告解消）。
- 対応: `Alert.alert` へ置き換え、`Notifications.setNotificationHandler` を SDK 54 仕様に合わせて更新、`simulateCall` を fire-and-forget 化。
- コマンド: `npm run lint` で ESLint を通過確認。

### 簡易通知サーバーの追加と実機連携準備
- 要望: 「サーバーでアクションが起きたら通知したい」「既存 server ディレクトリは使用せず、新たに dev_server を作りたい」。
- 対応: `apps/dev_server/main.py` で FastAPI サーバーを作成し、`/notifications/publish`・`/notifications/poll` を実装。`uv` CLI で `uv run uvicorn apps.dev_server.main:app --reload` を起動確認。
- 実機連携に向け、ユーザーからの質問:
  - 「UV でやってもいいですか？」→ `uv add fastapi uvicorn[standard]` を案内。
  - 「ローカル IP はどう調べるか？」→ macOS での確認方法を共有 (Wi-Fi 詳細、`ipconfig getifaddr en0` 等)。
  - `curl -X POST http://10.34.148.221:8000/notifications/publish` で PC から通知登録を確認。
- Expo 側の設定:
  - `EXPO_PUBLIC_API_BASE_URL` のエクスポート方法の質問に回答（`EXPO_PUBLIC_API_BASE_URL=http://... npx expo start --dev-client --tunnel` の形式）。
  - 実機テストに必要な `--host 0.0.0.0` の付け忘れを指摘し、`uv run uvicorn apps.dev_server.main:app --reload --host 0.0.0.0` で外部接続を許可。

### モバイル側のデバッグログ追加と通知動作検証
- ユーザー要望: 「index.tsx にデバッグを入れて欲しい」。
- 対応: API ベース URL・ポーリング結果・イベント内容などを `console.log` で出力。通知受信を実機で確認済み。
- Q: 「アプリを開いていない状態だと通知は無理？」→ 現状のポーリング方式では不可、プッシュ通知へ移行する必要を説明。
- Q: 「通知をもっと大きく出せないか？」→ iOS/Android での調整ポイント（importance や interruptionLevel）を案内。

### Expo Push → FCM HTTP v1 への移行準備
- Firebase 側で FCM Legacy API が無効である問題が判明。HTTP v1 へ移行する方針に決定。
- サーバー側 (`apps/dev_server/main.py`) を Expo Push 依存から切り離し、以下を実装。
  - `google-auth` を利用してサービスアカウント JSON からアクセストークンを取得。
  - `_send_fcm` 関数で `https://fcm.googleapis.com/v1/projects/<project-id>/messages:send` へ通知を送信。
  - `GOOGLE_SERVICE_ACCOUNT_JSON` 環境変数（JSON 文字列またはファイルパス）から資格情報を読み込む仕組みを追加。
  - レスポンスを `responses` として返し、登録トークン一覧には FCM デバイストークンを保持。
- モバイル側 (`app/(tabs)/index.tsx`) を FCM トークン取得フローへ更新。
  - `Notifications.getDevicePushTokenAsync()` で FCM デバイストークンを取得し、`/push/register` へ登録。
  - Android 通知チャンネルの設定は維持しつつ、Expo Push Token 取得ロジックを削除。
- ドキュメント整備:
  - `apps/dev_server/README.md` に環境変数設定・`google-auth` 依存・エンドポイントの説明を追記。
  - `apps/dev_server/server_code.md` を FCM HTTP v1 ベースの内容に書き換え。
- ユーザー質問:
  - 「FCM HTTP v1 のコードは書けるか？」→ 環境変数で JSON を渡す方法を提案。
  - 「自分の端末以外でも動作するか？」→ FCM トークンが取得できる端末なら問題ない旨を共有。

### その他メモ
- 通知処理内で `console.log` を多用し、Expo DevTools で状態を追跡可能にした。
- `.dev_log.md` の作成依頼を受け、経緯と手順を記録（本ファイル）。
- ネットワーク制限により `npm install` が失敗したケースがあり、依存追加はローカル環境で実行する前提とした。
