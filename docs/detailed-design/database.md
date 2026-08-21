# SoraSense 詳細設計書 — データベース

## 1. 文書情報

| 項目 | 内容 |
|---|---|
| 文書版数 | 0.1.0 |
| 入力文書 | 要件定義書 v0.1.0、基本設計書 v0.3.0 |
| 対象 | PostgreSQL 16、SQLAlchemy、Alembic、Grafana参照用VIEW |

### 1.1 変更履歴

| 版数 | 日付 | 変更内容 |
|---|---|---|
| 0.1.0 | 2026年8月21日 | 表示・集計タイムゾーンをAsia/Tokyoに固定 |
| 0.0.0 | 2026年8月13日 | 版数管理開始時点のデータベース詳細設計を登録 |

## 2. スキーマと権限

| スキーマ | 所有者 | 用途 |
|---|---|---|
| `app` | `sorasense_migrator` | 基底テーブル、Sequence、索引 |
| `reporting` | `sorasense_migrator` | Grafana参照用VIEW |

初回構築専用の管理者`sorasense_owner`がDBとロールの作成および所有関係の設定を行い、通常運用では使用しない。Migrationはスキーマ所有者`sorasense_migrator`で実行する。実行時ユーザー`sorasense_app`はスキーマを所有せず、`app`のUSAGE、テーブルのSELECT・INSERT・UPDATE、必要なSequenceのUSAGEだけを持つ。DELETE、TRUNCATE、CREATE、ALTER、DROPは与えない。`grafana_reader`には`reporting`のUSAGEとVIEWのSELECTだけを与え、基底テーブル、関数、他スキーマへの権限を与えない。

## 3. `app.devices`

| カラム | 型 | NULL | 制約・初期値 |
|---|---|:---:|---|
| `device_id` | varchar(64) | × | PK、ID形式CHECK |
| `registered_at` | timestamptz | × | `CURRENT_TIMESTAMP` |
| `last_alert_evaluated_at` | timestamptz | ○ | 最新のアラート判定済み測定日時 |

初期デバイスはMigration後の初期化処理で`DEVICE_ID`から冪等に登録する。PostgreSQLのVIEWはFastAPIコンテナの環境変数を直接参照しない。登録済みの本テーブルを状態判定と同一デバイス更新のロック対象にする。`last_alert_evaluated_at`は初回判定前をNULLとし、アラート判定を実行した測定の`measured_at`で更新する。受信した測定の`measured_at`がこの値以前の場合は、測定データだけを保存してアラート状態を更新しない。

## 4. `app.measurements`

| カラム | 型 | NULL | 制約・初期値 |
|---|---|:---:|---|
| `id` | bigint | × | identity、PK |
| `device_id` | varchar(64) | × | ID形式CHECK |
| `message_id` | uuid | × | UUID v4形式はアプリで検証 |
| `measured_at` | timestamptz | × | なし |
| `temperature_c` | numeric(5,2) | × | CHECK -40.00～85.00 |
| `humidity_percent` | numeric(5,2) | × | CHECK 0.00～100.00 |
| `received_at` | timestamptz | × | `CURRENT_TIMESTAMP` |

`device_id`は`app.devices(device_id)`への外部キーとする。索引は制約名`uq_measurements_device_message`のUNIQUE (`device_id`, `message_id`)と、履歴検索用 (`device_id`, `measured_at` DESC, `id` DESC)を作成する。受信順確認用に (`device_id`, `received_at` DESC)を作成する。

## 5. `app.alerts`

| カラム | 型 | NULL | 制約 |
|---|---|:---:|---|
| `id` | bigint | × | identity、PK |
| `device_id` | varchar(64) | × | ID形式CHECK |
| `metric` | varchar(20) | × | `TEMPERATURE` / `HUMIDITY` |
| `direction` | varchar(10) | × | `LOW` / `HIGH` |
| `status` | varchar(10) | × | `OPEN` / `RESOLVED` |
| `threshold_value` | numeric(5,2) | × | 発生時閾値 |
| `trigger_value` | numeric(5,2) | × | 発生時測定値 |
| `hysteresis` | numeric(5,2) | × | CHECK `> 0` |
| `started_at` | timestamptz | × | 異常測定日時 |
| `last_detected_at` | timestamptz | × | 最終異常測定日時 |
| `resolved_at` | timestamptz | ○ | RESOLVED時必須 |

`device_id`は`app.devices(device_id)`への外部キーとする。`status`と`resolved_at`の整合CHECKを設ける。履歴検索用 (`device_id`, `started_at` DESC)、未解消検索用 (`device_id`, `status`, `started_at` DESC)を作成する。`status = 'OPEN'`を条件として (`device_id`, `metric`, `direction`)の部分UNIQUE索引`uq_alerts_open_condition`を作る。

## 6. `app.ai_requests`

| カラム | 型 | NULL | 制約・説明 |
|---|---|:---:|---|
| `id` | uuid | × | PK |
| `question` | text | × | 1～2000文字をアプリで検証 |
| `answer` | text | ○ | 成功時の回答 |
| `status` | varchar(20) | × | `RUNNING` / `SUCCEEDED` / `FAILED` / `REJECTED` |
| `model` | varchar(100) | ○ | 利用モデル |
| `tool_calls` | integer | × | DEFAULT 0、0以上 |
| `input_tokens` | integer | ○ | 0以上 |
| `output_tokens` | integer | ○ | 0以上 |
| `error_code` | varchar(50) | ○ | 秘密情報・例外本文を含めない |
| `created_at` | timestamptz | × | `CURRENT_TIMESTAMP` |
| `completed_at` | timestamptz | ○ | 終了時刻 |

`status`と`answer`、`error_code`、`completed_at`の整合性は、次の規則に従うCHECK制約で保証する。

| `status` | `answer` | `error_code` | `completed_at` |
|---|---|---|---|
| `RUNNING` | NULL | NULL | NULL |
| `SUCCEEDED` | 必須 | NULL | 必須 |
| `FAILED` | NULL | 必須 | 必須 |
| `REJECTED` | NULL | 必須 | 必須 |

利用状況検索用 (`created_at` DESC)と (`status`, `created_at` DESC)を作成する。質問・回答本文は構造化ログへ複製しない。

## 7. reporting VIEW

| VIEW | 行の粒度 | 主な列 |
|---|---|---|
| `v_latest_measurements` | デバイス1行 | `device_id`、温度、湿度、`measured_at`、`received_at` |
| `v_device_statuses` | デバイス1行 | 最終受信、経過秒、`ONLINE` / `STALE` / `OFFLINE` |
| `v_measurement_series` | 測定1行 | デバイス、測定日時、温度、湿度 |
| `v_measurement_gaps` | 欠損区間1行 | デバイス、直前・直後の測定日時、間隔秒、推定欠損件数 |
| `v_alert_history` | アラート1行 | 項目、方向、状態、発生・解消日時、閾値、発生値 |
| `v_ai_usage_daily` | UTC日1行 | 質問数、成功数、失敗数、入出力トークン合計 |

最新値は`DISTINCT ON (device_id)`と`measured_at DESC, id DESC`で決定する。デバイス状態VIEWは`app.devices`を基点に測定の最終受信をLEFT JOINし、受信実績がなくてもデバイス1行を返す。最終受信から180秒以内をONLINE、600秒以内をSTALE、それ以外および受信実績なしをOFFLINEとする。

欠損区間VIEWは、デバイスごとに`LAG(measured_at)`で直前の測定日時を取得し、連続する測定日時の差が90秒を超える箇所を欠損候補として返す。推定欠損件数は`GREATEST(FLOOR(間隔秒 / 60) - 1, 1)`とする。遅延到着によって区間が埋まった場合はVIEWから自動的に消える。これは60秒周期に対するデータ欠損の識別であり、現在の通信途絶はデバイス状態VIEWで別に識別する。

## 8. 集計規則

- 対象期間は`measured_at >= from AND measured_at < to`とする。
- 最小・最大・平均・件数は温度と湿度を同じ対象行集合から算出する。
- 平均値はDB内では丸めず、外部DTOへの変換時に小数第2位へ丸める。
- 日・時単位のバケットは`Asia/Tokyo`へ変換して境界を求め、結果にはUTCの開始・終了と固定表示タイムゾーン`Asia/Tokyo`を含める。
- データがない期間は件数0、数値集計NULLとして返し、0とは区別する。

## 9. トランザクションとロック

測定登録、重複排除、アラート更新をREAD COMMITTEDの1トランザクションで実行する。処理の先頭で対象の`app.devices`行を`SELECT ... FOR UPDATE`し、同一デバイスの更新を直列化する。その後に`last_alert_evaluated_at`を確認し、判定対象となる測定だけについてOPENアラートを取得・更新する。アラート判定と`last_alert_evaluated_at`の更新は同じトランザクションで実行する。部分UNIQUE索引は不変条件を保証する防御層として残すが、通常処理で競合解決には使用しない。

`uq_measurements_device_message`違反が発生した場合は、そのトランザクションをロールバックする。ロールバック後の別の参照処理で同一`device_id`・`message_id`の測定を確認し、存在する場合だけ登録済みとして扱う。存在しない場合、および他の制約違反の場合は内部エラーとする。

AI照会とGrafana照会は参照トランザクションとし、測定登録を長時間ブロックしない。外部AI API呼出し中にDBトランザクションを保持しない。

## 10. Migration

- Alembic Revisionは1変更目的につき1つ作成する。
- Schema、テーブル、索引、VIEW、権限をMigrationで再現可能にする。
- VIEW変更は`DROP VIEW`と`CREATE VIEW`の依存順を明示し、downgradeも提供する。
- 大量データに対する索引追加は将来`CONCURRENTLY`を検討するが、初期構築時は通常作成とする。
- Migration適用前にバックアップを取得し、本番ではアプリ起動と自動的に同時実行しない。

## 11. 保持と拡張性

初期リリースでは自動削除しない。将来のセンサー追加に備え、既存カラムの意味を変更せず、追加Migrationまたは別の測定テーブルで拡張する。温度・湿度の既存VIEW契約を維持する。
