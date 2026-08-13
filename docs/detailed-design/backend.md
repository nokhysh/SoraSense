# SoraSense 詳細設計書 — バックエンド

## 1. 文書情報

| 項目 | 内容 |
|---|---|
| 文書版数 | 0.1.0 |
| 入力文書 | 要件定義書 v0.0.0、基本設計書 v0.2.0 |
| 対象 | FastAPI、サービス層、リポジトリ層、異常判定 |

### 1.1 変更履歴

| 版数 | 日付 | 変更内容 |
|---|---|---|
| 0.1.0 | 2026年8月14日 | APIドキュメント機能の公開方針を環境別設定へ変更 |
| 0.0.0 | 2026年8月13日 | 版数管理開始時点のバックエンド詳細設計を登録 |

## 2. パッケージ構成

```text
app/
├── main.py
├── config.py
├── dependencies.py
├── api/
│   ├── measurement_router.py
│   └── health_router.py
├── web/
│   ├── auth_router.py
│   └── agent_router.py
├── schemas/
│   ├── measurement.py
│   └── errors.py
├── services/
│   ├── measurement_service.py
│   ├── alert_service.py
│   ├── query_service.py
│   └── health_service.py
├── repositories/
│   ├── measurement_repository.py
│   ├── alert_repository.py
│   └── ai_request_repository.py
├── agent/
│   ├── runner.py
│   ├── instructions.py
│   └── tools.py
├── security/
│   ├── device_auth.py
│   ├── web_auth.py
│   └── csrf.py
└── observability/
    ├── logging.py
    └── middleware.py
```

RouterはHTTP変換、Serviceは業務処理、RepositoryはSQLAlchemyによるDB操作だけを担当する。RepositoryをRouterから直接呼ばない。

## 3. アプリケーション初期化

`create_app(settings)`でFastAPIを生成する。Swagger UIおよびReDocは本番環境では無効化する。開発環境ではAPIの動作確認に利用できるよう有効化してよい。OpenAPI定義は開発・テストで利用し、本番環境では外部公開しない。APIの保護は、これらの無効化ではなく、認証、認可およびネットワークのアクセス制御によって行う。リクエストID、例外変換、構造化ログのMiddlewareを登録する。起動時に必須設定、閾値設定、DB接続を検証する。設定不正ではプロセスを起動失敗とし、値そのものをログへ出さない。

## 4. 測定データAPI

### 4.1 接続と認証

| 項目 | 仕様 |
|---|---|
| Method / Path | `POST /api/v1/devices/{device_id}/measurements` |
| Content-Type | `application/json`のみ |
| 認証 | `Authorization: Bearer {device_api_key}` |
| リクエストID | 有効な`X-Request-ID`を採用し、未指定・不正時はサーバーがUUID v4を発行 |

`device_id`はURL、本文、`DEVICE_ID`の3値を定時間比較可能な処理で照合する。APIキーはArgon2idハッシュ`DEVICE_API_KEY_HASH`と照合する。認証失敗時は、IDとキーのどちらが不正かを応答で区別しない。

### 4.2 要求

```json
{
  "schema_version": 1,
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_id": "living-room-01",
  "measured_at": "2026-08-11T03:00:00Z",
  "temperature_c": 26.4,
  "humidity_percent": 58.2
}
```

| フィールド | 型 | 制約 |
|---|---|---|
| `schema_version` | integer | 必須、値は`1` |
| `message_id` | UUID | 必須、v4 |
| `device_id` | string | 必須、`^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$` |
| `measured_at` | datetime | 必須、UTC、現在時刻より5分超の未来は拒否 |
| `temperature_c` | decimal | 必須、有限値、-40.0～85.0 |
| `humidity_percent` | decimal | 必須、有限値、0.0～100.0 |

未知フィールドは後方互換性のため無視する。JSON本文上限は16 KiBとする。欠損、型、形式、範囲違反は保存しない。

### 4.3 応答

| HTTP | `code` | 条件 |
|---:|---|---|
| 201 | `MEASUREMENT_CREATED` | 新規保存と異常判定が完了 |
| 200 | `MEASUREMENT_ALREADY_ACCEPTED` | 同一デバイス・同一`message_id`を保存済み |
| 400 | `VALIDATION_ERROR` | JSON、形式、範囲、時刻が不正 |
| 401 | `UNAUTHENTICATED` | 認証情報なし・不一致 |
| 403 | `DEVICE_MISMATCH` | 認証済みデバイスとURLまたは本文が不一致 |
| 413 | `PAYLOAD_TOO_LARGE` | 本文上限超過 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Content-Type不正 |
| 429 | `RATE_LIMITED` | 送信レート上限超過 |
| 503 | `DATABASE_UNAVAILABLE` | DB接続・トランザクションが利用不能 |
| 500 | `INTERNAL_ERROR` | 想定外エラー |

JSON応答は`code`、`message`、`request_id`を持つ。成功応答はDBコミット後に返す。APIはデバイス単位で1分あたり30件を上限とし、429には`Retry-After`を付与する。

## 5. 測定登録ユースケース

`MeasurementService.accept(command)`は次の順に処理する。

1. 認証済みデバイスと入力を照合する。
2. トランザクションを開始する。
3. `app.devices`の対象行を`SELECT ... FOR UPDATE`でロックする。
4. `device_id`と`message_id`で既存測定を確認する。
5. 既存なら変更せず重複結果を返す。
6. 測定値を登録する。
7. 測定日時がデバイスの最新判定済み時刻以前の場合は、測定値だけを保存してアラートを更新しない。
8. 測定日時が最新判定済み時刻より新しい場合は、同一トランザクションで温度・湿度の異常状態を評価・更新し、最新判定済み時刻を測定日時へ更新する。
9. コミットし、登録結果を返す。

デバイス行のロックにより、同一デバイスの測定登録とアラート状態更新を直列化する。これにより、OPENアラートがまだ存在しない場合の同時作成競合を防ぐ。遅延到着した測定も履歴・集計のために保存するが、`measured_at`がデバイスの最新判定済み時刻以前であれば、現在のアラート状態には反映しない。

競合する重複送信は、測定テーブルのUNIQUE制約で最終的に排除する。制約違反は制約名で分類し、`uq_measurements_device_message`違反の場合は現在のトランザクションをロールバックする。その後、別の参照処理で同一`device_id`・`message_id`の測定が登録済みであることを確認し、存在する場合だけ冪等な重複成功`MEASUREMENT_ALREADY_ACCEPTED`として扱う。登録済み測定を確認できない場合は内部エラーとする。`uq_alerts_open_condition`違反やその他の制約違反は測定重複として扱わず、トランザクション全体をロールバックして内部エラーとする。

## 6. 異常判定

### 6.1 設定

```yaml
thresholds:
  temperature:
    lower: 10.0
    upper: 35.0
    hysteresis: 0.5
  humidity:
    lower: 30.0
    upper: 70.0
    hysteresis: 2.0
```

起動時に型、`lower < upper`、測定可能範囲内、`0 < hysteresis < (upper-lower)/2`を検証する。変更は設定ファイル更新とFastAPI再起動で反映し、過去データを再判定しない。

### 6.2 判定規則

| 現在状態 | 入力条件 | 処理 |
|---|---|---|
| OPENなし | 値 `< lower` | `LOW`アラート開始 |
| OPENなし | 値 `> upper` | `HIGH`アラート開始 |
| `LOW` OPEN | 値 `< lower + hysteresis` | `last_detected_at`更新 |
| `LOW` OPEN | 値 `>= lower + hysteresis` | RESOLVEDへ更新 |
| `HIGH` OPEN | 値 `> upper - hysteresis` | `last_detected_at`更新 |
| `HIGH` OPEN | 値 `<= upper - hysteresis` | RESOLVEDへ更新 |

境界値は正常とする。異常開始時の閾値、測定値、ヒステリシスをアラートへ保存する。同一デバイス・項目・方向のOPENは部分UNIQUE索引でも一意にする。

OPENアラートが存在する場合は、最初に現在の異常状態が復帰条件を満たすか判定する。復帰条件を満たした場合は現在のアラートをRESOLVEDへ更新し、同じ測定値をOPENアラートなしの状態として再評価する。反対方向の異常条件を満たす場合は、同じ測定処理内で新しいアラートをOPENにする。これにより、`LOW`から`HIGH`または`HIGH`から`LOW`へ直接変化した場合も、反対方向の異常開始を次回測定まで遅延させない。

## 7. 照会サービス

`QueryService`は最新値、期間統計、時系列集計、期間比較、アラート履歴を型付きDTOで返す。生SQL、任意テーブル名、任意URLを入力として受け付けない。期間は`from < to`で検証し、DBでは半開区間`[from, to)`を使用する。AI Toolからの利用条件は`ai-agent.md`、Grafana用の参照経路は`database.md`を正本とする。

## 8. ヘルスチェック

| Method / Path | 確認内容 | 成功 | 失敗 |
|---|---|---:|---:|
| `GET /health/live` | FastAPIプロセス | 200 | 接続不能 |
| `GET /health/ready` | 必須設定、DBへ`SELECT 1` | 200 | 503 |

OpenAI APIは収集・閲覧の準備完了条件に含めない。内部ネットワークからのみ到達可能にする。

## 9. 例外処理

ドメイン例外を`ValidationError`、`AuthenticationError`、`RateLimitError`、`DependencyUnavailableError`へ分類し、共通例外HandlerでHTTPへ変換する。DB例外はRepository境界で分類し、OpenAI例外はAgent境界で処理する。全例外にリクエストIDを付与する。
