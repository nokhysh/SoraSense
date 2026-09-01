"""Gemini SDK境界のTool制限、履歴分離および利用量集計を検証する。"""

import asyncio
from datetime import datetime
from threading import get_ident
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from google.genai import interactions

from app.agent.backend import AgentTurnLimitExceeded, GeminiBackend, _parse_candidate
from app.agent.period_resolver import ResolvedPeriod
from app.agent.schemas import AgentCandidate, ToolCallRecord, ToolResult
from app.schemas.query import DataStatus


class FakeTools:
    """Geminiへ登録するToolのうち、最新値照会をDBなしで再現する。"""

    def __init__(
        self,
        *,
        allowed_tool_names: frozenset[str] = frozenset({"get_latest_measurement"}),
        resolved_periods: tuple[ResolvedPeriod, ...] = (),
    ) -> None:
        self._allowed_tool_names = allowed_tool_names
        self._resolved_periods = resolved_periods
        self.calls = 0
        self.worker_thread_id: int | None = None
        self.history: list[ToolCallRecord] = []

    @property
    def configured_device_id(self) -> str:
        """本番と同じ設定済みデバイスIDを返す。"""

        return "living-room-01"

    @property
    def allowed_tool_names(self) -> frozenset[str]:
        return self._allowed_tool_names

    @property
    def resolved_periods(self) -> tuple[ResolvedPeriod, ...]:
        return self._resolved_periods

    def get_latest_measurement(self, device_id: str) -> ToolResult:
        self.worker_thread_id = get_ident()
        self.calls += 1
        result = ToolResult(data_status=DataStatus.NO_DATA, data={"device_id": device_id})
        self.history.append(
            ToolCallRecord(
                index=self.calls,
                name="get_latest_measurement",
                arguments={"device_id": device_id},
                result=result,
            )
        )
        return result


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


def test_parse_candidate_normalizes_model_timezone_to_server_constant() -> None:
    """Flash Liteが固定値へ説明文を連結してもサーバー設定を正とする。"""

    candidate = _parse_candidate(
        AgentCandidate(
            answer="該当データなし",
            data_status=DataStatus.NO_DATA,
        )
        .model_copy(update={"timezone": "Asia/TokyoSetting error"})
        .model_dump_json()
    )

    assert candidate.timezone == "Asia/Tokyo"


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
def test_sdk_keeps_history_local_and_runs_database_tool_in_worker_thread() -> None:
    """外部保存を無効にし、同期Toolを退避して利用量を合算する。"""

    tools = FakeTools()
    client = FakeClient([function_call_response(), final_response()])
    event_loop_thread_id: int | None = None

    async def execute() -> Any:
        nonlocal event_loop_thread_id
        event_loop_thread_id = get_ident()
        with patch("app.agent.backend.genai.Client", return_value=client) as constructor:
            result = await GeminiBackend("gemini-3.6-flash", "test-key").run(
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

    assert len(client.interactions.calls) == 2
    first_call, second_call = client.interactions.calls
    assert first_call["model"] == "gemini-3.6-flash"
    assert first_call["store"] is False
    assert first_call["timeout"] == 45
    assert first_call["generation_config"] == {
        "thinking_level": "low",
        "tool_choice": {"allowed_tools": {"mode": "any"}},
    }
    assert [tool["name"] for tool in first_call["tools"]] == [
        "get_latest_measurement"
    ]
    assert first_call["response_format"]["mime_type"] == "application/json"
    assert "source_pathは必ずdata.で始め" in first_call["system_instruction"]
    assert "AVAILABLEでanswer本文に数値を1つでも記載する場合" in first_call[
        "system_instruction"
    ]
    assert "個別バケットの値を全期間の最小値" in first_call[
        "system_instruction"
    ]
    assert "質問由来の期間長を数値で繰り返さず" in first_call[
        "system_instruction"
    ]
    assert "data.temperature_c: labelは最新温度、unitは℃" in first_call[
        "system_instruction"
    ]
    assert "data.humidity_percent: labelは最新湿度、unitは%" in first_call[
        "system_instruction"
    ]
    assert "timezoneは必ずAsia/Tokyo" in first_call["system_instruction"]
    assert "period_fromとperiod_toをどちらもdata.measured_at" in first_call[
        "system_instruction"
    ]
    assert "answer本文にはdevice_id、Tool呼出し番号、source_pathを記載しない" in (
        first_call["system_instruction"]
    )
    assert "answer本文には対象期間の日付・時刻を重複記載せず" in first_call[
        "system_instruction"
    ]
    assert first_call["input"] == [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "現在値は？"}],
        }
    ]
    assert any(step["type"] == "function_call" for step in second_call["input"])
    assert any(step["type"] == "function_result" for step in second_call["input"])
    assert second_call["generation_config"] == {
        "thinking_level": "low",
        "tool_choice": "auto",
    }


def test_sdk_instructs_model_to_use_application_resolved_period() -> None:
    """Geminiへアプリが確定した半開区間を明示する。"""

    period = ResolvedPeriod(
        datetime.fromisoformat("2026-08-29T00:00:00+09:00"),
        datetime.fromisoformat("2026-08-30T00:00:00+09:00"),
    )
    tools = FakeTools(resolved_periods=(period,))
    client = FakeClient([function_call_response(), final_response()])

    async def execute() -> None:
        with patch("app.agent.backend.genai.Client", return_value=client):
            await GeminiBackend("gemini-3.6-flash", "test-key").run(
                "昨日の平均温度は？", tools  # type: ignore[arg-type]
            )

    asyncio.run(execute())

    instruction = client.interactions.calls[0]["system_instruction"]
    assert "2026-08-29T00:00:00+09:00以上" in instruction
    assert "2026-08-30T00:00:00+09:00未満" in instruction


def test_sdk_stops_after_eight_gemini_turns() -> None:
    """最終回答が返らない場合も8ターンで停止する。"""

    tools = FakeTools()
    client = FakeClient([function_call_response() for _ in range(8)])

    async def execute() -> None:
        with patch("app.agent.backend.genai.Client", return_value=client):
            await GeminiBackend("gemini-3.6-flash", "test-key").run(
                "現在値は？", tools  # type: ignore[arg-type]
            )

    with pytest.raises(AgentTurnLimitExceeded):
        asyncio.run(execute())

    assert len(client.interactions.calls) == 8
