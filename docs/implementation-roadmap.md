# SoraSense 実装ロードマップ

## 1. 目的

本書は、SoraSenseの要件定義書、基本設計書および詳細設計書に基づき、初期リリースまでの実装順序と各段階の完了条件を示す。

実装は、依存関係と動作確認可能な単位を考慮し、次の順序で進める。

```text
開発基盤
  ↓
DB・Migration
  ↓
測定受付API ─→ 異常判定
  ↓              ↓
照会サービス → Grafana
  ↓
AI質問画面 → AI Agent
  ↓
センサーデバイス
  ↓
運用・受入試験
```

実装開始時点では、設計文書と最小限の`pyproject.toml`が存在し、アプリケーションコードは未作成である。

## 2. 実装方針

- 各フェーズを、利用者が1回で理解、実装、確認できる小さな学習ステップへ分割する。
- 原則として一度に1ステップだけ進め、完了条件を確認してから次へ進む。
- DB、API、UIなどを層ごとに一括実装せず、動作確認可能な縦方向の単位を優先する。
- 各実装には、詳細設計書`test-design.md`に定義されたテストを対応付ける。
- 設計と両立しない実装方式が必要になった場合は、実装だけで確定せず、基本設計書または要件定義書への影響を確認する。
- Secretの実値をソースコード、設定履歴、Composeファイルおよびログへ記録しない。

## 3. フェーズ1：開発基盤と最小アプリ

### 3.1 目的

以降の機能を安全に追加できる実行・検証基盤を作る。

### 3.2 主な作業

- `app/`および`tests/`の基本構成を作成する。
- `create_app(settings)`によるFastAPIのApplication Factoryを作成する。
- 設定クラスと環境別設定を作成する。
- `GET /health/live`を実装する。
- Ruff、mypy、pytestの実行環境を整備する。
- SQLAlchemy、Alembic、PostgreSQLドライバーなどの依存関係を追加し、バージョンを固定する。
- 開発用Docker Composeの最小構成を作成する。

### 3.3 完了条件

- FastAPIを起動できる。
- `/health/live`がHTTP 200を返す。
- Ruff、mypy、pytestが成功する。
- Secretの実値がリポジトリに含まれていない。

### 3.4 対応設計

- `docs/detailed-design/index.md`
- `docs/detailed-design/backend.md` 2～3章
- `docs/detailed-design/infrastructure-operations.md`

## 4. フェーズ2：データベースとMigration

### 4.1 目的

システム全体で使用するデータ構造、制約およびアクセス権限を確定する。

### 4.2 主な作業

- PostgreSQL 16のComposeサービスを作成する。
- SQLAlchemyモデルとAlembicの初期設定を作成する。
- `app.devices`を作成する。
- `app.measurements`を作成する。
- `app.alerts`を作成する。
- `app.ai_requests`を作成する。
- UNIQUE、CHECK、外部キーおよび部分索引を作成する。
- `DEVICE_ID`を使用した初期デバイスの冪等登録処理を作成する。
- DBロールと最小権限を設定する。
- Migrationのupgradeおよびdowngradeテストを作成する。

### 4.3 完了条件

- 空のPostgreSQLへMigrationを適用できる。
- 詳細設計で定義した制約と索引が存在する。
- 実行時ユーザー`sorasense_app`にDDLおよびDELETE権限がない。
- `IT-007`相当のMigrationテストが成功する。

### 4.4 対応設計

- `docs/detailed-design/database.md`
- `docs/detailed-design/test-design.md` IT-007

## 5. フェーズ3：測定受付の最小縦切り

### 5.1 目的

デバイス相当クライアントから受信した正常な測定値を、検証してDBへ保存できるようにする。

### 5.2 主な作業

- 測定データのRequest Schemaを作成する。
- URL、本文および設定値のデバイスIDを照合する。
- Argon2idによるAPIキー認証を実装する。
- Measurement Repositoryと`MeasurementService`を作成する。
- `POST /api/v1/devices/{device_id}/measurements`を実装する。
- リクエストIDを生成、検証および応答へ付与する。
- Content-Type、本文サイズ、形式および値範囲を検証する。
- DB障害を分類し、HTTP 503へ変換する。
- 測定受付に必要な構造化ログを作成する。

### 5.3 完了条件

- 正常データはHTTP 201で1件保存される。
- 不正データは測定値およびアラートとして保存されない。
- 認証失敗を安全な応答で拒否できる。
- 同じ`message_id`の再送はHTTP 200となり、DBには1件だけ保存される。
- `UT-API-001`および`IT-001`～`IT-004`が成功する。

### 5.4 対応要件・受入条件

- AC-001
- AC-005
- AC-009

## 6. フェーズ4：異常判定と同時実行制御

### 6.1 目的

測定値の保存とアラート状態の更新を、一貫したトランザクションとして処理する。

### 6.2 主な作業

- 閾値設定と起動時検証を実装する。
- ヒステリシスを含む異常判定を実装する。
- OPEN、継続、RESOLVEDおよび再発を処理する。
- LOWからHIGHなど、反対方向への直接遷移を処理する。
- `SELECT ... FOR UPDATE`で同一デバイスの更新を直列化する。
- 最新判定済み時刻以前に到着した測定値を履歴だけへ保存する。
- 同時送信とUNIQUE制約違反を正しく分類する。

### 6.3 完了条件

- 測定保存とアラート更新が同一トランザクションで行われる。
- 継続中の同一異常についてOPENアラートが重複しない。
- 正常範囲への復帰後に再発すると、新しいアラートが作成される。
- 遅延到着した測定値が現在のアラート状態を変更しない。
- `UT-ALT-001`、`IT-002A`、`IT-002B`、`IT-005`、`IT-011`および`IT-012`が成功する。

### 6.4 対応要件・受入条件

- AC-003
- AC-006

## 7. フェーズ5：照会サービスとGrafana

### 7.1 目的

保存済みデータを、型付けされた照会サービスと参照専用VIEWから安全に確認できるようにする。

### 7.2 主な作業

- `reporting`スキーマのVIEW一式を作成する。
- 最新値、デバイス状態、時系列、欠損区間、アラート履歴およびAI利用量を提供する。
- `QueryService`と型付きDTOを作成する。
- 統計、期間比較、半開区間およびタイムゾーン境界処理を実装する。
- `grafana_reader`へVIEWのSELECT権限だけを付与する。
- Grafanaのデータソース、フォルダーおよびダッシュボードをProvisioningする。
- GrafanaとAI質問画面の相互リンクを準備する。

### 7.3 完了条件

- 受信実績のない登録デバイスもOFFLINEとして表示される。
- 最新値、履歴、統計、欠損区間およびアラート履歴を確認できる。
- Grafanaから基底テーブルを参照または更新できない。
- 環境を再構築しても同じダッシュボードが復元される。
- `UT-STA-001`、`UT-GAP-001`、`UT-QRY-001`、`IT-006`、`IT-009`および`IT-010`が成功する。

### 7.4 対応要件・受入条件

- AC-002
- AC-006
- AC-007
- AC-010

## 8. フェーズ6：AI画面の認証・セッション

### 8.1 目的

AI Agentを接続する前に、Web画面の安全な認証、セッションおよび入力境界を完成させる。

### 8.2 主な作業

- Jinja2テンプレートとCSSを作成する。
- `/login`、`/agent`および`/logout`を実装する。
- Argon2idによる利用者認証を実装する。
- サーバー側セッションを実装する。
- CSRF対策を実装する。
- 質問送信用のワンタイムフォームトークンを実装する。
- ログイン試行のレート制限を実装する。
- Cookie属性とセキュリティヘッダーを設定する。
- HTMLエスケープと安全なエラー表示を実装する。

### 8.3 完了条件

- 未認証アクセス、失効セッションおよび不正なCSRFトークンを拒否する。
- ログイン成功時にセッションIDを再生成する。
- 質問または回答に含まれるHTMLを実行しない。
- `UT-SEC-001`、`ST-002`～`ST-004`および`ST-008`が成功する。

### 8.4 対応設計

- `docs/detailed-design/ui-grafana.md`
- `docs/detailed-design/test-design.md`

## 9. フェーズ7：AI Agentと根拠検証

### 9.1 目的

保存済みデータだけを参照し、回答の根拠をアプリケーション側で検証できるAI Agentを提供する。

### 9.2 主な作業

- OpenAI Agents SDKを導入する。
- 5種類の参照専用Toolを作成する。
- Agent Instructionsを作成する。
- Tool呼出し回数、ターン数および処理時間の上限を実装する。
- `ai_requests`へ結果と利用量を記録する。
- `AVAILABLE`、`NO_DATA`および`UNAVAILABLE`を区別する。
- Agent出力の構造検証を実装する。
- Tool実行履歴とAgent出力の根拠を照合する。
- 回答に含まれる数値の再現性を検証する。
- Fake Agentを使用した単体・結合テストを作成する。

### 9.3 実装分割

このフェーズは次の順に分割する。

1. 参照専用Tool
2. Agent実行と制限値
3. 構造検証
4. 意味検証と表示用根拠の再構築

### 9.4 完了条件

- AgentへDB接続、任意SQL、任意URLおよび更新操作を公開しない。
- Tool結果に存在しない数値を含む回答を表示しない。
- 入力検証で拒否した質問ではOpenAI APIを呼び出さない。
- OpenAI停止中も測定収集とGrafana閲覧が継続する。
- `UT-AI-001`～`UT-AI-003`、`IT-008`、`IT-013`および`E2E-003`が成功する。

### 9.5 対応要件・受入条件

- AC-004
- AC-005
- AC-009

## 10. フェーズ8：センサーデバイス

### 10.1 目的

M5StickC Plus2とENV IV Unitから、60秒周期で安全かつ継続的に測定値を送信する。

### 10.2 主な作業

- PlatformIOまたは採用するArduinoビルド環境を構成する。
- `SensorReader`を実装する。
- `ClockService`を実装する。
- `MeasurementFactory`を実装する。
- `ApiClient`を実装する。
- `RetryController`を実装する。
- `StatusDisplay`を実装する。
- `AppController`を実装する。
- NTP同期とUTC日時生成を実装する。
- CA証明書検証付きHTTPS通信を実装する。
- 非ブロッキングな計測と再送を実装する。
- 指数バックオフとジッターを実装する。
- 認証失敗時に自動送信を停止する。

### 10.3 完了条件

- 60秒周期の計測を継続する。
- 再送待機中も計測ループが停止しない。
- 同じ測定の再送で`message_id`が変わらない。
- 時刻を保証できない状態では送信しない。
- TLS検証を無効化する`setInsecure`を使用しない。
- `UT-DEV-001`、`UT-DEV-002`、`E2E-001`および`E2E-006`が成功する。

### 10.4 実装上の注意

実機依存部分へ進む前に、値検証、再送分類、バックオフおよび状態遷移などの純粋ロジックをホスト上でテストする。

## 11. フェーズ9：本番相当構成・運用・受入

### 11.1 目的

全要件を本番相当環境で確認し、障害発生後も復旧できる初期リリースを完成させる。

### 11.2 主な作業

- Reverse ProxyとHTTPSを構成する。
- frontendネットワークとbackendネットワークを分離する。
- コンテナを可能な限り非root化し、権限を削減する。
- Secret注入方式を構成する。
- `GET /health/ready`を実装する。
- バックアップ、暗号化およびチェックサム検査を実装する。
- 復元手順を整備して検証する。
- ログと監視項目を整備する。
- CIを構築する。
- 性能、障害、セキュリティおよびE2E試験を実施する。

### 11.3 完了条件

- Docker Composeから全サービスを再現できる。
- 30日分43,200件のデータで表示性能要件を満たす。
- 24時間相当1,440件のデータを欠損・重複なく処理する。
- OpenAI API、PostgreSQL、FastAPIおよびGrafanaの個別停止試験に合格する。
- バックアップを隔離したPostgreSQLへ復元できる。
- AC-001～AC-011をすべて満たす。

### 11.4 対応設計

- `docs/detailed-design/infrastructure-operations.md`
- `docs/detailed-design/test-design.md`

## 12. 推奨コミット単位

各フェーズを1コミットにまとめず、単独で検証可能な変更へ分割する。

例として、フェーズ3は次のコミット単位とする。

1. `feat: 測定データの入力スキーマを追加`
2. `feat: デバイスAPI認証を追加`
3. `feat: 測定データの保存処理を追加`
4. `feat: 測定受付APIを追加`
5. `test: 測定受付APIの結合テストを追加`

## 13. 最初の学習ステップ

### 13.1 目的

設定を外部から渡し、テスト可能なFastAPIアプリケーションを生成できるようにする。

### 13.2 学ぶ仕組み・概念

- Application Factory
- 設定とアプリケーション生成の分離
- FastAPIのルーティング
- TestClientを使用した最小限のHTTPテスト

### 13.3 変更対象

| ファイル | 変更理由 |
|---|---|
| `app/__init__.py` | `app`をPythonパッケージとして定義する |
| `app/main.py` | `create_app(settings)`とルーター登録を定義する |
| `app/config.py` | アプリケーション設定の型と初期値を定義する |
| `tests/test_health.py` | 最小アプリをHTTP経由で検証する |

### 13.4 利用者が実装する範囲

- `create_app(settings)`
- `GET /health/live`
- `/health/live`がHTTP 200を返すことを確認するテスト

### 13.5 完了条件と確認方法

- TestClientから`GET /health/live`へアクセスできる。
- HTTP 200と固定された正常応答が返る。
- pytest、Ruffおよびmypyが成功する。

このステップでは、DB接続、認証、構造化ログおよびReadyチェックを実装しない。最小アプリがテスト可能になった後、設定値の読込と検証へ進む。

## 14. 参照文書

- `docs/requirements.md`
- `docs/basic-design.md`
- `docs/detailed-design/index.md`
- `docs/detailed-design/backend.md`
- `docs/detailed-design/database.md`
- `docs/detailed-design/ai-agent.md`
- `docs/detailed-design/ui-grafana.md`
- `docs/detailed-design/device.md`
- `docs/detailed-design/infrastructure-operations.md`
- `docs/detailed-design/test-design.md`
