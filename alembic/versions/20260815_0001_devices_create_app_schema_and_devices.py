"""appスキーマとdevicesテーブルを作成する。

Revision ID: 0001_devices
Revises: なし
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_devices"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEVICE_ID_PATTERN = "^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"


def upgrade() -> None:
    """appスキーマとdevicesテーブルを作成する。"""

    op.execute("CREATE SCHEMA app AUTHORIZATION sorasense_migrator")
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_alert_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"device_id ~ '{DEVICE_ID_PATTERN}'",
            name=op.f("ck_devices_device_id_format"),
        ),
        sa.PrimaryKeyConstraint("device_id", name=op.f("pk_devices")),
        schema="app",
    )
    op.execute("GRANT USAGE ON SCHEMA app TO sorasense_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE app.devices TO sorasense_app"
    )


def downgrade() -> None:
    """devicesテーブルとappスキーマを削除する。"""

    op.drop_table("devices", schema="app")
    op.execute("DROP SCHEMA app")
