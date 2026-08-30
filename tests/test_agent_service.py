"""Agentユースケースの記録、再試行および検証失敗を確認する。"""

import asyncio
import json
from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from google.genai._gaos.lib.compat_errors import APIConnectionError, APIError
from sqlalchemy.orm import Session

from app.agent.schemas import (
    AgentCandidate,
    AgentRunResult,
    AgentUsage,
    EvidenceCandidate,
    ToolResult,
)
from app.agent.service import AgentService, AgentUnavailable
from app.agent.tools import ReadOnlyTools, ToolLimitExceeded
from app.schemas.query import DataStatus


class FakeSession(AbstractContextManager[Session]):
    def __enter__(self) -> Session:
        return cast(Session, object())

    def __exit__(self, *args: object) -> None:
        return None


class RequestRow:
    def __init__(self) -> None:
        self.id = uuid4()


class FakeRequestRepository:
    """永続化引数をメモリへ記録する。"""

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.succeeded: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []

    def start(self, session: Session, question: str, model: str) -> RequestRow:
        self.started.append((question, model))
        return RequestRow()

    def succeed(self, session: Session, request_id: UUID, **values: Any) -> None:
        self.succeeded.append(values)

    def fail(self, session: Session, request_id: UUID, **values: Any) -> None:
        self.failed.append(values)


class FakeBackend:
    """Toolを1回呼び、固定した構造化回答を返す。"""

    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        tools._record(
            "get_latest_measurement",
            {"device_id": "living-room-01"},
            ToolResult(
                data_status=DataStatus.AVAILABLE,
                data={"temperature_c": "24.5"},
            ),
        )
        return AgentRunResult(
            candidate=AgentCandidate(
                answer="最新温度は24.5℃です。",
                data_status=DataStatus.AVAILABLE,
                evidence=(
                    EvidenceCandidate(
                        label="最新温度",
                        value=Decimal("24.5"),
                        unit="℃",
                        source_call_index=1,
                        source_path="data.temperature_c",
                    ),
                ),
            ),
            usage=AgentUsage(input_tokens=10, output_tokens=20),
        )


def test_service_stores_only_validated_answer_and_usage(caplog: Any) -> None:
    repository = FakeRequestRepository()
    service = AgentService(
        cast(Any, FakeSession),
        "living-room-01",
        "fake-model",
        FakeBackend(),
        repository=cast(Any, repository),
    )

    with caplog.at_level("INFO", logger="sorasense.agent"):
        result = asyncio.run(service.run("現在値は？"))

    assert result.answer == "最新温度は24.5℃です。"
    assert repository.started == [("現在値は？", "fake-model")]
    assert repository.succeeded == [
        {
            "answer": "最新温度は24.5℃です。",
            "tool_calls": 1,
            "input_tokens": 10,
            "output_tokens": 20,
        }
    ]
    assert repository.failed == []
    completed = json.loads(caplog.records[-1].message)
    assert completed == {
        "event": "agent.completed",
        "request_id": completed["request_id"],
        "result": "success",
        "duration_ms": completed["duration_ms"],
        "model": "fake-model",
        "tool_calls": 1,
        "input_tokens": 10,
        "output_tokens": 20,
        "error_code": None,
    }
    assert completed["duration_ms"] >= 0
    assert "現在値" not in caplog.text


class InvalidBackend(FakeBackend):
    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        result = await super().run(question, tools)
        return result.model_copy(
            update={
                "candidate": result.candidate.model_copy(
                    update={"answer": "根拠のない99℃です。"}
                )
            }
        )


def test_service_records_invalid_output_without_answer(caplog: Any) -> None:
    repository = FakeRequestRepository()
    service = AgentService(
        cast(Any, FakeSession),
        "living-room-01",
        "fake-model",
        InvalidBackend(),
        repository=cast(Any, repository),
    )

    with (
        caplog.at_level("INFO", logger="sorasense.agent"),
        pytest.raises(AgentUnavailable),
    ):
        asyncio.run(service.run("現在値は？"))

    assert repository.succeeded == []
    assert repository.failed[0]["error_code"] == "AI_RESPONSE_INVALID"
    assert repository.failed[0]["input_tokens"] == 10
    assert repository.failed[0]["output_tokens"] == 20
    failed = json.loads(caplog.records[-1].message)
    assert failed["event"] == "agent.failed"
    assert failed["result"] == "failure"
    assert failed["error_code"] == "AI_RESPONSE_INVALID"
    assert failed["tool_calls"] == 1
    assert failed["input_tokens"] == 10
    assert failed["output_tokens"] == 20
    assert "現在値" not in caplog.text


class LimitBackend:
    """SDK境界から伝播したTool上限を再現する。"""

    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        raise ToolLimitExceeded("tool call limit exceeded")


def test_service_records_propagated_tool_limit() -> None:
    """Tool上限をAI一般障害ではなくLIMIT_EXCEEDEDとして記録する。"""

    repository = FakeRequestRepository()
    service = AgentService(
        cast(Any, FakeSession),
        "living-room-01",
        "fake-model",
        LimitBackend(),
        repository=cast(Any, repository),
    )

    with pytest.raises(AgentUnavailable, match="tool call limit"):
        asyncio.run(service.run("現在値は？"))

    assert repository.failed[0]["error_code"] == "LIMIT_EXCEEDED"


class RetryBackend(FakeBackend):
    """1回目だけ指定例外を送出し、呼出し回数を記録する。"""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return await super().run(question, tools)


def gemini_status_error(status_code: int) -> APIError:
    """Interactions APIが返す実際の例外階層でHTTPエラーを作る。"""

    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/interactions")
    response = httpx.Response(status_code, request=request)
    return APIError.generate(
        status_code,
        {"error": {"message": "Gemini request failed"}},
        None,
        response,
    )


@pytest.mark.parametrize("status_code", [408, 429, 500, 501, 502, 503, 504, 599])
def test_service_retries_transient_gemini_error_once(status_code: int) -> None:
    """Interactions APIの一時ステータスエラーだけを1回再試行する。"""

    repository = FakeRequestRepository()
    backend = RetryBackend(gemini_status_error(status_code))
    service = AgentService(
        cast(Any, FakeSession),
        "living-room-01",
        "fake-model",
        backend,
        repository=cast(Any, repository),
    )

    result = asyncio.run(service.run("現在値は？"))

    assert result.answer == "最新温度は24.5℃です。"
    assert backend.calls == 2


def test_service_retries_interactions_connection_error_once() -> None:
    """Interactions APIが変換した接続エラーも1回再試行する。"""

    repository = FakeRequestRepository()
    request = httpx.Request(
        "POST", "https://generativelanguage.googleapis.com/interactions"
    )
    backend = RetryBackend(APIConnectionError(request=request))
    service = AgentService(
        cast(Any, FakeSession),
        "living-room-01",
        "fake-model",
        backend,
        repository=cast(Any, repository),
    )

    result = asyncio.run(service.run("現在値は？"))

    assert result.answer == "最新温度は24.5℃です。"
    assert backend.calls == 2


class PermanentFailureBackend:
    """認証エラーを返し、呼出し回数を記録する。"""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.calls = 0

    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        self.calls += 1
        raise gemini_status_error(self.status_code)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 422])
def test_service_does_not_retry_permanent_gemini_error(status_code: int) -> None:
    """認証失敗などの恒久エラーではGeminiを再呼出ししない。"""

    repository = FakeRequestRepository()
    backend = PermanentFailureBackend(status_code)
    service = AgentService(
        cast(Any, FakeSession),
        "living-room-01",
        "fake-model",
        backend,
        repository=cast(Any, repository),
    )

    with pytest.raises(AgentUnavailable):
        asyncio.run(service.run("現在値は？"))

    assert backend.calls == 1
    assert repository.failed[0]["error_code"] == "AI_UNAVAILABLE"
