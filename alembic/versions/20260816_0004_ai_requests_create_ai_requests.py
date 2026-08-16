"""ai_requestsテーブルを作成する。

Revision ID: 0004_ai_requests
Revises: 0003_alerts
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_ai_requests"
down_revision: str | None = "0003_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """ai_requestsテーブル、制約、索引および最小権限を作成する。"""

    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("tool_calls", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name=op.f("ck_ai_requests_input_tokens_nonnegative"),
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name=op.f("ck_ai_requests_output_tokens_nonnegative"),
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND answer IS NULL AND error_code IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'SUCCEEDED' AND answer IS NOT NULL AND error_code IS NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('FAILED', 'REJECTED') AND answer IS NULL "
            "AND error_code IS NOT NULL AND completed_at IS NOT NULL)",
            name=op.f("ck_ai_requests_status_result"),
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'REJECTED')",
            name=op.f("ck_ai_requests_status_value"),
        ),
        sa.CheckConstraint(
            "tool_calls >= 0",
            name=op.f("ck_ai_requests_tool_calls_nonnegative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_requests")),
        schema="app",
    )
    op.create_index(
        "ix_ai_requests_created",
        "ai_requests",
        [sa.literal_column("created_at DESC")],
        schema="app",
    )
    op.create_index(
        "ix_ai_requests_status_created",
        "ai_requests",
        ["status", sa.literal_column("created_at DESC")],
        schema="app",
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE app.ai_requests TO sorasense_app"
    )


def downgrade() -> None:
    """ai_requestsテーブルを削除する。"""

    op.drop_index(
        "ix_ai_requests_status_created",
        table_name="ai_requests",
        schema="app",
    )
    op.drop_index(
        "ix_ai_requests_created",
        table_name="ai_requests",
        schema="app",
    )
    op.drop_table("ai_requests", schema="app")
