"""フェーズ5のVIEW、照会結果およびGrafana最小権限を検証する。"""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg import errors
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.schemas.query import Granularity
from app.services.query_service import QueryService


def required_url(name: str) -> str:
    """指定された結合テストURLを取得し、未設定ならテストを省略する。"""

    value = os.getenv(name)
    if value is None:
        pytest.skip(f"{name} is not set")
    return value


@pytest.mark.integration
def test_reporting_views_preserve_latest_status_gap_and_query_semantics() -> None:
    """IT-006としてVIEWとQueryServiceが同じ期間・欠損規則に従う。"""

    migration_url = required_url("TEST_MIGRATION_DATABASE_URL")
    app_url = required_url("TEST_APP_DATABASE_URL")
    device_id = f"phase5-reporting-{uuid4().hex[:8]}"
    offline_device_id = f"phase5-offline-{uuid4().hex[:8]}"
    start = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)

    try:
        with psycopg.connect(migration_url) as connection:
            connection.execute(
                "INSERT INTO app.devices (device_id) VALUES (%s), (%s)",
                (device_id, offline_device_id),
            )
            for offset, temperature in [(0, 20), (60, 21), (180, 22), (180, 23)]:
                connection.execute(
                    """
                    INSERT INTO app.measurements (
                        device_id, message_id, measured_at, temperature_c, humidity_percent
                    ) VALUES (%s, %s, %s, %s, 50)
                    """,
                    (device_id, uuid4(), start + timedelta(seconds=offset), temperature),
                )
            connection.commit()

        with psycopg.connect(migration_url) as connection:
            latest = connection.execute(
                """
                SELECT temperature_c
                FROM reporting.v_latest_measurements
                WHERE device_id = %s
                """,
                (device_id,),
            ).fetchone()
            statuses = dict(connection.execute(
                """
                SELECT device_id, status
                FROM reporting.v_device_statuses
                WHERE device_id IN (%s, %s)
                """,
                (device_id, offline_device_id),
            ).fetchall())
            gaps = connection.execute(
                """
                SELECT interval_seconds, estimated_missing_count
                FROM reporting.v_measurement_gaps
                WHERE device_id = %s
                """,
                (device_id,),
            ).fetchall()

        engine = create_engine(make_url(app_url).set(drivername="postgresql+psycopg"))
        try:
            with Session(engine) as session:
                statistics = QueryService().get_measurement_statistics(
                    session,
                    device_id,
                    start,
                    start + timedelta(seconds=180),
                )
                series = QueryService().get_measurement_series(
                    session,
                    device_id,
                    start,
                    start + timedelta(minutes=4),
                    Granularity.HOUR,
                )
        finally:
            engine.dispose()

        assert latest == (Decimal("23.00"),)
        assert statuses[offline_device_id] == "OFFLINE"
        assert gaps == [(120, 1)]
        # 終端180秒の2行は半開区間に含まれない。
        assert statistics.temperature.count == 2
        assert statistics.temperature.average == Decimal("20.50")
        assert statistics.timezone == "Asia/Tokyo"
        assert series.timezone == "Asia/Tokyo"
        assert len(series.points) == 1
        assert series.points[0].bucket_from == start
        assert series.points[0].bucket_to == start + timedelta(hours=1)
    finally:
        with psycopg.connect(migration_url) as connection:
            connection.execute(
                "DELETE FROM app.measurements WHERE device_id = %s",
                (device_id,),
            )
            connection.execute(
                "DELETE FROM app.devices WHERE device_id IN (%s, %s)",
                (device_id, offline_device_id),
            )


@pytest.mark.integration
def test_grafana_reader_can_select_only_reporting_views() -> None:
    """IT-009としてGrafanaロールがVIEW以外を参照・更新できない。"""

    reader_url = required_url("TEST_GRAFANA_DATABASE_URL")

    with psycopg.connect(reader_url) as connection:
        view_count = connection.execute(
            "SELECT count(*) FROM reporting.v_device_statuses"
        ).fetchone()
        write_privileges = connection.execute(
            """
            SELECT
                has_table_privilege(
                    current_user, 'reporting.v_measurement_series', 'INSERT'
                ),
                has_table_privilege(
                    current_user, 'reporting.v_measurement_series', 'UPDATE'
                ),
                has_table_privilege(
                    current_user, 'reporting.v_measurement_series', 'DELETE'
                )
            """
        ).fetchone()

    assert view_count is not None
    assert write_privileges == (False, False, False)

    with (
        psycopg.connect(reader_url) as connection,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        connection.execute("SELECT count(*) FROM app.devices")

    with (
        psycopg.connect(reader_url) as connection,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        connection.execute("UPDATE reporting.v_measurement_series SET temperature_c = 0")
