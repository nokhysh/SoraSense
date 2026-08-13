# SoraSense 詳細設計書 — インフラ・運用

## 1. 文書情報

| 項目 | 内容 |
|---|---|
| 文書版数 | 0.0.0 |
| 対象 | Docker Compose、HTTPS、設定・Secret、ログ、監視、バックアップ・復旧 |

## 2. コンテナ構成

| Service | 公開 | 永続化 | 依存 |
|---|---|---|---|
| `reverse-proxy` | 443 | 証明書または証明書参照設定 | `app`, `grafana` |
| `app` | 内部8000 | なし | `postgres` |
| `postgres` | 内部5432のみ | PostgreSQL data volume | なし |
| `grafana` | 内部3000 | 原則不要、必要時のみvolume | `postgres` |
| `backup` | 外部非公開 | 暗号化バックアップ保存先 | `postgres` |

PostgreSQLをホストへ公開しない。`app`と`grafana`は別DBユーザーを使用する。コンテナは可能な限り非root、読み取り専用ルートファイルシステム、権限削減を適用する。

## 3. ネットワークとHTTPS

`frontend`ネットワークにはProxy、app、Grafanaを、`backend`ネットワークにはapp、Grafana、PostgreSQLを接続する。PostgreSQLは`backend`だけに接続する。外部公開はProxyの443だけとし、80は443へのリダイレクトに限定する。

本番証明書は運用環境で信頼されたCAから取得し、自動更新する。TLS 1.2以上を許可する。Proxyは`X-Forwarded-Proto`等を上書きし、外部から受けた転送ヘッダーを信用しない。AI画面とGrafanaには別パスまたは別ホストを割り当てる。

## 4. 設定とSecret

| 分類 | 主な設定 |
|---|---|
| App | `DATABASE_URL`、`DEVICE_ID`、`APP_TIMEZONE`、`OPENAI_MODEL` |
| Secret | `DEVICE_API_KEY_HASH`、`WEB_PASSWORD_HASH`、`SESSION_SECRET`、`OPENAI_API_KEY`、DBパスワード |
| Grafana | 管理者認証、`grafana_reader`接続情報、公開URL |
| Device | API URL、Wi-Fi、デバイスAPIキー、CA証明書 |

Secret実値を`.env`、Composeファイル、Git履歴、ログへ登録しない。本番ではDocker Secretまたは同等のSecret機構を使用する。起動時には存在と形式だけを検証し、値は出力しない。Secret更新手順は、新値発行、対象サービス更新、動作確認、旧値失効の順とする。

## 5. 構造化ログ

標準出力へ1イベント1 JSONで出力する。

| フィールド | 内容 |
|---|---|
| `timestamp` | UTC ISO 8601 |
| `level` | DEBUG / INFO / WARNING / ERROR |
| `service` | サービス名 |
| `event` | 安定したイベント名 |
| `request_id` | HTTP要求の相関ID |
| `message_id` | 測定送信ID。必要なイベントのみ |
| `device_id` | 対象デバイス。必要なイベントのみ |
| `result` | success / rejected / failure |
| `duration_ms` | 処理時間 |
| `error_code` | 分類済みエラーコード |

Authorization、Cookie、APIキー、パスワード、DB接続文字列、セッションID、質問・回答本文、測定値全件、スタックトレースの外部転送を禁止する。スタックトレースは想定外エラー時にローカル標準エラーへ出せるが、Secretマスク処理を通す。

## 6. 主要ログイベント

| イベント | 発生条件 |
|---|---|
| `measurement.accepted` | 新規測定コミット完了 |
| `measurement.duplicate` | 重複送信を正常受理 |
| `measurement.rejected` | 入力・認証拒否 |
| `alert.opened` / `alert.resolved` | アラート状態変更 |
| `agent.completed` / `agent.failed` | AI質問終了 |
| `authentication.succeeded` / `authentication.failed` | Web認証結果 |
| `dependency.unavailable` | DBまたはOpenAI利用不能 |
| `health.ready.failed` | Ready確認失敗 |
| `backup.completed` / `backup.failed` | バックアップ結果 |

## 7. 監視

- Proxy、FastAPI、PostgreSQL、Grafanaのコンテナ状態を確認する。
- `/health/live`と`/health/ready`を60秒間隔で確認する。
- 受信成功件数、拒否件数、最終受信時刻、デバイス状態を確認する。
- Agent成功・失敗、トークン利用量、処理時間を確認する。
- ディスク空き容量、PostgreSQL接続数、バックアップ成否を確認する。
- Ready失敗、最終受信10分超、バックアップ失敗、ディスク残量20%未満を運用確認対象とする。

初期リリースでは外部通知連携を要件に含めず、ログと管理者による定期確認を基本とする。

## 8. バックアップ

`pg_dump`のカスタム形式で日次取得し、取得後に復元可能性を検査してから、DB本体と異なる保存先へ暗号化して保管する。保持期間は日次7世代、週次4世代を初期値とする。バックアップ暗号鍵はバックアップと別に管理する。成功・容量・所要時間・チェックサムを記録する。

## 9. 復旧手順

1. 障害範囲と復旧対象時点を決定する。
2. 新しいPostgreSQL領域を用意する。
3. バックアップのチェックサムと復号を確認する。
4. Migration互換バージョンのDBへ`pg_restore`する。
5. テーブル件数、最新測定日時、VIEW、DB権限を確認する。
6. FastAPIを起動しReadyを確認する。
7. Grafanaを起動し主要パネルを確認する。
8. デバイス送信を再開し、新規測定と重複排除を確認する。

月次で隔離環境へ復元し、RPO 24時間、RTO 4時間以内を記録する。

## 10. デプロイとロールバック

リリース前に設定検証、テスト、DBバックアップを実行する。DB Migration、app、Grafana、Proxy設定の順に反映する。失敗時はアプリイメージを直前版へ戻す。DB downgradeがデータ損失を伴う場合は実行せず、バックアップから別DBへ復元して切り替える。
