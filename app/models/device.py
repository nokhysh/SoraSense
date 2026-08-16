"""登録デバイスのSQLAlchemyモデルを定義する。"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DEVICE_ID_PATTERN = "^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"


class Device(Base):
    """登録済みデバイスと最新のアラート判定日時を保持する。"""

    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            f"device_id ~ '{DEVICE_ID_PATTERN}'",
            name="device_id_format",
        ),
        {"schema": "app"},
    )

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    last_alert_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
