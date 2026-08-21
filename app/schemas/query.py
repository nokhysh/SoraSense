"""照会サービスが返す、変更不能な型付きDTOを定義する。"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DataStatus(StrEnum):
    """照会結果を、値なしと障害を混同せず表す。"""

    AVAILABLE = "AVAILABLE"
    NO_DATA = "NO_DATA"
    UNAVAILABLE = "UNAVAILABLE"


class Granularity(StrEnum):
    """時系列集計で許可する粒度。"""

    HOUR = "hour"
    DAY = "day"


class AlertStatusFilter(StrEnum):
    """アラート履歴で許可する状態条件。"""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ALL = "ALL"


class QueryDTO(BaseModel):
    """照会DTO共通の厳格な設定。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class MetricStatistics(QueryDTO):
    """単一測定項目の期間統計。"""

    minimum: Decimal | None
    maximum: Decimal | None
    average: Decimal | None
    count: int


class LatestMeasurementDTO(QueryDTO):
    """デバイスの最新測定値。"""

    data_status: DataStatus
    device_id: str
    temperature_c: Decimal | None = None
    humidity_percent: Decimal | None = None
    measured_at: datetime | None = None
    received_at: datetime | None = None


class MeasurementStatisticsDTO(QueryDTO):
    """指定期間の温湿度統計。"""

    data_status: DataStatus
    device_id: str
    period_from: datetime
    period_to: datetime
    timezone: str
    temperature: MetricStatistics
    humidity: MetricStatistics


class SeriesPointDTO(QueryDTO):
    """Asia/Tokyo境界で集計した時系列の1点。"""

    bucket_from: datetime
    bucket_to: datetime
    temperature: MetricStatistics
    humidity: MetricStatistics


class MeasurementSeriesDTO(QueryDTO):
    """指定期間の時系列集計。"""

    data_status: DataStatus
    device_id: str
    period_from: datetime
    period_to: datetime
    timezone: str
    granularity: Granularity
    points: tuple[SeriesPointDTO, ...]


class PeriodComparisonDTO(QueryDTO):
    """2期間の統計と平均値の絶対差。"""

    data_status: DataStatus
    first: MeasurementStatisticsDTO
    second: MeasurementStatisticsDTO
    temperature_average_difference: Decimal | None
    humidity_average_difference: Decimal | None


class AlertHistoryItemDTO(QueryDTO):
    """アラート履歴の1件。"""

    id: int
    metric: str
    direction: str
    status: str
    threshold_value: Decimal
    trigger_value: Decimal
    hysteresis: Decimal
    started_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None


class AlertHistoryDTO(QueryDTO):
    """上限と切詰め情報を含むアラート履歴。"""

    data_status: DataStatus
    device_id: str
    period_from: datetime
    period_to: datetime
    timezone: str
    total_count: int
    truncated: bool
    alerts: tuple[AlertHistoryItemDTO, ...]
