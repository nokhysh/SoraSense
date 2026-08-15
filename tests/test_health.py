"""ヘルスチェックとアプリケーション生成を検証する。"""

from fastapi.testclient import TestClient

from app.config import Environment, Settings
from app.main import create_app


def test_live_health_check_returns_ok() -> None:
    """Liveヘルスチェックが固定された正常応答を返す。"""

    client = TestClient(create_app(Settings(environment=Environment.TEST)))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_documentation_is_available_outside_production() -> None:
    """テスト環境ではOpenAPI定義を利用できる。"""

    client = TestClient(create_app(Settings(environment=Environment.TEST)))

    assert client.get("/openapi.json").status_code == 200


def test_api_documentation_is_hidden_in_production() -> None:
    """本番環境ではAPIドキュメントを公開しない。"""

    client = TestClient(create_app(Settings(environment=Environment.PRODUCTION)))

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
