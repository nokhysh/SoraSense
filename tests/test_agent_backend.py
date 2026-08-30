"""Gemini SDK境界のTool制限、履歴分離および利用量集計を検証する。"""

import asyncio
from threading import get_ident
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from google.genai import interactions

from app.agent.backend import AgentTurnLimitExceeded, GeminiBackend
from app.agent.schemas import AgentCandidate, ToolResult
from app.agent.tools import ToolLimitExceeded
from app.schemas.query import DataStatus


class FakeTools:
    """Geminiへ登録するToolのうち、最新値照会をDBなしで再現する。"""

    def __init__(self, *, limit_after: int | None = None) -> None:
        self.limit_after = limit_after
        self.calls = 0
        self.worker_thread_id: int | None = None

    def get_latest_measurement(self, device_id: str) -> ToolResult:
        self.worker_thread_id = get_ident()
        self.calls += 1
        if self.limit_after is not None and self.calls > self.limit_after:
            raise ToolLimitExceeded("tool call limit exceeded")
        return ToolResult(data_status=DataStatus.NO_DATA, data={"device_id": device_id})


class FakeInteractions:
    """事前に用意したInteractions API応答を順番に返す。"""

    def __init__(self, responses: list[interactions.Interaction]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.sdk_configuration = SimpleNamespace(
            retry_config=SimpleNamespace(max_retries=3)
        )

    async def create(self, **values: Any) -> interactions.Interaction:
        self.calls.append(values)
        return self.responses.pop(0)


class FakeAsyncClient:
    def __init__(self, api: FakeInteractions) -> None:
        self.interactions = api
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self, responses: list[interactions.Interaction]) -> None:
        self.interactions = FakeInteractions(responses)
        self.aio = FakeAsyncClient(self.interactions)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def function_call_response(count: int = 1) -> interactions.Interaction:
    """同一Toolを指定回数要求するGemini応答を作る。"""

    return interactions.Interaction.model_validate(
        {
            "status": "requires_action",
            "steps": [
                {
                    "type": "function_call",
                    "name": "get_latest_measurement",
                    "arguments": {"device_id": "living-room-01"},
                    "id": f"call-{index}",
                }
                for index in range(count)
            ],
            "usage": {"total_input_tokens": 10, "total_output_tokens": 2},
        }
    )


def final_response() -> interactions.Interaction:
    """構造化された最終回答と利用量を返すGemini応答を作る。"""

    candidate = AgentCandidate(
        answer="該当データなし",
        data_status=DataStatus.NO_DATA,
    )
    return interactions.Interaction.model_validate(
        {
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": candidate.model_dump_json()}],
                }
            ],
            "usage": {"total_input_tokens": 20, "total_output_tokens": 5},
        }
    )


def test_sdk_propagates_sixth_tool_limit_exception() -> None:
    """6回目のTool上限例外をGemini向け結果へ変換せず、そのまま伝播する。"""

    tools = FakeTools(limit_after=5)
    client = FakeClient([function_call_response(6)])

    async def execute() -> None:
        with patch("app.agent.backend.genai.Client", return_value=client):
            await GeminiBackend("gemini-3.7-flash", "test-key").run(
                "現在値は？", tools  # type: ignore[arg-type]
            )

    with pytest.raises(ToolLimitExceeded):
        asyncio.run(execute())

    assert client.aio.closed is True
    assert client.closed is True


def test_sdk_keeps_history_local_and_runs_database_tool_in_worker_thread() -> None:
    """外部保存を無効にし、同期Toolを退避して全ターンの利用量を合算する。"""

    tools = FakeTools()
    client = FakeClient([function_call_response(), final_response()])
    event_loop_thread_id: int | None = None

    async def execute() -> Any:
        nonlocal event_loop_thread_id
        event_loop_thread_id = get_ident()
        with patch("app.agent.backend.genai.Client", return_value=client) as constructor:
            result = await GeminiBackend("gemini-3.7-flash", "test-key").run(
                "現在値は？", tools  # type: ignore[arg-type]
            )
        constructor.assert_called_once()
        constructor_options = constructor.call_args.kwargs["http_options"]
        assert constructor_options.retry_options.attempts == 1
        return result

    result = asyncio.run(execute())

    assert result.candidate.answer == "該当データなし"
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 7
    assert event_loop_thread_id is not None
    assert tools.worker_thread_id is not None
    assert tools.worker_thread_id != event_loop_thread_id
    assert client.aio.closed is True
    assert client.closed is True
    assert client.interactions.sdk_configuration.retry_config.max_retries == 0

    first_call, second_call = client.interactions.calls
    assert first_call["model"] == "gemini-3.7-flash"
    assert first_call["store"] is False
    assert first_call["timeout"] == 30
    assert len(first_call["tools"]) == 5
    assert first_call["response_format"]["mime_type"] == "application/json"
    assert first_call["input"] == [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "現在値は？"}],
        }
    ]
    assert any(step["type"] == "function_call" for step in second_call["input"])
    assert any(step["type"] == "function_result" for step in second_call["input"])


def test_sdk_stops_after_eight_gemini_turns() -> None:
    """最終回答が返らない場合も8ターンで停止し、同じモデルだけを使用する。"""

    tools = FakeTools()
    client = FakeClient([function_call_response() for _ in range(8)])

    async def execute() -> None:
        with patch("app.agent.backend.genai.Client", return_value=client):
            await GeminiBackend("gemini-3.7-flash", "test-key").run(
                "現在値は？", tools  # type: ignore[arg-type]
            )

    with pytest.raises(AgentTurnLimitExceeded):
        asyncio.run(execute())

    assert len(client.interactions.calls) == 8
    assert {call["model"] for call in client.interactions.calls} == {
        "gemini-3.7-flash"
    }
