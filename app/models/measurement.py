"""温湿度測定値のSQLAlchemyモデルを定義する。"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    desc,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.device import DEVICE_ID_PATTERN


class Measurement(Base):
    """デバイスから受信した温度と湿度の測定値を保持する。"""

    __tablename__ = "measurements"
    __table_args__ = (
        CheckConstraint(
            f"device_id ~ '{DEVICE_ID_PATTERN}'",
            name="device_id_format",
        ),
        CheckConstraint(
            "temperature_c BETWEEN -40.00 AND 85.00",
            name="temperature_range",
        ),
        CheckConstraint(
            "humidity_percent BETWEEN 0.00 AND 100.00",
            name="humidity_range",
        ),
        UniqueConstraint(
            "device_id",
            "message_id",
            name="uq_measurements_device_message",
        ),
        Index(
            "ix_measurements_device_measured",
            "device_id",
            desc("measured_at"),
            desc("id"),
        ),
        Index(
            "ix_measurements_device_received",
            "device_id",
            desc("received_at"),
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
    message_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    temperature_c: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )
    humidity_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
