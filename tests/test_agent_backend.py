"""OpenAI Agents SDK境界のTool例外伝播とスレッド分離を検証する。"""

import asyncio
import json
from threading import get_ident
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.agent.backend import OpenAIAgentsBackend
from app.agent.schemas import AgentCandidate, ToolResult
from app.agent.tools import ToolLimitExceeded
from app.schemas.query import DataStatus


class FakeTools:
    """SDKが登録する5種類のToolをDBなしで再現する。"""

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

    get_measurement_statistics = get_latest_measurement
    get_measurement_series = get_latest_measurement
    compare_periods = get_latest_measurement
    get_alert_history = get_latest_measurement


def test_sdk_propagates_sixth_tool_limit_exception() -> None:
    """SDK既定ハンドラで上限例外を文字列化せず、実行を停止する。"""

    tools = FakeTools(limit_after=5)

    async def fake_run(agent: Any, question: str, max_turns: int) -> Any:
        for _ in range(6):
            await agent.tools[0].on_invoke_tool(
                None, json.dumps({"device_id": "living-room-01"})
            )
        raise AssertionError("sixth tool call must stop the runner")

    async def execute() -> None:
        with patch("agents.Runner.run", new=fake_run):
            await OpenAIAgentsBackend("gpt-5-mini", "test-key").run(
                "現在値は？", tools  # type: ignore[arg-type]
            )

    with pytest.raises(ToolLimitExceeded):
        asyncio.run(execute())


def test_sdk_runs_synchronous_database_tool_outside_event_loop_thread() -> None:
    """同期QueryService呼出しがイベントループのスレッドを占有しない。"""

    tools = FakeTools()
    event_loop_thread_id: int | None = None

    async def fake_run(agent: Any, question: str, max_turns: int) -> Any:
        nonlocal event_loop_thread_id
        event_loop_thread_id = get_ident()
        assert agent.model._client.timeout == 30
        assert agent.model._client.max_retries == 0
        await agent.tools[0].on_invoke_tool(
            None, json.dumps({"device_id": "living-room-01"})
        )
        return SimpleNamespace(
            final_output=AgentCandidate(
                answer="該当データなし",
                data_status=DataStatus.NO_DATA,
            ),
            raw_responses=[],
        )

    async def execute() -> None:
        with patch("agents.Runner.run", new=fake_run):
            await OpenAIAgentsBackend("gpt-5-mini", "test-key").run(
                "現在値は？", tools  # type: ignore[arg-type]
            )

    asyncio.run(execute())

    assert event_loop_thread_id is not None
    assert tools.worker_thread_id is not None
    assert tools.worker_thread_id != event_loop_thread_id
