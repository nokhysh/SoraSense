"""参照専用Toolの入力境界、状態分類および呼出し制限を検証する。"""

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.agent.schemas import ToolErrorCode
from app.agent.tools import ReadOnlyTools, ToolLimitExceeded
from app.schemas.query import DataStatus, LatestMeasurementDTO


class FakeSession(AbstractContextManager[Session]):
    """DBを使わずwith境界だけを再現する。"""

    def __enter__(self) -> Session:
        return cast(Session, object())

    def __exit__(self, *args: object) -> None:
        return None


class FakeQueryService:
    """最新値またはDB障害を返す照会サービス。"""

    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    def get_latest_measurement(self, session: Session, device_id: str) -> LatestMeasurementDTO:
        if self.unavailable:
            raise OperationalError("SELECT secret", {}, RuntimeError("db-secret"))
        return LatestMeasurementDTO(
            data_status=DataStatus.AVAILABLE,
            device_id=device_id,
            temperature_c=Decimal("24.5"),
            humidity_percent=Decimal("50.0"),
            measured_at=datetime(2026, 8, 24, tzinfo=UTC),
            received_at=datetime(2026, 8, 24, tzinfo=UTC),
        )


def make_tools(service: FakeQueryService, max_calls: int = 5) -> ReadOnlyTools:
    return ReadOnlyTools(
        cast(Any, FakeSession),
        "living-room-01",
        query_service=cast(Any, service),
        max_calls=max_calls,
    )


def test_latest_tool_returns_typed_data_and_records_normalized_history() -> None:
    tools = make_tools(FakeQueryService())

    result = tools.get_latest_measurement("living-room-01")

    assert result.data_status is DataStatus.AVAILABLE
    assert result.data is not None
    assert result.data["temperature_c"] == "24.5"
    assert tools.history[0].name == "get_latest_measurement"
    assert tools.history[0].arguments == {"device_id": "living-room-01"}


def test_tool_rejects_other_device_without_querying_database() -> None:
    tools = make_tools(FakeQueryService(unavailable=True))

    result = tools.get_latest_measurement("attacker-device")

    assert result.data_status is DataStatus.UNAVAILABLE
    assert result.error_code is ToolErrorCode.INVALID_INPUT
    assert result.retryable is False


def test_tool_converts_database_error_without_exposing_exception() -> None:
    result = make_tools(FakeQueryService(unavailable=True)).get_latest_measurement(
        "living-room-01"
    )

    assert result.data_status is DataStatus.UNAVAILABLE
    assert result.error_code is ToolErrorCode.DATA_UNAVAILABLE
    assert result.retryable is True
    assert "secret" not in result.model_dump_json()


def test_tool_stops_before_sixth_call() -> None:
    tools = make_tools(FakeQueryService(), max_calls=1)
    tools.get_latest_measurement("living-room-01")

    with pytest.raises(ToolLimitExceeded):
        tools.get_latest_measurement("living-room-01")
