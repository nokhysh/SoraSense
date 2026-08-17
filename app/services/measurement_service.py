"""測定受付のトランザクションと冪等性を管理する。

HTTP表現には依存せず、RepositoryのDB例外を呼び出し側が分類できる
アプリケーション例外へ変換する。
"""

from enum import StrEnum

from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import AlertSettings
from app.models.measurement import Measurement
from app.repositories.alert_repository import AlertRepository
from app.repositories.measurement_repository import MeasurementRepository
from app.schemas.measurement import MeasurementRequest
from app.services.alert_service import AlertService


class AcceptanceResult(StrEnum):
    """新規保存と安全な再送を区別する測定受付結果。"""

    CREATED = "created"
    ALREADY_ACCEPTED = "already_accepted"


class DatabaseUnavailableError(Exception):
    """DB接続またはトランザクションを利用できないことを示す。"""


class MeasurementPersistenceError(Exception):
    """測定の保存に失敗したことを示す。"""


class MeasurementService:
    """1つのSession境界で測定を冪等に保存する。

    事前検索で通常の再送を処理し、UNIQUE制約を同時送信競合に対する最後の
    防御層として使用する。
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        alert_settings: AlertSettings | None = None,
        repository: MeasurementRepository | None = None,
        alert_repository: AlertRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or MeasurementRepository()
        self._alert_repository = alert_repository or AlertRepository()
        self._alert_service = AlertService(
            alert_settings or AlertSettings(), self._alert_repository
        )

    def accept(self, request: MeasurementRequest) -> AcceptanceResult:
        """未登録の測定だけを保存して受付結果を返す。"""

        try:
            with self._session_factory() as session:
                try:
                    device = self._alert_repository.lock_device(session, request.device_id)
                    if device is None:
                        raise MeasurementPersistenceError("registered device was not found")
                    existing = self._repository.find_by_message_id(
                        session, request.device_id, request.message_id
                    )
                    if existing is not None:
                        return AcceptanceResult.ALREADY_ACCEPTED
                    self._repository.add(
                        session,
                        Measurement(
                            device_id=request.device_id,
                            message_id=request.message_id,
                            measured_at=request.measured_at,
                            temperature_c=request.temperature_c,
                            humidity_percent=request.humidity_percent,
                        ),
                    )
                    if (
                        device.last_alert_evaluated_at is None
                        or request.measured_at > device.last_alert_evaluated_at
                    ):
                        self._alert_service.evaluate(
                            session,
                            request.device_id,
                            request.measured_at,
                            request.temperature_c,
                            request.humidity_percent,
                        )
                        device.last_alert_evaluated_at = request.measured_at
                    session.commit()
                    return AcceptanceResult.CREATED
                except IntegrityError as error:
                    # 失敗したトランザクションでは照会できないため、先にrollbackする。
                    session.rollback()
                    # 制約名と保存済み行の両方を確認し、別の制約違反を重複扱いしない。
                    if self._is_duplicate_message(error) and self._repository.find_by_message_id(
                        session, request.device_id, request.message_id
                    ) is not None:
                        return AcceptanceResult.ALREADY_ACCEPTED
                    raise MeasurementPersistenceError from error
        except DBAPIError as error:
            raise DatabaseUnavailableError from error
        except SQLAlchemyError as error:
            raise MeasurementPersistenceError from error

    @staticmethod
    def _is_duplicate_message(error: IntegrityError) -> bool:
        """一意制約違反が測定メッセージの重複かを判定する。"""

        diagnostic = getattr(error.orig, "diag", None)
        return getattr(diagnostic, "constraint_name", None) == "uq_measurements_device_message"
