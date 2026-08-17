"""ヒステリシスを含む温湿度の異常状態遷移を実装する。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import AlertSettings, ThresholdSettings
from app.models.alert import Alert
from app.repositories.alert_repository import AlertRepository


class AlertService:
    """測定値からOPEN、継続、RESOLVEDおよび再発を判定する。"""

    def __init__(
        self,
        settings: AlertSettings,
        repository: AlertRepository | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository or AlertRepository()

    def evaluate(
        self,
        session: Session,
        device_id: str,
        measured_at: datetime,
        temperature: Decimal,
        humidity: Decimal,
    ) -> None:
        """2項目を評価し、状態変更を呼び出し元のSessionへ反映する。"""

        self._evaluate_metric(
            session, device_id, "TEMPERATURE", measured_at, temperature,
            self._settings.temperature,
        )
        self._evaluate_metric(
            session, device_id, "HUMIDITY", measured_at, humidity,
            self._settings.humidity,
        )

    def _evaluate_metric(
        self,
        session: Session,
        device_id: str,
        metric: str,
        measured_at: datetime,
        value: Decimal,
        thresholds: ThresholdSettings,
    ) -> None:
        """現在のOPENを解消または継続し、必要なら同じ測定で反対方向を開始する。"""

        current = self._repository.find_open(session, device_id, metric)
        if current is not None:
            if self._continues(current.direction, value, thresholds):
                current.last_detected_at = measured_at
                return
            current.status = "RESOLVED"
            current.resolved_at = measured_at

        direction = self._new_direction(value, thresholds)
        if direction is None:
            return
        threshold = thresholds.lower if direction == "LOW" else thresholds.upper
        self._repository.add(
            session,
            Alert(
                device_id=device_id,
                metric=metric,
                direction=direction,
                status="OPEN",
                threshold_value=threshold,
                trigger_value=value,
                hysteresis=thresholds.hysteresis,
                started_at=measured_at,
                last_detected_at=measured_at,
                resolved_at=None,
            ),
        )

    @staticmethod
    def _continues(direction: str, value: Decimal, thresholds: ThresholdSettings) -> bool:
        """OPEN中の異常がヒステリシスを考慮して継続するか返す。"""

        if direction == "LOW":
            return value < thresholds.lower + thresholds.hysteresis
        return value > thresholds.upper - thresholds.hysteresis

    @staticmethod
    def _new_direction(value: Decimal, thresholds: ThresholdSettings) -> str | None:
        """境界値を正常として、新しく開始すべき異常方向を返す。"""

        if value < thresholds.lower:
            return "LOW"
        if value > thresholds.upper:
            return "HIGH"
        return None
