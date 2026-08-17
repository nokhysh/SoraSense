"""異常判定の境界値、状態遷移および再発を検証する。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy.orm import Session

from app.config import AlertSettings
from app.models.alert import Alert
from app.services.alert_service import AlertService


class FakeAlertRepository:
    """DBを使わず項目ごとのOPENアラートを保持する。"""

    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def find_open(self, session: Session, device_id: str, metric: str) -> Alert | None:
        """一致するOPENアラートを返す。"""

        return next(
            (
                alert
                for alert in self.alerts
                if alert.device_id == device_id
                and alert.metric == metric
                and alert.status == "OPEN"
            ),
            None,
        )

    def add(self, session: Session, alert: Alert) -> None:
        """作成されたアラートを記録する。"""

        self.alerts.append(alert)


def evaluate_temperature(
    service: AlertService,
    measured_at: datetime,
    value: str,
) -> None:
    """湿度を正常値に固定して温度だけを評価する。"""

    service.evaluate(
        cast(Session, object()),
        "living-room-01",
        measured_at,
        Decimal(value),
        Decimal("50.0"),
    )


def test_alert_boundaries_are_normal_and_hysteresis_controls_recovery() -> None:
    """上下境界は正常とし、復帰境界まではLOWを継続する。"""

    repository = FakeAlertRepository()
    service = AlertService(AlertSettings(), cast(object, repository))
    now = datetime.now(UTC)

    evaluate_temperature(service, now, "10.0")
    evaluate_temperature(service, now + timedelta(seconds=1), "35.0")
    assert repository.alerts == []

    evaluate_temperature(service, now + timedelta(seconds=2), "9.9")
    low = repository.alerts[0]
    evaluate_temperature(service, now + timedelta(seconds=3), "10.49")
    assert low.status == "OPEN"
    assert low.last_detected_at == now + timedelta(seconds=3)

    evaluate_temperature(service, now + timedelta(seconds=4), "10.5")
    assert low.status == "RESOLVED"
    assert low.resolved_at == now + timedelta(seconds=4)


def test_alert_resolves_opens_opposite_direction_and_records_recurrence() -> None:
    """方向の直接遷移と、解消後の同方向再発を別アラートとして扱う。"""

    repository = FakeAlertRepository()
    service = AlertService(AlertSettings(), cast(object, repository))
    now = datetime.now(UTC)

    evaluate_temperature(service, now, "9.0")
    evaluate_temperature(service, now + timedelta(seconds=1), "36.0")

    low, high = repository.alerts
    assert low.status == "RESOLVED"
    assert high.status == "OPEN"
    assert high.direction == "HIGH"

    evaluate_temperature(service, now + timedelta(seconds=2), "34.5")
    evaluate_temperature(service, now + timedelta(seconds=3), "36.0")
    assert high.status == "RESOLVED"
    assert len(repository.alerts) == 3
    assert repository.alerts[-1].direction == "HIGH"
    assert repository.alerts[-1].status == "OPEN"
