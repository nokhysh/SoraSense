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


GEMINI_CALL_TIMEOUT_SECONDS = 45


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
単位は温度℃、湿度%です。対象期間はperiod_from、period_to、timezoneへ設定してください。
answer本文には対象期間の日付・時刻を重複記載せず、質問で求められた測定値だけを簡潔に記載してください。
NO_DATAは該当データなし、UNAVAILABLEは現在取得不能として区別してください。
原因、健康影響、安全性を推測または断定してはいけません。
更新、削除、任意SQL、任意URLへのアクセス要求は実行できないと説明してください。
数値の根拠は実行したToolの呼出し番号と、Tool結果Envelopeを起点とするsource_pathで示してください。
AVAILABLEでanswer本文に数値を1つでも記載する場合、その数値ごとに対応するevidenceを必ず1件以上含めてください。
期間比較ではfirstとsecondの値をそれぞれevidenceへ含め、Tool結果に差分値がある場合もそのsource_pathをevidenceへ含めてください。evidenceを空にしてはいけません。
source_pathは必ずdata.で始め、result.を付けてはいけません（例: data.temperature_c）。
根拠のlabelとunitは次の対応へ完全一致させてください。
- data.temperature_c: labelは最新温度、unitは℃
- data.humidity_percent: labelは最新湿度、unitは%
timezoneは必ずAsia/Tokyoとしてください。
get_latest_measurementではperiod_fromとperiod_toをどちらもdata.measured_atと同じ時刻にしてください。
answer本文にはdevice_id、Tool呼出し番号、source_pathを記載しないでください。これらは構造化フィールドだけで示します。
その他のsource_pathはその意味に合わせ、温度は℃、湿度は%、countは件とします。
統計値のlabelは次のいずれかを使ってください。
- temperature.minimum: 温度最小値、最小温度、最低温度
- temperature.maximum: 温度最大値、最大温度、最高温度
- temperature.average: 温度平均値、平均温度
- humidity.minimum: 湿度最小値、最小湿度、最低湿度
- humidity.maximum: 湿度最大値、最大湿度、最高湿度
- humidity.average: 湿度平均値、平均湿度
差・増減率を述べる場合はoperand_paths、operationと式をcalculationsへ含めてください。
絶対差の式はabs(second - first)、増減率は(second - first) / first * 100だけを使います。
ただしcompare_periodsが返すtemperature_average_differenceまたはhumidity_average_differenceをそのまま述べる場合は、計算を作らず対応する値をevidenceで参照してください。
時系列では個別バケットの値を全期間の最小値、最大値または平均値と呼んではいけません。全点の羅列を避け、先頭・末尾や特徴的な代表バケットのaverageを使って推移を簡潔に要約し、そのpoints配列上の正確なsource_pathとbucket_fromのobserved_atを示してください。
answer本文には「24時間」「7日間」など質問由来の期間長を数値で繰り返さず、対象期間はperiod_fromとperiod_toだけで示してください。
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
    """Geminiへ質問に必要な参照Toolと構造化出力だけを公開する。"""

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
        system_instruction = (
            f"{INSTRUCTIONS}\n"
            f"Toolのdevice_idには、設定済みの{tools.configured_device_id}を必ず指定してください。"
        )
        if tools.resolved_periods:
            resolved_text = ", ".join(
                f"期間{index}: {period.start.isoformat()}以上、{period.end.isoformat()}未満"
                for index, period in enumerate(tools.resolved_periods, start=1)
            )
            system_instruction += (
                "\n質問の期間はアプリが次の値へ確定しました。"
                f"Tool引数と回答にはこの期間だけを使用してください。{resolved_text}"
            )
        tool_declarations = [
            declaration
            for declaration in TOOL_DECLARATIONS
            if declaration["name"] in tools.allowed_tool_names
        ]
        if not tool_declarations:
            raise RuntimeError("no tool is allowed for this data question")
        input_tokens = 0
        output_tokens = 0
        usage_seen = False
        tool_result_seen = False
        try:
            for _ in range(8):
                interaction: Any = await interactions_api.create(
                    model=self._model,
                    input=list(history),
                    system_instruction=system_instruction,
                    generation_config={
                        "thinking_level": "low",
                        "tool_choice": (
                            "auto"
                            if tool_result_seen
                            else {"allowed_tools": {"mode": "any"}}
                        ),
                    },
                    tools=tool_declarations,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": AgentCandidate.model_json_schema(),
                    },
                    store=False,
                    timeout=GEMINI_CALL_TIMEOUT_SECONDS,
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
                    candidate = _parse_candidate(output_text)
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
                    tool_result_seen = True
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

        if name not in tools.allowed_tool_names:
            raise ValueError("Gemini called a tool that was not exposed")
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


def _parse_candidate(output_text: str) -> AgentCandidate:
    """モデルが変形した固定タイムゾーンを境界で正規値へ戻す。"""

    values = json.loads(output_text)
    if not isinstance(values, dict):
        raise ValueError("Gemini structured response must be an object")
    # 表示タイムゾーンはサーバー設計で固定済みであり、モデルの判断対象ではない。
    values["timezone"] = "Asia/Tokyo"
    return AgentCandidate.model_validate(values)
