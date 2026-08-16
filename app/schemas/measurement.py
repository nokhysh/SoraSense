"""測定受付APIの外部データを、Serviceが安全に扱える型へ変換する。

HTTP固有の応答コードやDB保存処理は扱わず、形式、範囲および時刻の検証を担当する。
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.device import DEVICE_ID_PATTERN


class MeasurementRequest(BaseModel):
    """検証済みで変更不能なデバイス測定データ。

    未知フィールドは将来のデバイスSchema追加に対する後方互換性のため無視する。
    frozenにより、検証後の値が保存処理中に書き換わることを防ぐ。
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    schema_version: Annotated[int, Field(strict=True)]
    message_id: UUID
    device_id: Annotated[str, Field(pattern=DEVICE_ID_PATTERN)]
    measured_at: datetime
    temperature_c: Annotated[Decimal, Field(ge=Decimal("-40.0"), le=Decimal("85.0"))]
    humidity_percent: Annotated[Decimal, Field(ge=Decimal("0.0"), le=Decimal("100.0"))]

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        """対応するSchema版だけを受け付ける。"""

        if value != 1:
            raise ValueError("schema_version must be 1")
        return value

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, value: UUID) -> UUID:
        """message_idがUUID v4であることを確認する。"""

        if value.version != 4:
            raise ValueError("message_id must be UUID v4")
        return value

    @field_validator("measured_at")
    @classmethod
    def validate_measured_at(cls, value: datetime) -> datetime:
        """測定日時がUTCであり、許容範囲を超えた未来でないことを確認する。"""

        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("measured_at must be UTC")
        normalized = value.astimezone(UTC)
        if normalized > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("measured_at is too far in the future")
        return normalized

    @field_validator("temperature_c", "humidity_percent", mode="before")
    @classmethod
    def validate_finite_number(cls, value: Any) -> Any:
        """NaNと無限大を拒否する。"""

        try:
            if not Decimal(str(value)).is_finite():
                raise ValueError("measurement value must be finite")
        except Exception as error:
            if isinstance(error, ValueError):
                raise
        return value


class ApiResponse(BaseModel):
    """成功・失敗のどちらでも相関IDを返す共通応答。"""

    code: str
    message: str
    request_id: str
