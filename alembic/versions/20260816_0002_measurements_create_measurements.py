"""measurementsテーブルを作成する。

Revision ID: 0002_measurements
Revises: 0001_devices
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_measurements"
down_revision: str | None = "0001_devices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEVICE_ID_PATTERN = "^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"


def upgrade() -> None:
    """measurementsテーブル、制約、索引および最小権限を作成する。"""

    op.create_table(
        "measurements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature_c", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("humidity_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"device_id ~ '{DEVICE_ID_PATTERN}'",
            name=op.f("ck_measurements_device_id_format"),
        ),
        sa.CheckConstraint(
            "humidity_percent BETWEEN 0.00 AND 100.00",
            name=op.f("ck_measurements_humidity_range"),
        ),
        sa.CheckConstraint(
            "temperature_c BETWEEN -40.00 AND 85.00",
            name=op.f("ck_measurements_temperature_range"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["app.devices.device_id"],
            name=op.f("fk_measurements_device_id_devices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measurements")),
        sa.UniqueConstraint(
            "device_id",
            "message_id",
            name="uq_measurements_device_message",
        ),
        schema="app",
    )
    op.create_index(
        "ix_measurements_device_measured",
        "measurements",
        ["device_id", sa.literal_column("measured_at DESC"), sa.literal_column("id DESC")],
        schema="app",
    )
    op.create_index(
        "ix_measurements_device_received",
        "measurements",
        ["device_id", sa.literal_column("received_at DESC")],
        schema="app",
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE app.measurements TO sorasense_app"
    )
    op.execute("GRANT USAGE ON SEQUENCE app.measurements_id_seq TO sorasense_app")


def downgrade() -> None:
    """measurementsテーブルを削除する。"""

    op.drop_index(
        "ix_measurements_device_received",
        table_name="measurements",
        schema="app",
    )
    op.drop_index(
        "ix_measurements_device_measured",
        table_name="measurements",
        schema="app",
    )
    op.drop_table("measurements", schema="app")
