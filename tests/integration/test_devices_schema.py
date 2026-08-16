"""app.devicesの物理スキーマと制約を検証する。"""

import os

import psycopg
import pytest
from psycopg import errors


@pytest.fixture
def migration_database_url() -> str:
    """結合テスト用のMigration接続URLを返す。"""

    database_url = os.getenv("TEST_MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_MIGRATION_DATABASE_URL is not set")
    return database_url


@pytest.mark.integration
def test_devices_table_rejects_invalid_device_id(migration_database_url: str) -> None:
    """DBのCHECK制約が不正なデバイスIDを拒否する。"""

    with (
        psycopg.connect(migration_database_url) as connection,
        pytest.raises(errors.CheckViolation),
    ):
        connection.execute(
            "INSERT INTO app.devices (device_id) VALUES (%s)",
            ("Invalid_Device",),
        )


@pytest.mark.integration
def test_devices_table_accepts_valid_device_id(migration_database_url: str) -> None:
    """DBが有効なデバイスIDと初期値を保存できる。"""

    with psycopg.connect(migration_database_url) as connection:
        device = connection.execute(
            """
            INSERT INTO app.devices (device_id)
            VALUES (%s)
            RETURNING device_id, registered_at, last_alert_evaluated_at
            """,
            ("living-room-01",),
        ).fetchone()
        connection.rollback()

    assert device is not None
    assert device[0] == "living-room-01"
    assert device[1] is not None
    assert device[2] is None
