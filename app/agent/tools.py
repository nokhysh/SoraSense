"""QueryServiceだけを公開する5種類の参照専用Agent Toolを実装する。"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.schemas import ToolCallRecord, ToolErrorCode, ToolResult
from app.schemas.query import AlertStatusFilter, DataStatus, Granularity
from app.services.query_service import QueryService, QueryValidationError

SessionFactory = Callable[[], Session]


class ToolLimitExceeded(RuntimeError):
    """1質問のTool呼出し上限を超えたことを表す。"""


class ReadOnlyTools:
    """検証済み条件でQueryServiceを呼び、実行履歴を保持する。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        device_id: str,
        *,
        query_service: QueryService | None = None,
        max_calls: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._device_id = device_id
        self._query_service = query_service or QueryService()
        self._max_calls = max_calls
        self.history: list[ToolCallRecord] = []

    def get_latest_measurement(self, device_id: str) -> ToolResult:
        """設定済みデバイスの最新測定値を返す。"""

        return self._execute(
            "get_latest_measurement",
            {"device_id": device_id},
            lambda session: self._query_service.get_latest_measurement(session, device_id),
        )

    def get_measurement_statistics(
        self, device_id: str, period_from: datetime, period_to: datetime
    ) -> ToolResult:
        """最大90日の温湿度統計を返す。"""

        return self._execute(
            "get_measurement_statistics",
            {"device_id": device_id, "period_from": period_from, "period_to": period_to},
            lambda session: self._query_service.get_measurement_statistics(
                session, device_id, period_from, period_to
            ),
        )

    def get_measurement_series(
        self,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
        granularity: Granularity,
    ) -> ToolResult:
        """最大500点の時系列集計を返す。"""

        return self._execute(
            "get_measurement_series",
            {
                "device_id": device_id,
                "period_from": period_from,
                "period_to": period_to,
                "granularity": granularity,
            },
            lambda session: self._query_service.get_measurement_series(
                session, device_id, period_from, period_to, granularity
            ),
        )

    def compare_periods(
        self,
        device_id: str,
        first_from: datetime,
        first_to: datetime,
        second_from: datetime,
        second_to: datetime,
    ) -> ToolResult:
        """2つの最大90日期間を比較する。"""

        arguments = {
            "device_id": device_id,
            "first_from": first_from,
            "first_to": first_to,
            "second_from": second_from,
            "second_to": second_to,
        }
        return self._execute(
            "compare_periods",
            arguments,
            lambda session: self._query_service.compare_periods(
                session,
                device_id,
                first_from,
                first_to,
                second_from,
                second_to,
            ),
        )

    def get_alert_history(
        self,
        device_id: str,
        period_from: datetime,
        period_to: datetime,
        status: AlertStatusFilter = AlertStatusFilter.ALL,
    ) -> ToolResult:
        """期間内のアラート履歴を最大100件返す。"""

        return self._execute(
            "get_alert_history",
            {
                "device_id": device_id,
                "period_from": period_from,
                "period_to": period_to,
                "status": status,
            },
            lambda session: self._query_service.get_alert_history(
                session, device_id, period_from, period_to, status
            ),
        )

    def _execute(
        self,
        name: str,
        arguments: dict[str, Any],
        operation: Callable[[Session], Any],
    ) -> ToolResult:
        if len(self.history) >= self._max_calls:
            raise ToolLimitExceeded("tool call limit exceeded")
        normalized = self._normalize(arguments)
        if arguments.get("device_id") != self._device_id:
            return self._record(
                name,
                normalized,
                ToolResult(
                    data_status=DataStatus.UNAVAILABLE,
                    error_code=ToolErrorCode.INVALID_INPUT,
                ),
            )
        try:
            with self._session_factory() as session:
                dto = operation(session)
            result = ToolResult(
                data_status=dto.data_status,
                data=dto.model_dump(mode="json"),
            )
        except QueryValidationError:
            result = ToolResult(
                data_status=DataStatus.UNAVAILABLE,
                error_code=ToolErrorCode.INVALID_INPUT,
            )
        except SQLAlchemyError:
            result = ToolResult(
                data_status=DataStatus.UNAVAILABLE,
                error_code=ToolErrorCode.DATA_UNAVAILABLE,
                retryable=True,
            )
        return self._record(name, normalized, result)

    def _record(self, name: str, arguments: dict[str, Any], result: ToolResult) -> ToolResult:
        self.history.append(
            ToolCallRecord(
                index=len(self.history) + 1,
                name=name,
                arguments=arguments,
                result=result,
            )
        )
        return result

    @staticmethod
    def _normalize(values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (
                value.isoformat()
                if isinstance(value, datetime)
                else getattr(value, "value", value)
            )
            for key, value in values.items()
        }
