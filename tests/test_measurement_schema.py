"""測定受付のRequest Schemaを検証する。"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.schemas.measurement import MeasurementRequest


def valid_payload() -> dict[str, object]:
    """検証用の正常な測定データを返す。"""

    return {
        "schema_version": 1,
        "message_id": str(uuid4()),
        "device_id": "living-room-01",
        "measured_at": datetime.now(UTC).isoformat(),
        "temperature_c": 26.4,
        "humidity_percent": 58.2,
    }


def test_request_schema_accepts_valid_payload_and_ignores_unknown_fields() -> None:
    """正常値を型へ変換し、未知フィールドを無視する。"""

    payload = valid_payload()
    payload["future_field"] = "ignored"

    result = MeasurementRequest.model_validate(payload)

    assert result.schema_version == 1
    assert isinstance(result.message_id, UUID)
    assert not hasattr(result, "future_field")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("message_id", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
        ("device_id", "Living Room"),
        ("temperature_c", -40.01),
        ("temperature_c", 85.01),
        ("temperature_c", "NaN"),
        ("humidity_percent", -0.01),
        ("humidity_percent", 100.01),
        ("humidity_percent", "Infinity"),
    ],
)
def test_request_schema_rejects_invalid_values(field: str, value: object) -> None:
    """形式外・範囲外・非有限の値を拒否する。"""

    payload = valid_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        MeasurementRequest.model_validate(payload)


def test_request_schema_rejects_non_utc_and_far_future_time() -> None:
    """UTC以外および5分を超える未来日時を拒否する。"""

    non_utc = valid_payload()
    non_utc["measured_at"] = "2026-08-16T12:00:00+09:00"
    future = valid_payload()
    future["measured_at"] = (datetime.now(UTC) + timedelta(minutes=6)).isoformat()

    with pytest.raises(ValidationError):
        MeasurementRequest.model_validate(non_utc)
    with pytest.raises(ValidationError):
        MeasurementRequest.model_validate(future)
