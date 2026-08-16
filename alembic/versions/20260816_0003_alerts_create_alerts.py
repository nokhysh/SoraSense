"""alertsテーブルを作成する。

Revision ID: 0003_alerts
Revises: 0002_measurements
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_alerts"
down_revision: str | None = "0002_measurements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEVICE_ID_PATTERN = "^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"


def upgrade() -> None:
    """alertsテーブル、制約、索引および最小権限を作成する。"""

    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("threshold_value", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("trigger_value", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("hysteresis", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"device_id ~ '{DEVICE_ID_PATTERN}'",
            name=op.f("ck_alerts_device_id_format"),
        ),
        sa.CheckConstraint(
            "direction IN ('LOW', 'HIGH')",
            name=op.f("ck_alerts_direction_value"),
        ),
        sa.CheckConstraint(
            "hysteresis > 0",
            name=op.f("ck_alerts_hysteresis_positive"),
        ),
        sa.CheckConstraint(
            "metric IN ('TEMPERATURE', 'HUMIDITY')",
            name=op.f("ck_alerts_metric_value"),
        ),
        sa.CheckConstraint(
            "(status = 'OPEN' AND resolved_at IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL)",
            name=op.f("ck_alerts_status_resolved_at"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'RESOLVED')",
            name=op.f("ck_alerts_status_value"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["app.devices.device_id"],
            name=op.f("fk_alerts_device_id_devices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        schema="app",
    )
    op.create_index(
        "ix_alerts_device_started",
        "alerts",
        ["device_id", sa.literal_column("started_at DESC")],
        schema="app",
    )
    op.create_index(
        "ix_alerts_device_status_started",
        "alerts",
        ["device_id", "status", sa.literal_column("started_at DESC")],
        schema="app",
    )
    op.create_index(
        "uq_alerts_open_condition",
        "alerts",
        ["device_id", "metric", "direction"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE app.alerts TO sorasense_app")
    op.execute("GRANT USAGE ON SEQUENCE app.alerts_id_seq TO sorasense_app")


def downgrade() -> None:
    """alertsテーブルを削除する。"""

    op.drop_index(
        "uq_alerts_open_condition",
        table_name="alerts",
        schema="app",
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.drop_index(
        "ix_alerts_device_status_started",
        table_name="alerts",
        schema="app",
    )
    op.drop_index(
        "ix_alerts_device_started",
        table_name="alerts",
        schema="app",
    )
    op.drop_table("alerts", schema="app")
