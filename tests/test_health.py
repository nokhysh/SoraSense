"""ヘルスチェックとアプリケーション生成を検証する。"""

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from app.config import Environment, Settings
from app.main import create_app


def test_live_health_check_returns_ok() -> None:
    """Liveヘルスチェックが固定された正常応答を返す。"""

    client = TestClient(create_app(Settings(environment=Environment.TEST)))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _Connection:
    """ReadyテストでSELECT実行を記録する接続Fake。"""

    def __init__(self) -> None:
        self.statement = ""

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        self.statement = str(statement)


class _Engine:
    """Readyテスト用のEngine Fake。"""

    def __init__(self, connection: _Connection) -> None:
        self.connection_result = connection

    def connect(self) -> _Connection:
        return self.connection_result


def _ready_settings() -> Settings:
    """測定受付の必須設定が揃ったテスト設定を返す。"""

    return Settings(
        environment=Environment.TEST,
        database_url="postgresql://app:password@postgres/sorasense",
        device_id="living-room-01",
        device_api_key_hash=SecretStr("argon2id-hash"),
    )


def test_ready_health_check_verifies_database() -> None:
    """必須設定とDBが利用可能ならReadyを返す。"""

    application = create_app(_ready_settings())
    connection = _Connection()
    application.state.readiness_engine = _Engine(connection)

    response = TestClient(application).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert connection.statement == "SELECT 1"


def test_ready_health_check_rejects_missing_configuration() -> None:
    """測定受付の必須設定がなければ503を返す。"""

    response = TestClient(create_app(Settings(environment=Environment.TEST))).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_ready_health_check_hides_database_failure() -> None:
    """DB障害の内部情報を公開せず503へ変換する。"""

    application = create_app(_ready_settings())
    application.state.readiness_engine.connect = lambda: (_ for _ in ()).throw(
        OperationalError("SELECT 1", {}, Exception("secret-db-detail"))
    )

    response = TestClient(application).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "secret-db-detail" not in response.text


def test_live_health_check_is_independent_from_database_failure() -> None:
    """DB障害時もFastAPIプロセスが応答可能ならLiveは200を返す。"""

    application = create_app(_ready_settings())
    application.state.readiness_engine.connect = lambda: (_ for _ in ()).throw(
        OperationalError("SELECT 1", {}, Exception("database-unavailable"))
    )

    response = TestClient(application).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_documentation_is_available_outside_production() -> None:
    """テスト環境ではOpenAPI定義を利用できる。"""

    client = TestClient(create_app(Settings(environment=Environment.TEST)))

    assert client.get("/openapi.json").status_code == 200


def test_api_documentation_is_hidden_in_production() -> None:
    """本番環境ではAPIドキュメントを公開しない。"""

    client = TestClient(
        create_app(
            Settings(
                environment=Environment.PRODUCTION,
                web_username="admin",
                web_password_hash=SecretStr(PasswordHasher().hash("test-password")),
            )
        )
    )

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
