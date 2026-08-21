"""QueryServiceの期間検証、集計規則およびDTO変換を検証する。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from inspect import signature
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from app.schemas.query import DataStatus, Granularity
from app.services.query_service import QueryService, QueryValidationError


class FakeQueryRepository:
    """照会条件を記録し、固定した集計結果を返す。"""

    def __init__(self, count: int = 1) -> None:
        self.count = count
        self.statistics_arguments: list[tuple[datetime, datetime]] = []

    def latest(self, session: Session, device_id: str) -> None:
        return None

    def statistics(
        self, session: Session, device_id: str, period_from: datetime, period_to: datetime
    ) -> dict[str, Any]:
        self.statistics_arguments.append((period_from, period_to))
        return {
            "temperature_minimum": Decimal("20.00") if self.count else None,
            "temperature_maximum": Decimal("25.00") if self.count else None,
            "temperature_average": Decimal("22.345") if self.count else None,
            "temperature_count": self.count,
            "humidity_minimum": Decimal("40.00") if self.count else None,
            "humidity_maximum": Decimal("55.00") if self.count else None,
            "humidity_average": Decimal("47.555") if self.count else None,
            "humidity_count": self.count,
        }

    def series(
        self,
        session: Session,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
        granularity: str,
    ) -> list[dict[str, Any]]:
        return []

    def alerts(
        self,
        session: Session,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
        status: str | None,
        limit: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        return 0, []


def make_service(repository: FakeQueryRepository) -> QueryService:
    """テスト用Repositoryを型境界越しに注入する。"""

    return QueryService(cast(Any, repository))


def test_statistics_normalizes_utc_rounds_at_dto_boundary_and_keeps_half_open_period() -> None:
    """TZ付き期間をUTCへ変換し、平均だけDTO境界で丸める。"""

    repository = FakeQueryRepository()
    service = make_service(repository)
    start = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)

    result = service.get_measurement_statistics(
        cast(Session, object()), "living-room-01", start, end
    )

    assert repository.statistics_arguments == [(start, end)]
    assert result.data_status is DataStatus.AVAILABLE
    assert result.timezone == "Asia/Tokyo"
    assert result.temperature.average == Decimal("22.35")
    assert result.humidity.average == Decimal("47.56")


def test_statistics_distinguishes_no_data_from_zero() -> None:
    """0件では数値集計をNULLのまま返し、測定値0と混同しない。"""

    service = make_service(FakeQueryRepository(count=0))
    start = datetime(2026, 8, 18, tzinfo=UTC)
    result = service.get_measurement_statistics(
        cast(Session, object()),
        "living-room-01",
        start,
        start + timedelta(hours=1),
    )

    assert result.data_status is DataStatus.NO_DATA
    assert result.temperature.count == 0
    assert result.temperature.average is None


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 8, 18), datetime(2026, 8, 19)),
        (datetime(2026, 8, 19, tzinfo=UTC), datetime(2026, 8, 18, tzinfo=UTC)),
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 4, 2, tzinfo=UTC),
        ),
    ],
)
def test_invalid_periods_are_rejected(start: datetime, end: datetime) -> None:
    """naive日時、逆転および90日超を拒否する。"""

    with pytest.raises(QueryValidationError):
        make_service(FakeQueryRepository()).get_measurement_statistics(
            cast(Session, object()), "living-room-01", start, end
        )


def test_query_methods_do_not_accept_timezone_input() -> None:
    """利用者が表示・集計タイムゾーンを変更できない。"""

    assert "timezone" not in signature(QueryService.get_measurement_statistics).parameters
    assert "timezone" not in signature(QueryService.get_measurement_series).parameters
    assert "timezone" not in signature(QueryService.compare_periods).parameters
    assert "timezone" not in signature(QueryService.get_alert_history).parameters


def test_series_rejects_more_than_500_points_instead_of_truncating() -> None:
    """過大な時系列指定を自動切詰めせず拒否する。"""

    start = datetime(2026, 8, 1, tzinfo=UTC)
    with pytest.raises(QueryValidationError, match="500"):
        make_service(FakeQueryRepository()).get_measurement_series(
            cast(Session, object()),
            "living-room-01",
            start,
            start + timedelta(days=30),
            Granularity.HOUR,
        )
