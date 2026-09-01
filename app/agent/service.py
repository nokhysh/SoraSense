"""Agent実行、制限、根拠検証および利用量記録を1ユースケースにまとめる。"""

import asyncio
import json
import logging
from collections.abc import Callable
from time import monotonic
from uuid import UUID

from sqlalchemy.orm import Session

from app.agent.backend import AgentBackend, AgentTurnLimitExceeded
from app.agent.fallback import build_verified_fallback
from app.agent.gemini_compat import GeminiAPIConnectionError, GeminiAPIError
from app.agent.period_resolver import PeriodResolver, ResolvedPeriod
from app.agent.question_classifier import QuestionClassifier, QuestionKind, QuestionRoute
from app.agent.schemas import AgentRunResult
from app.agent.tools import ReadOnlyTools, ToolLimitExceeded
from app.agent.validation import AgentResponseInvalid, validate_and_build_display
from app.repositories.ai_request_repository import AIRequestRepository
from app.web.schemas import AgentDisplayResult

SessionFactory = Callable[[], Session]
TRANSIENT_GEMINI_STATUS_CODES = frozenset({408, 429})
AGENT_EXECUTION_TIMEOUT_SECONDS = 100
PERIOD_COUNT_BY_KIND = {
    QuestionKind.STATISTICS: 1,
    QuestionKind.SERIES: 1,
    QuestionKind.COMPARE: 2,
    QuestionKind.ALERT_HISTORY: 1,
}
logger = logging.getLogger("sorasense.agent")


class AgentUnavailable(RuntimeError):
    """Webへ内部詳細を公開せずAI利用不能を通知する。"""


class AgentService:
    """1質問ごとに独立したAgentとTool履歴を実行する。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        device_id: str,
        model: str,
        backend: AgentBackend,
        *,
        repository: AIRequestRepository | None = None,
        question_classifier: QuestionClassifier | None = None,
        period_resolver: PeriodResolver | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._device_id = device_id
        self._model = model
        self._backend = backend
        self._repository = repository or AIRequestRepository()
        self._question_classifier = question_classifier or QuestionClassifier()
        self._period_resolver = period_resolver or PeriodResolver()

    async def run(self, question: str) -> AgentDisplayResult:
        """最大100秒で実行し、検証済み回答または固定回答だけを表示する。"""

        if not 1 <= len(question) <= 2000:
            raise ValueError("question must be between 1 and 2000 characters")
        route = self._question_classifier.classify(question)
        if route.tool_name is None:
            assert route.local_answer is not None
            return AgentDisplayResult(answer=route.local_answer)
        period_count = PERIOD_COUNT_BY_KIND.get(route.kind, 0)
        resolved_periods: tuple[ResolvedPeriod, ...] = ()
        if period_count:
            resolved = self._period_resolver.resolve(
                question, expected_count=period_count
            )
            if resolved is None:
                clarification = QuestionRoute(QuestionKind.CLARIFICATION).local_answer
                assert clarification is not None
                return AgentDisplayResult(answer=clarification)
            resolved_periods = resolved
        started_at = monotonic()
        with self._session_factory() as session:
            request = self._repository.start(session, question, self._model)
        tools = ReadOnlyTools(
            self._session_factory,
            self._device_id,
            max_calls=5,
            allowed_tool_names=frozenset({route.tool_name}),
            resolved_periods=resolved_periods,
        )
        result: AgentRunResult | None = None
        try:
            result = await asyncio.wait_for(
                self._run_with_one_retry(question, tools),
                timeout=AGENT_EXECUTION_TIMEOUT_SECONDS,
            )
            display = validate_and_build_display(
                result.candidate, tools.history, self._device_id
            )
            with self._session_factory() as session:
                self._repository.succeed(
                    session,
                    request.id,
                    answer=display.answer,
                    tool_calls=len(tools.history),
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                )
            self._log_result(
                "agent.completed",
                request.id,
                result="success",
                duration_ms=self._duration_ms(started_at),
                tool_calls=len(tools.history),
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            )
            return display
        except TimeoutError as error:
            self._record_failure(
                request.id,
                "LIMIT_EXCEEDED",
                len(tools.history),
                started_at=started_at,
            )
            raise AgentUnavailable("agent execution limit exceeded") from error
        except (AgentTurnLimitExceeded, ToolLimitExceeded) as error:
            self._record_failure(
                request.id,
                "LIMIT_EXCEEDED",
                len(tools.history),
                started_at=started_at,
            )
            raise AgentUnavailable("tool call limit exceeded") from error
        except AgentResponseInvalid as error:
            assert result is not None
            try:
                display = build_verified_fallback(
                    question, tools.history, self._device_id
                )
            except Exception as fallback_error:
                self._record_failure(
                    request.id,
                    "AI_RESPONSE_INVALID",
                    len(tools.history),
                    started_at=started_at,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    validation_rule=(
                        f"{error}; fallback failed: {type(fallback_error).__name__}"
                    ),
                )
                raise AgentUnavailable("agent response was invalid") from fallback_error
            with self._session_factory() as session:
                self._repository.succeed(
                    session,
                    request.id,
                    answer=display.answer,
                    tool_calls=len(tools.history),
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                )
            self._log_result(
                "agent.completed_with_fallback",
                request.id,
                result="success",
                duration_ms=self._duration_ms(started_at),
                tool_calls=len(tools.history),
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                validation_rule=str(error),
            )
            return display
        except Exception as error:
            self._record_failure(
                request.id,
                "AI_UNAVAILABLE",
                len(tools.history),
                started_at=started_at,
            )
            raise AgentUnavailable("agent backend is unavailable") from error

    async def _run_with_one_retry(
        self, question: str, tools: ReadOnlyTools
    ) -> AgentRunResult:
        try:
            return await self._backend.run(question, tools)
        except GeminiAPIError as error:
            status_code = error.status_code
            is_transient = (
                isinstance(error, GeminiAPIConnectionError)
                or status_code in TRANSIENT_GEMINI_STATUS_CODES
                or status_code is not None
                and 500 <= status_code <= 599
            )
            if not is_transient:
                raise
            # Tool実行後の再試行は、前回結果と新しい実行を混在させるため行わない。
            if tools.history:
                raise
            return await self._backend.run(question, tools)

    def _record_failure(
        self,
        request_id: UUID,
        error_code: str,
        tool_calls: int,
        *,
        started_at: float,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        validation_rule: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            self._repository.fail(
                session,
                request_id,
                error_code=error_code,
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        self._log_result(
            "agent.failed",
            request_id,
            result="failure",
            duration_ms=self._duration_ms(started_at),
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_code=error_code,
            validation_rule=validation_rule,
        )

    def _log_result(
        self,
        event: str,
        request_id: UUID,
        *,
        result: str,
        duration_ms: int,
        tool_calls: int,
        input_tokens: int | None,
        output_tokens: int | None,
        error_code: str | None = None,
        validation_rule: str | None = None,
    ) -> None:
        """質問・回答本文を含めず、Agent終了結果を構造化ログへ出力する。"""

        log = logger.error if result == "failure" else logger.info
        log(
            json.dumps(
                {
                    "event": event,
                    "request_id": str(request_id),
                    "result": result,
                    "duration_ms": duration_ms,
                    "model": self._model,
                    "tool_calls": tool_calls,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "error_code": error_code,
                    "validation_rule": validation_rule,
                }
            )
        )

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return max(0, round((monotonic() - started_at) * 1000))
