"""AI質問実行履歴のSQLAlchemyモデルを定義する。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, Uuid, desc, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIRequest(Base):
    """AI質問の状態、回答、エラー分類および利用量を保持する。"""

    __tablename__ = "ai_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'REJECTED')",
            name="status_value",
        ),
        CheckConstraint("tool_calls >= 0", name="tool_calls_nonnegative"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="input_tokens_nonnegative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="output_tokens_nonnegative",
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND answer IS NULL AND error_code IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'SUCCEEDED' AND answer IS NOT NULL AND error_code IS NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('FAILED', 'REJECTED') AND answer IS NULL "
            "AND error_code IS NOT NULL AND completed_at IS NOT NULL)",
            name="status_result",
        ),
        Index("ix_ai_requests_created", desc("created_at")),
        Index("ix_ai_requests_status_created", "status", desc("created_at")),
        {"schema": "app"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_calls: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
