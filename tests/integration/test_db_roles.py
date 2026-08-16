"""PostgreSQLロールと最小権限を検証する。"""

import os
from datetime import UTC, datetime
from uuid import uuid4

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


@pytest.mark.integration
def test_app_role_has_only_required_phase2_privileges(app_database_url: str) -> None:
    """実行時ロールが全基底表とSequenceに必要最小限の権限だけを持つ。"""

    table_names = ["devices", "measurements", "alerts", "ai_requests"]
    with psycopg.connect(app_database_url) as connection:
        schema_privileges = connection.execute(
            """
            SELECT
                has_schema_privilege(current_user, 'app', 'USAGE'),
                has_schema_privilege(current_user, 'app', 'CREATE')
            """
        ).fetchone()
        table_privileges = connection.execute(
            """
            SELECT
                table_name,
                has_table_privilege(current_user, 'app.' || table_name, 'SELECT'),
                has_table_privilege(current_user, 'app.' || table_name, 'INSERT'),
                has_table_privilege(current_user, 'app.' || table_name, 'UPDATE'),
                has_table_privilege(current_user, 'app.' || table_name, 'DELETE'),
                has_table_privilege(current_user, 'app.' || table_name, 'TRUNCATE')
            FROM unnest(%s::text[]) AS table_name
            ORDER BY table_name
            """,
            (table_names,),
        ).fetchall()
        sequence_privileges = connection.execute(
            """
            SELECT
                has_sequence_privilege(
                    current_user,
                    'app.measurements_id_seq',
                    'USAGE'
                ),
                has_sequence_privilege(current_user, 'app.alerts_id_seq', 'USAGE')
            """
        ).fetchone()

    assert schema_privileges == (True, False)
    assert {row[0]: row[1:] for row in table_privileges} == {
        table_name: (True, True, True, False, False) for table_name in table_names
    }
    assert sequence_privileges == (True, True)


@pytest.mark.integration
def test_app_role_can_use_all_phase2_tables(app_database_url: str) -> None:
    """実行時ロールが全基底表で参照・登録・更新を実行できる。"""

    device_id = "phase2-role-test"
    now = datetime.now(UTC)
    with psycopg.connect(app_database_url) as connection:
        connection.execute(
            "INSERT INTO app.devices (device_id) VALUES (%s)",
            (device_id,),
        )
        measurement_id = connection.execute(
            """
            INSERT INTO app.measurements (
                device_id, message_id, measured_at, temperature_c, humidity_percent
            ) VALUES (%s, %s, %s, 25, 50)
            RETURNING id
            """,
            (device_id, uuid4(), now),
        ).fetchone()
        alert_id = connection.execute(
            """
            INSERT INTO app.alerts (
                device_id, metric, direction, status, threshold_value,
                trigger_value, hysteresis, started_at, last_detected_at
            ) VALUES (%s, 'TEMPERATURE', 'HIGH', 'OPEN', 35, 36, 0.5, %s, %s)
            RETURNING id
            """,
            (device_id, now, now),
        ).fetchone()
        request_id = uuid4()
        connection.execute(
            """
            INSERT INTO app.ai_requests (id, question, status)
            VALUES (%s, '現在の温度は？', 'RUNNING')
            """,
            (request_id,),
        )

        connection.execute(
            "UPDATE app.measurements SET temperature_c = 26 WHERE id = %s",
            (measurement_id[0] if measurement_id else None,),
        )
        connection.execute(
            "UPDATE app.alerts SET last_detected_at = %s WHERE id = %s",
            (now, alert_id[0] if alert_id else None),
        )
        connection.execute(
            "UPDATE app.ai_requests SET model = 'test-model' WHERE id = %s",
            (request_id,),
        )
        row_count = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM app.measurements WHERE device_id = %s),
                (SELECT count(*) FROM app.alerts WHERE device_id = %s),
                (SELECT count(*) FROM app.ai_requests WHERE id = %s)
            """,
            (device_id, device_id, request_id),
        ).fetchone()
        connection.rollback()

    assert measurement_id is not None
    assert alert_id is not None
    assert row_count == (1, 1, 1)
