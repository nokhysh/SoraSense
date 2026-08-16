"""PostgreSQLロールと最小権限を検証する。"""

import os

import psycopg
import pytest
from psycopg import errors


@pytest.fixture
def app_database_url() -> str:
    """結合テスト用の実行時DB接続URLを返す。"""

    database_url = os.getenv("TEST_APP_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_APP_DATABASE_URL is not set")
    return database_url


@pytest.mark.integration
def test_database_roles_have_minimum_attributes(app_database_url: str) -> None:
    """各ロールがログイン以外の管理権限を持たないことを確認する。"""

    role_names = {"sorasense_migrator", "sorasense_app", "grafana_reader"}

    with psycopg.connect(app_database_url) as connection:
        rows = connection.execute(
            """
            SELECT
                rolname,
                rolcanlogin,
                rolsuper,
                rolcreatedb,
                rolcreaterole,
                rolreplication,
                rolbypassrls
            FROM pg_roles
            WHERE rolname = ANY(%s)
            """,
            (list(role_names),),
        ).fetchall()

    assert {row[0] for row in rows} == role_names
    for row in rows:
        assert row[1:] == (True, False, False, False, False, False)


@pytest.mark.integration
def test_app_role_cannot_create_schema(app_database_url: str) -> None:
    """実行時ロールにDDL権限がないことを確認する。"""

    with (
        psycopg.connect(app_database_url) as connection,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        connection.execute("CREATE SCHEMA forbidden_by_test")


@pytest.mark.integration
def test_app_role_can_use_devices_table(app_database_url: str) -> None:
    """実行時ロールがdevicesで必要な参照・登録・更新を実行できる。"""

    with psycopg.connect(app_database_url) as connection:
        connection.execute(
            "INSERT INTO app.devices (device_id) VALUES (%s)",
            ("permission-test-device",),
        )
        device = connection.execute(
            "SELECT device_id FROM app.devices WHERE device_id = %s",
            ("permission-test-device",),
        ).fetchone()
        connection.execute(
            """
            UPDATE app.devices
            SET last_alert_evaluated_at = CURRENT_TIMESTAMP
            WHERE device_id = %s
            """,
            ("permission-test-device",),
        )
        connection.rollback()

    assert device == ("permission-test-device",)


@pytest.mark.integration
@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM app.devices WHERE device_id = 'permission-test-device'",
        "TRUNCATE app.devices",
        "ALTER TABLE app.devices ADD COLUMN forbidden integer",
        "DROP TABLE app.devices",
    ],
)
def test_app_role_cannot_modify_devices_structure_or_delete(
    app_database_url: str,
    statement: str,
) -> None:
    """実行時ロールが削除系操作とDDLを実行できない。"""

    with (
        psycopg.connect(app_database_url) as connection,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        connection.execute(statement)
