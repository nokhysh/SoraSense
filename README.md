# SoraSense

SoraSenseは、室内の温度・湿度を収集、保存、可視化し、蓄積したデータについて
自然言語で質問できるIoT環境モニタリングシステムです。

M5StickC Plus2とENV IV Unitで測定したデータをFastAPIへ送信し、PostgreSQLへ保存します。
現在値や履歴、異常状態はGrafanaで確認でき、AI AgentはGemini Developer APIを利用して
集計、比較、傾向を説明します。

> [!IMPORTANT]
> 本システムはローカルネットワーク内での個人利用を想定しています。
> 医療、生命維持、防災用途や、公的な精度保証が必要な測定には使用できません。

## 主な機能

- 温度・湿度データの受信、検証、重複抑止、保存
- 閾値とヒステリシスに基づく異常検知
- Grafanaによる現在値、履歴、集計、アラート、デバイス状態の表示
- Geminiを利用した自然言語でのデータ照会
- M5StickC Plus2による60秒周期の測定と、通信失敗時の再送
- Live／Readyヘルスチェックと構造化ログ

## システム構成

```text
M5StickC Plus2 + ENV IV Unit
             │ 測定データ（HTTP）
             ▼
          FastAPI ───── Gemini Developer API（HTTPS）
             │
             ▼
         PostgreSQL ◀──── Grafana
```

| コンポーネント | 主な技術 | 役割 |
|---|---|---|
| センサーデバイス | M5StickC Plus2、ENV IV Unit、PlatformIO | 温度・湿度の測定と送信 |
| Web／API | Python 3.12、FastAPI | 測定受付、Web認証、AI質問画面 |
| データベース | PostgreSQL 16、SQLAlchemy、Alembic | 測定値、アラート、AI利用履歴の保存 |
| ダッシュボード | Grafana | 保存データの可視化 |
| AI Agent | Gemini Developer API | データの照会、集計、比較、傾向説明 |

## 必要な環境

- DockerおよびDocker Compose
- Python 3.12（開発ツールやSecret生成スクリプトをローカルで実行する場合）
- Gemini Developer APIのFree Tier用APIキー（AI機能を使用する場合）
- PlatformIO（センサーデバイスをビルドする場合）

## セットアップ

### 1. リポジトリを取得する

```shell
git clone <repository-url>
cd SoraSense
```

### 2. Python開発環境を準備する

```shell
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

### 3. 環境変数を設定する

```shell
cp .env.example .env
```

`.env`のサンプル値を、ローカル環境用の値へ置き換えてください。特に次の設定が必要です。

- PostgreSQL、アプリ、Grafanaの各パスワード
- M5StickC Plus2と同じLANから到達可能な`APP_BIND_ADDRESS`
- `DEVICE_ID`とデバイスAPIキーのハッシュ
- `WEB_USERNAME`とWebログインパスワードのハッシュ
- `GEMINI_API_KEY`（AI機能を使用する場合）

Argon2idハッシュは、次のスクリプトで生成できます。入力した平文は画面やファイルへ出力されません。

```shell
python scripts/generate-device-api-key-hash.py
python scripts/generate-web-password-hash.py
```

生成されたハッシュは、`.env.example`の説明どおり一重引用符で囲んで設定してください。
Secretの実値や平文のAPIキー、パスワードをGitへ登録しないでください。

## 起動方法

初回は、データベースの起動、Migration、初期デバイス登録の順に実行します。

```shell
docker compose up -d postgres
docker compose --profile tools run --rm migration
docker compose --profile tools run --rm device-init
docker compose up -d app grafana
```

サービスの状態を確認します。

```shell
docker compose ps
```

| 画面・エンドポイント | URL |
|---|---|
| AI質問画面 | `http://<APP_BIND_ADDRESS>:8000/agent` |
| APIドキュメント（開発環境） | `http://<APP_BIND_ADDRESS>:8000/docs` |
| Liveチェック | `http://<APP_BIND_ADDRESS>:8000/health/live` |
| Readyチェック | `http://<APP_BIND_ADDRESS>:8000/health/ready` |
| Grafana | `http://127.0.0.1:3000/` |

停止する場合は、次を実行します。

```shell
docker compose down
```

PostgreSQLのデータはDocker volumeへ保持されます。データを残したい場合は、volumeを削除する
オプションを付けないでください。

## センサーデバイス

M5StickC Plus2の設定、ビルド、実機への書き込み方法は、
[firmware/README.md](firmware/README.md)を参照してください。

## 開発とテスト

単体テスト、Lint、型チェックは次のコマンドで実行します。

```shell
pytest
ruff check .
mypy app tests
```

PostgreSQLを使用する結合テストは、必要なテスト用接続情報を設定した環境で実行してください。
環境変数が未設定の場合、対象の結合テストはスキップされます。

ファームウェアの検証方法は[firmware/README.md](firmware/README.md)に記載しています。

## ディレクトリ構成

```text
app/                 FastAPIアプリケーション
alembic/             データベースMigration
docs/                要件定義、設計、実装ロードマップ
firmware/            M5StickC Plus2用ファームウェア
grafana/             DashboardとProvisioning設定
scripts/             初期化・Secret生成用スクリプト
tests/               単体テストと結合テスト
compose.yaml         ローカル実行環境
```

## ドキュメント

- [要件定義書](docs/requirements.md)
- [基本設計書](docs/basic-design.md)
- [詳細設計書](docs/detailed-design/index.md)
- [実装ロードマップ](docs/implementation-roadmap.md)
- [センサーデバイスREADME](firmware/README.md)

## セキュリティ上の注意

- FastAPIとGrafanaをインターネットへ直接公開しないでください。
- FastAPIの公開範囲は、ホストのファイアウォールでも管理対象LANに制限してください。
- PostgreSQLはComposeの内部ネットワークだけで使用してください。
- APIキー、パスワード、データベース接続情報をソースコードやログへ記録しないでください。
- AI Agentの回答は補助情報として扱い、重要な判断ではGrafanaなどで元データを確認してください。
