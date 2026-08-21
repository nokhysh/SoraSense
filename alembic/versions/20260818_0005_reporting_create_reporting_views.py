"""reportingスキーマと参照専用VIEWを作成する。

Revision ID: 0005_reporting
Revises: 0004_ai_requests
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_reporting"
down_revision: str | None = "0004_ai_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VIEW_SQL = {
    "v_latest_measurements": """
        SELECT DISTINCT ON (device_id)
            device_id, temperature_c, humidity_percent, measured_at, received_at
        FROM app.measurements
        ORDER BY device_id, measured_at DESC, id DESC
    """,
    "v_device_statuses": """
        SELECT
            d.device_id,
            latest.received_at AS last_received_at,
            EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - latest.received_at))::bigint
                AS elapsed_seconds,
            CASE
                WHEN latest.received_at IS NULL THEN 'OFFLINE'
                WHEN CURRENT_TIMESTAMP - latest.received_at <= INTERVAL '180 seconds'
                    THEN 'ONLINE'
                WHEN CURRENT_TIMESTAMP - latest.received_at <= INTERVAL '600 seconds'
                    THEN 'STALE'
                ELSE 'OFFLINE'
            END AS status
        FROM app.devices AS d
        LEFT JOIN LATERAL (
            SELECT m.received_at
            FROM app.measurements AS m
            WHERE m.device_id = d.device_id
            ORDER BY m.received_at DESC, m.id DESC
            LIMIT 1
        ) AS latest ON TRUE
    """,
    "v_measurement_series": """
        SELECT device_id, measured_at, temperature_c, humidity_percent
        FROM app.measurements
    """,
    "v_measurement_gaps": """
        WITH ordered AS (
            SELECT
                device_id,
                LAG(measured_at) OVER (
                    PARTITION BY device_id ORDER BY measured_at, id
                ) AS previous_measured_at,
                measured_at AS next_measured_at
            FROM app.measurements
        )
        SELECT
            device_id,
            previous_measured_at,
            next_measured_at,
            EXTRACT(EPOCH FROM (next_measured_at - previous_measured_at))::bigint
                AS interval_seconds,
            GREATEST(
                FLOOR(EXTRACT(EPOCH FROM (next_measured_at - previous_measured_at)) / 60) - 1,
                1
            )::bigint AS estimated_missing_count
        FROM ordered
        WHERE next_measured_at - previous_measured_at > INTERVAL '90 seconds'
    """,
    "v_alert_history": """
        SELECT
            id, device_id, metric, direction, status, threshold_value,
            trigger_value, hysteresis, started_at, last_detected_at, resolved_at
        FROM app.alerts
    """,
    "v_ai_usage_daily": """
        SELECT
            date_trunc('day', created_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                AS day_started_at,
            COUNT(*)::bigint AS request_count,
            COUNT(*) FILTER (WHERE status = 'SUCCEEDED')::bigint AS success_count,
            COUNT(*) FILTER (WHERE status IN ('FAILED', 'REJECTED'))::bigint
                AS failure_count,
            COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
            COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens
        FROM app.ai_requests
        GROUP BY 1
    """,
}


def upgrade() -> None:
    """VIEWを作成し、GrafanaへVIEWの参照権限だけを付与する。"""

    op.execute("CREATE SCHEMA reporting AUTHORIZATION sorasense_migrator")
    for name, query in VIEW_SQL.items():
        op.execute(f"CREATE VIEW reporting.{name} AS {query}")
    op.execute("REVOKE ALL ON SCHEMA reporting FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA reporting TO grafana_reader")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO grafana_reader")


def downgrade() -> None:
    """Grafanaの権限とreportingスキーマを削除する。"""

    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA reporting FROM grafana_reader")
    op.execute("REVOKE ALL ON SCHEMA reporting FROM grafana_reader")
    op.execute("DROP SCHEMA reporting CASCADE")
