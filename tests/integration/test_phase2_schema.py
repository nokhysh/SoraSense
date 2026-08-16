"""フェーズ2のテーブル制約をPostgreSQLで検証する。"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg import errors
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.db.device_initializer import register_device


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
def test_initial_device_registration_is_idempotent(
    app_database_url: str,
    migration_database_url: str,
) -> None:
    """同じDEVICE_IDを複数回初期化してもデバイスを1行だけ登録する。"""

    device_id = "phase2-initializer-test"
    engine = create_engine(
        make_url(app_database_url).set(drivername="postgresql+psycopg")
    )
    try:
        assert register_device(engine, device_id) is True
        assert register_device(engine, device_id) is False

        with psycopg.connect(migration_database_url) as connection:
            count = connection.execute(
                "SELECT count(*) FROM app.devices WHERE device_id = %s",
                (device_id,),
            ).fetchone()
            connection.execute(
                "DELETE FROM app.devices WHERE device_id = %s",
                (device_id,),
            )
    finally:
        engine.dispose()

    assert count == (1,)


@pytest.mark.integration
def test_measurements_enforce_range_foreign_key_and_uniqueness(
    migration_database_url: str,
) -> None:
    """測定値の範囲、デバイス参照およびメッセージ重複を拒否する。"""

    now = datetime.now(UTC)
    message_id = uuid4()
    with psycopg.connect(migration_database_url) as connection:
        connection.execute(
            "INSERT INTO app.devices (device_id) VALUES (%s)",
            ("phase2-measurement-test",),
        )
        connection.execute(
            """
            INSERT INTO app.measurements (
                device_id, message_id, measured_at, temperature_c, humidity_percent
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            ("phase2-measurement-test", message_id, now, 25.0, 50.0),
        )

        with pytest.raises(errors.UniqueViolation):
            connection.execute(
                """
                INSERT INTO app.measurements (
                    device_id, message_id, measured_at, temperature_c, humidity_percent
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                ("phase2-measurement-test", message_id, now, 25.0, 50.0),
            )
        connection.rollback()

        with pytest.raises(errors.CheckViolation):
            connection.execute(
                """
                INSERT INTO app.measurements (
                    device_id, message_id, measured_at, temperature_c, humidity_percent
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                ("phase2-measurement-test", uuid4(), now, 86.0, 50.0),
            )
        connection.rollback()

        with pytest.raises(errors.ForeignKeyViolation):
            connection.execute(
                """
                INSERT INTO app.measurements (
                    device_id, message_id, measured_at, temperature_c, humidity_percent
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                ("unregistered-device", uuid4(), now, 25.0, 50.0),
            )


@pytest.mark.integration
def test_alerts_enforce_state_and_one_open_condition(migration_database_url: str) -> None:
    """アラートの状態整合と同一OPEN条件の一意性を保証する。"""

    now = datetime.now(UTC)
    with psycopg.connect(migration_database_url) as connection:
        connection.execute(
            "INSERT INTO app.devices (device_id) VALUES (%s)",
            ("phase2-alert-test",),
        )
        values = ("phase2-alert-test", "TEMPERATURE", "HIGH", "OPEN", 35, 36, 0.5, now, now)
        connection.execute(
            """
            INSERT INTO app.alerts (
                device_id, metric, direction, status, threshold_value,
                trigger_value, hysteresis, started_at, last_detected_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )
        with pytest.raises(errors.UniqueViolation):
            connection.execute(
                """
                INSERT INTO app.alerts (
                    device_id, metric, direction, status, threshold_value,
                    trigger_value, hysteresis, started_at, last_detected_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                values,
            )
        connection.rollback()

        with pytest.raises(errors.CheckViolation):
            connection.execute(
                """
                INSERT INTO app.alerts (
                    device_id, metric, direction, status, threshold_value,
                    trigger_value, hysteresis, started_at, last_detected_at, resolved_at
                ) VALUES (%s, 'TEMPERATURE', 'HIGH', 'RESOLVED', 35, 36, 0.5, %s, %s, NULL)
                """,
                ("phase2-alert-test", now, now),
            )


@pytest.mark.integration
def test_ai_requests_enforce_status_result_and_usage_ranges(
    migration_database_url: str,
) -> None:
    """AI質問の状態別結果と利用量の整合性を保証する。"""

    with psycopg.connect(migration_database_url) as connection:
        connection.execute(
            """
            INSERT INTO app.ai_requests (id, question, status)
            VALUES (%s, %s, 'RUNNING')
            """,
            (uuid4(), "現在の温度は？"),
        )
        with pytest.raises(errors.CheckViolation):
            connection.execute(
                """
                INSERT INTO app.ai_requests (
                    id, question, answer, status, tool_calls, completed_at
                ) VALUES (%s, %s, %s, 'SUCCEEDED', -1, CURRENT_TIMESTAMP)
                """,
                (uuid4(), "現在の温度は？", "25度です"),
            )
