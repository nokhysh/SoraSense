"""OpenAI Agents SDKを、テストで差し替え可能な小さな境界へ隔離する。"""

from typing import Any, Protocol

from starlette.concurrency import run_in_threadpool

from app.agent.schemas import AgentCandidate, AgentRunResult, AgentUsage
from app.agent.tools import ReadOnlyTools


class AgentBackend(Protocol):
    """Agentモデル実行の差し替え境界。"""

    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        """質問を処理し、構造化候補と利用量を返す。"""


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


class OpenAIAgentsBackend:
    """OpenAI Agents SDKで5種類のToolと構造化出力だけを公開する。"""

    def __init__(self, model: str, api_key: str) -> None:
        self._model = model
        self._api_key = api_key

    async def run(self, question: str, tools: ReadOnlyTools) -> AgentRunResult:
        """履歴を持ち越さず、1質問につき新しいAgent実行を開始する。"""

        from agents import Agent, Runner, function_tool
        from agents.models.openai_responses import OpenAIResponsesModel
        from openai import AsyncOpenAI

        async def get_latest_measurement(device_id: str) -> dict[str, object]:
            """設定済みデバイスの最新測定値を取得する。"""

            result = await run_in_threadpool(tools.get_latest_measurement, device_id)
            return result.model_dump(mode="json")

        async def get_measurement_statistics(
            device_id: str, period_from: str, period_to: str
        ) -> dict[str, object]:
            """指定期間の温湿度統計を取得する。日時はISO 8601で指定する。"""

            from datetime import datetime

            result = await run_in_threadpool(
                tools.get_measurement_statistics,
                device_id, datetime.fromisoformat(period_from), datetime.fromisoformat(period_to)
            )
            return result.model_dump(mode="json")

        async def get_measurement_series(
            device_id: str, period_from: str, period_to: str, granularity: str
        ) -> dict[str, object]:
            """指定期間の時系列をhourまたはday単位で取得する。"""

            from datetime import datetime

            from app.schemas.query import Granularity

            result = await run_in_threadpool(
                tools.get_measurement_series,
                device_id,
                datetime.fromisoformat(period_from),
                datetime.fromisoformat(period_to),
                Granularity(granularity),
            )
            return result.model_dump(mode="json")

        async def compare_periods(
            device_id: str,
            first_from: str,
            first_to: str,
            second_from: str,
            second_to: str,
        ) -> dict[str, object]:
            """2期間の温湿度統計を比較する。日時はISO 8601で指定する。"""

            from datetime import datetime

            result = await run_in_threadpool(
                tools.compare_periods,
                device_id,
                datetime.fromisoformat(first_from),
                datetime.fromisoformat(first_to),
                datetime.fromisoformat(second_from),
                datetime.fromisoformat(second_to),
            )
            return result.model_dump(mode="json")

        async def get_alert_history(
            device_id: str, period_from: str, period_to: str, status: str = "ALL"
        ) -> dict[str, object]:
            """指定期間のOPEN、RESOLVEDまたはALLのアラート履歴を取得する。"""

            from datetime import datetime

            from app.schemas.query import AlertStatusFilter

            result = await run_in_threadpool(
                tools.get_alert_history,
                device_id,
                datetime.fromisoformat(period_from),
                datetime.fromisoformat(period_to),
                AlertStatusFilter(status),
            )
            return result.model_dump(mode="json")

        sdk_tools: list[Any] = [
            function_tool(get_latest_measurement, failure_error_function=None),
            function_tool(get_measurement_statistics, failure_error_function=None),
            function_tool(get_measurement_series, failure_error_function=None),
            function_tool(compare_periods, failure_error_function=None),
            function_tool(get_alert_history, failure_error_function=None),
        ]
        agent = Agent(
            name="SoraSense Assistant",
            instructions=INSTRUCTIONS,
            model=OpenAIResponsesModel(
                model=self._model,
                # 再試行回数をアプリケーション側で1回に統一する。
                openai_client=AsyncOpenAI(
                    api_key=self._api_key,
                    timeout=30,
                    max_retries=0,
                ),
            ),
            tools=sdk_tools,
            output_type=AgentCandidate,
        )
        result = await Runner.run(agent, question, max_turns=8)
        candidate = result.final_output
        if not isinstance(candidate, AgentCandidate):
            candidate = AgentCandidate.model_validate(candidate)
        input_tokens = 0
        output_tokens = 0
        usage_seen = False
        for response in result.raw_responses:
            usage = getattr(response, "usage", None)
            if usage is not None:
                input_tokens += int(getattr(usage, "input_tokens", 0))
                output_tokens += int(getattr(usage, "output_tokens", 0))
                usage_seen = True
        return AgentRunResult(
            candidate=candidate,
            usage=AgentUsage(
                input_tokens=input_tokens if usage_seen else None,
                output_tokens=output_tokens if usage_seen else None,
            ),
        )
