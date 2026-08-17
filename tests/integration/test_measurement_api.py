"""測定受付APIとPostgreSQLの結合を検証する。"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.config import Environment, Settings
from app.db.device_initializer import register_device
from app.main import create_app


def post_measurement(
    client: TestClient,
    device_id: str,
    api_key: str,
    measured_at: datetime,
    temperature: float,
) -> int:
    """指定した温度の測定を送信し、HTTP状態コードを返す。"""

    response = client.post(
        f"/api/v1/devices/{device_id}/measurements",
        json={
            "schema_version": 1,
            "message_id": str(uuid4()),
            "device_id": device_id,
            "measured_at": measured_at.isoformat(),
            "temperature_c": temperature,
            "humidity_percent": 50.0,
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return response.status_code


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


@pytest.mark.integration
def test_alert_lifecycle_direct_transition_and_delayed_measurement(
    app_database_url: str,
    migration_database_url: str,
) -> None:
    """開始、継続、直接遷移、復帰、再発および遅延到着を一連で検証する。"""

    device_id = f"phase4-state-{uuid4().hex[:12]}"
    api_key = "phase4-state-secret"
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
    base = datetime.now(UTC) - timedelta(minutes=1)

    try:
        statuses = [
            post_measurement(client, device_id, api_key, base, 9.0),
            post_measurement(client, device_id, api_key, base + timedelta(seconds=1), 9.5),
            post_measurement(client, device_id, api_key, base + timedelta(seconds=2), 36.0),
            post_measurement(client, device_id, api_key, base + timedelta(seconds=3), 34.5),
            post_measurement(client, device_id, api_key, base + timedelta(seconds=4), 36.0),
            # 最新判定時刻以前の正常値は履歴だけに保存する。
            post_measurement(client, device_id, api_key, base + timedelta(seconds=3), 20.0),
        ]
        with psycopg.connect(migration_database_url) as connection:
            alerts = connection.execute(
                """
                SELECT direction, status, started_at, resolved_at
                FROM app.alerts WHERE device_id = %s ORDER BY started_at
                """,
                (device_id,),
            ).fetchall()
            device_state = connection.execute(
                "SELECT last_alert_evaluated_at FROM app.devices WHERE device_id = %s",
                (device_id,),
            ).fetchone()
            measurement_count = connection.execute(
                "SELECT count(*) FROM app.measurements WHERE device_id = %s", (device_id,)
            ).fetchone()
            connection.execute("DELETE FROM app.alerts WHERE device_id = %s", (device_id,))
            connection.execute("DELETE FROM app.measurements WHERE device_id = %s", (device_id,))
            connection.execute("DELETE FROM app.devices WHERE device_id = %s", (device_id,))
    finally:
        engine.dispose()

    assert statuses == [201] * 6
    assert [(row[0], row[1]) for row in alerts] == [
        ("LOW", "RESOLVED"),
        ("HIGH", "RESOLVED"),
        ("HIGH", "OPEN"),
    ]
    assert device_state == (base + timedelta(seconds=4),)
    assert measurement_count == (6,)


@pytest.mark.integration
def test_concurrent_abnormal_measurements_create_one_open_alert(
    app_database_url: str,
    migration_database_url: str,
) -> None:
    """同一デバイスへの同時送信を直列化し、OPEN重複を防止する。"""

    device_id = f"phase4-lock-{uuid4().hex[:12]}"
    api_key = "phase4-lock-secret"
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
    measured_at = datetime.now(UTC) - timedelta(seconds=1)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    post_measurement,
                    TestClient(application),
                    device_id,
                    api_key,
                    measured_at + timedelta(microseconds=offset),
                    36.0,
                )
                for offset in (0, 1)
            ]
            statuses = [future.result() for future in futures]
        with psycopg.connect(migration_database_url) as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM app.measurements WHERE device_id = %s),
                    (SELECT count(*) FROM app.alerts
                     WHERE device_id = %s AND status = 'OPEN')
                """,
                (device_id, device_id),
            ).fetchone()
            connection.execute("DELETE FROM app.alerts WHERE device_id = %s", (device_id,))
            connection.execute("DELETE FROM app.measurements WHERE device_id = %s", (device_id,))
            connection.execute("DELETE FROM app.devices WHERE device_id = %s", (device_id,))
    finally:
        engine.dispose()

    assert statuses == [201, 201]
    assert counts == (2, 1)
