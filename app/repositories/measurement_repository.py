"""測定データに対するSQLAlchemy操作をServiceから分離する。

トランザクションの開始、commit、rollbackおよび業務上の重複判断はServiceが担当する。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.measurement import Measurement


class MeasurementRepository:
    """呼び出し元が管理するSession内で測定データを操作する。

    Repository自身はSessionを生成・終了しないため、複数のDB操作を同じ
    トランザクションへまとめられる。
    """

    def find_by_message_id(
        self, session: Session, device_id: str, message_id: UUID
    ) -> Measurement | None:
        """デバイスとメッセージIDが一致する測定を取得する。"""

        statement = select(Measurement).where(
            Measurement.device_id == device_id,
            Measurement.message_id == message_id,
        )
        return session.scalar(statement)

    def add(self, session: Session, measurement: Measurement) -> None:
        """測定を追加し、commit前にDB制約違反を検出できる状態にする。"""

        session.add(measurement)
        # flushでSQLを発行し、UNIQUE制約違反をServiceの例外分類へ渡す。
        session.flush()
