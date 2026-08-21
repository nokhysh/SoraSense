"""検証済み条件だけで保存データを照会し、型付きDTOへ変換する。"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.repositories.query_repository import QueryRepository
from app.schemas.query import (
    AlertHistoryDTO,
    AlertHistoryItemDTO,
    AlertStatusFilter,
    DataStatus,
    Granularity,
    LatestMeasurementDTO,
    MeasurementSeriesDTO,
    MeasurementStatisticsDTO,
    MetricStatistics,
    PeriodComparisonDTO,
    SeriesPointDTO,
)

MAX_PERIOD = timedelta(days=90)
MAX_SERIES_POINTS = 500
MAX_ALERTS = 100
DISPLAY_QUANTUM = Decimal("0.01")
DISPLAY_TIMEZONE = "Asia/Tokyo"
DISPLAY_ZONE = ZoneInfo(DISPLAY_TIMEZONE)


class QueryValidationError(ValueError):
    """照会条件が公開契約に違反した場合に送出する。"""


class QueryService:
    """照会条件を検証し、DB表現を安全な公開DTOへ変換する。"""

    def __init__(self, repository: QueryRepository | None = None) -> None:
        self._repository = repository or QueryRepository()

    def get_latest_measurement(
        self, session: Session, device_id: str
    ) -> LatestMeasurementDTO:
        """最新値を返し、未受信をNO_DATAとして表す。"""

        row = self._repository.latest(session, device_id)
        if row is None:
            return LatestMeasurementDTO(data_status=DataStatus.NO_DATA, device_id=device_id)
        return LatestMeasurementDTO(data_status=DataStatus.AVAILABLE, **dict(row))

    def get_measurement_statistics(
        self,
        session: Session,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
    ) -> MeasurementStatisticsDTO:
        """半開区間に含まれる測定値の統計を返す。"""

        start, end = self._validate_period(period_from, period_to)
        row = self._repository.statistics(session, device_id, start, end)
        return self._statistics_dto(device_id, start, end, dict(row))

    def get_measurement_series(
        self,
        session: Session,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
        granularity: Granularity,
    ) -> MeasurementSeriesDTO:
        """Asia/Tokyo境界で集計した時系列を返す。"""

        start, end = self._validate_period(period_from, period_to)
        estimated_points = self._estimate_points(start, end, granularity)
        if estimated_points > MAX_SERIES_POINTS:
            raise QueryValidationError("the requested series exceeds 500 points")
        rows = self._repository.series(session, device_id, start, end, granularity.value)
        points_list: list[SeriesPointDTO] = []
        for row in rows:
            values = dict(row)
            points_list.append(
                SeriesPointDTO(
                    bucket_from=values["bucket_from"],
                    bucket_to=values["bucket_to"],
                    temperature=self._metric(values, "temperature"),
                    humidity=self._metric(values, "humidity"),
                )
            )
        points = tuple(points_list)
        return MeasurementSeriesDTO(
            data_status=DataStatus.AVAILABLE if points else DataStatus.NO_DATA,
            device_id=device_id,
            period_from=start,
            period_to=end,
            timezone=DISPLAY_TIMEZONE,
            granularity=granularity,
            points=points,
        )

    def compare_periods(
        self,
        session: Session,
        device_id: str,
        first_from: datetime,
        first_to: datetime,
        second_from: datetime,
        second_to: datetime,
    ) -> PeriodComparisonDTO:
        """2期間を同じ規則で集計し、平均値の絶対差を返す。"""

        first = self.get_measurement_statistics(session, device_id, first_from, first_to)
        second = self.get_measurement_statistics(session, device_id, second_from, second_to)
        return PeriodComparisonDTO(
            data_status=(
                DataStatus.AVAILABLE
                if first.data_status is DataStatus.AVAILABLE
                and second.data_status is DataStatus.AVAILABLE
                else DataStatus.NO_DATA
            ),
            first=first,
            second=second,
            temperature_average_difference=self._difference(
                first.temperature.average, second.temperature.average
            ),
            humidity_average_difference=self._difference(
                first.humidity.average, second.humidity.average
            ),
        )

    def get_alert_history(
        self,
        session: Session,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
        status: AlertStatusFilter = AlertStatusFilter.ALL,
    ) -> AlertHistoryDTO:
        """期間内のアラートを最大100件返す。"""

        start, end = self._validate_period(period_from, period_to)
        status_value = None if status is AlertStatusFilter.ALL else status.value
        total, rows = self._repository.alerts(
            session, device_id, start, end, status_value, MAX_ALERTS
        )
        alerts = tuple(AlertHistoryItemDTO(**dict(row)) for row in rows)
        return AlertHistoryDTO(
            data_status=DataStatus.AVAILABLE if alerts else DataStatus.NO_DATA,
            device_id=device_id,
            period_from=start,
            period_to=end,
            timezone=DISPLAY_TIMEZONE,
            total_count=total,
            truncated=total > len(alerts),
            alerts=alerts,
        )

    def _validate_period(
        self, period_from: datetime, period_to: datetime
    ) -> tuple[datetime, datetime]:
        """日時と期間長を検証しUTCへ正規化する。"""

        if period_from.tzinfo is None or period_to.tzinfo is None:
            raise QueryValidationError("period datetimes must include timezone information")
        start = period_from.astimezone(UTC)
        end = period_to.astimezone(UTC)
        if start >= end:
            raise QueryValidationError("period_from must be earlier than period_to")
        if end - start > MAX_PERIOD:
            raise QueryValidationError("period must not exceed 90 days")
        return start, end

    def _statistics_dto(
        self,
        device_id: str,
        start: datetime,
        end: datetime,
        row: Mapping[str, Any],
    ) -> MeasurementStatisticsDTO:
        temperature = self._metric(row, "temperature")
        humidity = self._metric(row, "humidity")
        return MeasurementStatisticsDTO(
            data_status=(DataStatus.AVAILABLE if temperature.count else DataStatus.NO_DATA),
            device_id=device_id,
            period_from=start,
            period_to=end,
            timezone=DISPLAY_TIMEZONE,
            temperature=temperature,
            humidity=humidity,
        )

    @staticmethod
    def _metric(row: Mapping[str, Any], prefix: str) -> MetricStatistics:
        count = int(row[f"{prefix}_count"])
        return MetricStatistics(
            minimum=row[f"{prefix}_minimum"],
            maximum=row[f"{prefix}_maximum"],
            average=QueryService._round(row[f"{prefix}_average"]),
            count=count,
        )

    @staticmethod
    def _round(value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(DISPLAY_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _difference(first: Decimal | None, second: Decimal | None) -> Decimal | None:
        if first is None or second is None:
            return None
        return QueryService._round(abs(second - first))

    @staticmethod
    def _estimate_points(start: datetime, end: datetime, granularity: Granularity) -> int:
        """東京時間で対象期間が触れるバケット数を返す。"""

        local_start = start.astimezone(DISPLAY_ZONE)
        local_end = end.astimezone(DISPLAY_ZONE)
        if granularity is Granularity.HOUR:
            bucket_start = local_start.replace(minute=0, second=0, microsecond=0)
            return ceil((local_end - bucket_start).total_seconds() / 3600)
        bucket_start = local_start.replace(hour=0, minute=0, second=0, microsecond=0)
        return ceil((local_end - bucket_start).total_seconds() / 86400)
