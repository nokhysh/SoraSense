"""Gemini Developer APIを、テストで差し替え可能な小さな境界へ隔離する。"""

import json
from datetime import datetime
from typing import Any, Protocol

from google import genai
from google.genai import types
from starlette.concurrency import run_in_threadpool

from app.agent.schemas import AgentCandidate, AgentRunResult, AgentUsage, ToolResult
from app.agent.tools import ReadOnlyTools
from app.schemas.query import AlertStatusFilter, Granularity


class AgentBackend(Protocol):
    """Agentモデル実行の差し替え境界。"""

    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        """質問を処理し、構造化候補と利用量を返す。"""


class AgentTurnLimitExceeded(RuntimeError):
    """1質問のGemini呼出しターン上限を超えたことを表す。"""


def _interactions_without_sdk_retry(client: genai.Client) -> Any:
    """Interactions SDKの内部再試行を止め、呼出し回数をServiceへ一元化する。"""

    interactions_api = client.aio.interactions
    retry_config: Any = interactions_api.sdk_configuration.retry_config
    if not hasattr(retry_config, "max_retries"):
        raise RuntimeError("Gemini Interactions retry configuration is unavailable")
    # 2.20.0のInteractionsブリッジは公開設定のattempts=1を1回再試行と解釈する。
    # 固定SDKの内部構造へ依存するため、SDK更新時は回帰テストで互換性を確認する。
    retry_config.max_retries = 0
    return interactions_api


INSTRUCTIONS = """
あなたはSoraSenseの温湿度データ参照アシスタントです。
保存された温度、湿度、アラートだけを、必ず提供Toolの結果に基づいて日本語で回答してください。
単位は温度℃、湿度%です。対象期間とAsia/Tokyoを明示してください。
NO_DATAは該当データなし、UNAVAILABLEは現在取得不能として区別してください。
原因、健康影響、安全性を推測または断定してはいけません。
更新、削除、任意SQL、任意URLへのアクセス要求は実行できないと説明してください。
数値の根拠は実行したToolの呼出し番号とresult.data以下のsource_pathで示してください。
根拠のlabelとunitはsource_pathの意味に合わせ、温度は℃、湿度は%、countは件とします。
差・増減率を述べる場合はoperand_paths、operationと式をcalculationsへ含めてください。
絶対差の式はabs(second - first)、増減率は(second - first) / first * 100だけを使います。
""".strip()


TOOL_DECLARATIONS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "name": "get_latest_measurement",
        "description": "設定済みデバイスの最新測定値を取得する。",
        "parameters": {
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_measurement_statistics",
        "description": "指定期間の温湿度統計を取得する。日時はISO 8601で指定する。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "period_from": {"type": "string", "format": "date-time"},
                "period_to": {"type": "string", "format": "date-time"},
            },
            "required": ["device_id", "period_from", "period_to"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_measurement_series",
        "description": "指定期間の時系列をhourまたはday単位で取得する。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "period_from": {"type": "string", "format": "date-time"},
                "period_to": {"type": "string", "format": "date-time"},
                "granularity": {"type": "string", "enum": ["hour", "day"]},
            },
            "required": ["device_id", "period_from", "period_to", "granularity"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "compare_periods",
        "description": "2期間の温湿度統計を比較する。日時はISO 8601で指定する。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "first_from": {"type": "string", "format": "date-time"},
                "first_to": {"type": "string", "format": "date-time"},
                "second_from": {"type": "string", "format": "date-time"},
                "second_to": {"type": "string", "format": "date-time"},
            },
            "required": [
                "device_id",
                "first_from",
                "first_to",
                "second_from",
                "second_to",
            ],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_alert_history",
        "description": "指定期間のOPEN、RESOLVEDまたはALLのアラート履歴を取得する。",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "period_from": {"type": "string", "format": "date-time"},
                "period_to": {"type": "string", "format": "date-time"},
                "status": {
                    "type": "string",
                    "enum": ["OPEN", "RESOLVED", "ALL"],
                    "default": "ALL",
                },
            },
            "required": ["device_id", "period_from", "period_to"],
            "additionalProperties": False,
        },
    },
)


class GeminiBackend:
    """Gemini Interactions APIへ5種類の参照Toolと構造化出力だけを公開する。"""

    def __init__(self, model: str, api_key: str) -> None:
        self._model = model
        self._api_key = api_key

    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        """外部保存を無効にし、1質問だけのTool実行履歴をGeminiへ渡す。"""

        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        interactions_api = _interactions_without_sdk_retry(client)
        history: list[dict[str, Any]] = [
            {
                "type": "user_input",
                "content": [{"type": "text", "text": question}],
            }
        ]
        input_tokens = 0
        output_tokens = 0
        usage_seen = False
        try:
            for _ in range(8):
                interaction: Any = await interactions_api.create(
                    model=self._model,
                    input=list(history),
                    system_instruction=INSTRUCTIONS,
                    tools=list(TOOL_DECLARATIONS),
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": AgentCandidate.model_json_schema(),
                    },
                    store=False,
                    timeout=30,
                )
                usage = interaction.usage
                if usage is not None:
                    input_tokens += int(usage.total_input_tokens or 0)
                    output_tokens += int(usage.total_output_tokens or 0)
                    usage_seen = True

                steps: list[Any] = list(interaction.steps or [])
                history.extend(
                    step.model_dump(mode="json", exclude_none=True) for step in steps
                )
                function_calls = [
                    step for step in steps if getattr(step, "type", None) == "function_call"
                ]
                if not function_calls:
                    output_text = interaction.output_text
                    if not isinstance(output_text, str):
                        raise ValueError("Gemini response did not contain structured text")
                    candidate = AgentCandidate.model_validate_json(output_text)
                    return AgentRunResult(
                        candidate=candidate,
                        usage=AgentUsage(
                            input_tokens=input_tokens if usage_seen else None,
                            output_tokens=output_tokens if usage_seen else None,
                        ),
                    )

                for call in function_calls:
                    name = str(call.name)
                    result = await self._invoke_tool(name, dict(call.arguments or {}), tools)
                    history.append(
                        {
                            "type": "function_result",
                            "name": name,
                            "call_id": str(call.id),
                            "result": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        result.model_dump(mode="json"), ensure_ascii=False
                                    ),
                                }
                            ],
                        }
                    )
        finally:
            await client.aio.aclose()
            client.close()
        raise AgentTurnLimitExceeded("agent turn limit exceeded")

    async def _invoke_tool(
        self, name: str, arguments: dict[str, Any], tools: ReadOnlyTools
    ) -> ToolResult:
        """Geminiが選択した名前だけを許可し、同期DB処理をスレッドへ退避する。"""

        if name == "get_latest_measurement":
            return await run_in_threadpool(
                tools.get_latest_measurement, str(arguments["device_id"])
            )
        if name == "get_measurement_statistics":
            return await run_in_threadpool(
                tools.get_measurement_statistics,
                str(arguments["device_id"]),
                datetime.fromisoformat(str(arguments["period_from"])),
                datetime.fromisoformat(str(arguments["period_to"])),
            )
        if name == "get_measurement_series":
            return await run_in_threadpool(
                tools.get_measurement_series,
                str(arguments["device_id"]),
                datetime.fromisoformat(str(arguments["period_from"])),
                datetime.fromisoformat(str(arguments["period_to"])),
                Granularity(str(arguments["granularity"])),
            )
        if name == "compare_periods":
            return await run_in_threadpool(
                tools.compare_periods,
                str(arguments["device_id"]),
                datetime.fromisoformat(str(arguments["first_from"])),
                datetime.fromisoformat(str(arguments["first_to"])),
                datetime.fromisoformat(str(arguments["second_from"])),
                datetime.fromisoformat(str(arguments["second_to"])),
            )
        if name == "get_alert_history":
            return await run_in_threadpool(
                tools.get_alert_history,
                str(arguments["device_id"]),
                datetime.fromisoformat(str(arguments["period_from"])),
                datetime.fromisoformat(str(arguments["period_to"])),
                AlertStatusFilter(str(arguments.get("status", "ALL"))),
            )
        raise ValueError("unsupported Gemini tool call")
