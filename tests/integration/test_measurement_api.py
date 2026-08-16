"""測定受付APIとPostgreSQLの結合を検証する。"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.config import Environment, Settings
from app.db.device_initializer import register_device
from app.main import create_app


@pytest.fixture
def migration_database_url() -> str:
    """結合テスト用のMigration接続URLを返す。"""

    database_url = os.getenv("TEST_MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_MIGRATION_DATABASE_URL is not set")
    return database_url


@pytest.fixture
def app_database_url() -> str:
    """結合テスト用の実行時DB接続URLを返す。"""

    database_url = os.getenv("TEST_APP_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_APP_DATABASE_URL is not set")
    return database_url


@pytest.mark.integration
def test_measurement_post_is_created_once_and_retry_is_idempotent(
    app_database_url: str,
    migration_database_url: str,
) -> None:
    """正常測定を201で保存し、同じmessage_idの再送を200にする。"""

    device_id = f"phase3-api-{uuid4().hex[:12]}"
    message_id = uuid4()
    api_key = "phase3-integration-secret"
    application = create_app(
        Settings(
            environment=Environment.TEST,
            database_url=app_database_url,
            device_id=device_id,
            device_api_key_hash=PasswordHasher().hash(api_key),
        )
    )
    engine = application.state.db_engine
    register_device(engine, device_id)
    client = TestClient(application)
    payload = {
        "schema_version": 1,
        "message_id": str(message_id),
        "device_id": device_id,
        "measured_at": datetime.now(UTC).isoformat(),
        "temperature_c": 24.5,
        "humidity_percent": 50.0,
    }

    try:
        created = client.post(
            f"/api/v1/devices/{device_id}/measurements",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        retried = client.post(
            f"/api/v1/devices/{device_id}/measurements",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with psycopg.connect(migration_database_url) as connection:
            count = connection.execute(
                """
                SELECT count(*) FROM app.measurements
                WHERE device_id = %s AND message_id = %s
                """,
                (device_id, message_id),
            ).fetchone()
            connection.execute("DELETE FROM app.measurements WHERE device_id = %s", (device_id,))
            connection.execute("DELETE FROM app.devices WHERE device_id = %s", (device_id,))
    finally:
        engine.dispose()

    assert created.status_code == 201
    assert created.json()["code"] == "MEASUREMENT_CREATED"
    assert retried.status_code == 200
    assert retried.json()["code"] == "MEASUREMENT_ALREADY_ACCEPTED"
    assert count == (1,)
