"""デバイスロックとアラート永続化を同じトランザクションで提供する。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.device import Device


class AlertRepository:
    """異常判定に必要なデバイス状態とOPENアラートを操作する。"""

    def lock_device(self, session: Session, device_id: str) -> Device | None:
        """対象デバイス行をロックし、同一デバイスの更新を直列化する。"""

        statement = select(Device).where(Device.device_id == device_id).with_for_update()
        return session.scalar(statement)

    def find_open(self, session: Session, device_id: str, metric: str) -> Alert | None:
        """指定項目で現在OPENのアラートを取得する。"""

        statement = select(Alert).where(
            Alert.device_id == device_id,
            Alert.metric == metric,
            Alert.status == "OPEN",
        )
        return session.scalar(statement)

    def add(self, session: Session, alert: Alert) -> None:
        """新しいOPENアラートをSessionへ追加する。"""

        session.add(alert)
