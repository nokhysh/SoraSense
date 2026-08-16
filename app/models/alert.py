"""異常状態のSQLAlchemyモデルを定義する。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    desc,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.device import DEVICE_ID_PATTERN


class Alert(Base):
    """デバイスごとの異常発生・継続・解消状態を保持する。"""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            f"device_id ~ '{DEVICE_ID_PATTERN}'",
            name="device_id_format",
        ),
        CheckConstraint(
            "metric IN ('TEMPERATURE', 'HUMIDITY')",
            name="metric_value",
        ),
        CheckConstraint(
            "direction IN ('LOW', 'HIGH')",
            name="direction_value",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'RESOLVED')",
            name="status_value",
        ),
        CheckConstraint("hysteresis > 0", name="hysteresis_positive"),
        CheckConstraint(
            "(status = 'OPEN' AND resolved_at IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL)",
            name="status_resolved_at",
        ),
        Index(
            "ix_alerts_device_started",
            "device_id",
            desc("started_at"),
        ),
        Index(
            "ix_alerts_device_status_started",
            "device_id",
            "status",
            desc("started_at"),
        ),
        Index(
            "uq_alerts_open_condition",
            "device_id",
            "metric",
            "direction",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    device_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("app.devices.device_id"),
        nullable=False,
    )
    metric: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    threshold_value: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    trigger_value: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    hysteresis: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
