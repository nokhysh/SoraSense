# SoraSense 詳細設計書 — インフラ・運用

## 2. コンテナ構成

| Service | 公開 | 永続化 | 依存 |
|---|---|---|---|
| `app` | ホストのLANアドレス:8000 | なし | `postgres` |
| `postgres` | 内部5432のみ | PostgreSQL data volume | なし |
| `grafana` | ホストのローカルアドレス:3000 | 原則不要、必要時のみvolume | `postgres` |

PostgreSQLをホストへ公開しない。`app`と`grafana`は別DBユーザーを使用する。コンテナは可能な限り非root、読み取り専用ルートファイルシステム、権限削減を適用する。

## 3. ローカルネットワークと外部通信

`frontend`ネットワークにはappとGrafanaを、`backend`ネットワークにはapp、Grafana、PostgreSQLを接続する。PostgreSQLは`backend`だけに接続する。appの8000番ポートはM5StickC Plus2から到達可能なホストの特定LANアドレスへバインドし、`0.0.0.0`への無条件公開を避ける。Grafanaは利用するホストのローカルアドレスへバインドする。

ホストのファイアウォールでappの8000番ポートへの接続元を管理対象LANに制限し、ルーターでインターネットからのポート転送を設定しない。ローカルのデバイス、AI質問画面およびGrafanaはHTTPを使用する。appからGemini Developer APIへの外向き通信だけはHTTPSを使用し、証明書検証はGoogle Gen AI SDKの既定動作を維持する。

## 4. 設定とSecret

| 分類 | 主な設定 |
|---|---|
| App | `DATABASE_URL`、`DEVICE_ID`、`APP_TIMEZONE`、`GEMINI_MODEL` |
| Secret | `DEVICE_API_KEY_HASH`、`WEB_PASSWORD_HASH`、`GEMINI_API_KEY`、DBパスワード |
| Grafana | 管理者認証、`grafana_reader`接続情報、公開URL |
| Device | ローカルHTTP API URL、Wi-Fi、デバイスAPIキー |

Secret実値をGit管理対象のファイル、Composeファイル、Git履歴およびログへ登録しない。初期リリースではGit管理外の`.env`を使用し、Argon2idハッシュは`$`をComposeに展開させないよう値全体を一重引用符で囲む。Docker Secretまたは同等の専用Secret機構は将来対象とする。起動時には存在と形式だけを検証し、値は出力しない。Secret更新手順は、新値発行、対象サービス更新、動作確認、旧値失効の順とする。

Geminiモデルを変更する場合は、`.env`の`GEMINI_MODEL`だけを書き換え、`docker compose up -d --force-recreate app`でappコンテナを再作成する。APIキーやComposeファイルの変更は不要とする。反映後は`docker compose exec -T app python -c "from app.config import Settings; print(Settings().gemini_model)"`でモデル名だけを確認し、質問を1件実行して`ai_requests.model`と成功状態を確認する。モデル変更を過去の監査レコードへ遡及適用しない。

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
| `validation_rule` | Agent回答検証に失敗した固定ルール。質問・回答・測定値は含めない |

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
| `dependency.unavailable` | DBまたはGemini利用不能 |
| `health.ready.failed` | Ready確認失敗 |

## 7. 監視

- FastAPI、PostgreSQL、Grafanaのコンテナ状態を確認する。
- `/health/live`と`/health/ready`を60秒間隔で確認する。
- 受信成功件数、拒否件数、最終受信時刻、デバイス状態を確認する。
- Agent成功・失敗、トークン利用量、処理時間を確認する。
- PostgreSQL接続数を確認する。
- Ready失敗と最終受信10分超を運用確認対象とする。

初期リリースでは外部通知連携を要件に含めず、ログと管理者による定期確認を基本とする。

## 8. 初期リリースの復旧範囲

PostgreSQLの永続volumeを削除せず、PostgreSQL、FastAPI、Grafanaの順に再起動する。再起動後は`GET /health/ready`、主要VIEW、Grafana表示および新規測定受付を確認する。

日次バックアップ、暗号化、世代管理、隔離環境への復元、RPO・RTO保証および自動ロールバックは将来対象とし、初期リリースへ含めない。Migrationのdowngradeがデータ損失を伴う場合は実行しない。
