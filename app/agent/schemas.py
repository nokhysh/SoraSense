"""Agentへ公開する入力、実行履歴および出力契約を定義する。"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.query import DataStatus


class AgentSchema(BaseModel):
    """Agent境界で余分なフィールドを拒否する共通モデル。"""

    model_config = ConfigDict(extra="forbid")


class ToolErrorCode(StrEnum):
    """内部例外の詳細を公開せずに表すToolエラー。"""

    INVALID_INPUT = "INVALID_INPUT"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class ToolResult(AgentSchema):
    """すべての参照Toolが返す共通Envelope。"""

    data_status: DataStatus
    data: dict[str, Any] | None = None
    error_code: ToolErrorCode | None = None
    retryable: bool = False


class ToolCallRecord(AgentSchema):
    """意味検証の正本となる1回のTool実行履歴。"""

    index: int
    name: str
    arguments: dict[str, Any]
    result: ToolResult


class EvidenceCandidate(AgentSchema):
    """モデルが提示する、Tool結果中の値への参照。"""

    label: str
    value: Decimal | int | str
    unit: str | None = None
    observed_at: datetime | None = None
    source_call_index: int = Field(ge=1)
    source_path: str = Field(min_length=1, max_length=200)


class CalculationOperation(StrEnum):
    """Agent回答で許可する再現可能な計算種別。"""

    ABSOLUTE_DIFFERENCE = "ABSOLUTE_DIFFERENCE"
    PERCENT_CHANGE = "PERCENT_CHANGE"


class CalculationCandidate(AgentSchema):
    """Tool結果だけを入力とする表示用計算。"""

    operation: CalculationOperation
    expression: str = Field(min_length=1, max_length=300)
    result: Decimal
    operand_paths: tuple[str, str]


class AgentCandidate(AgentSchema):
    """モデル出力を検証前の候補として受け取る構造。"""

    answer: str = Field(min_length=1, max_length=8000)
    period_from: datetime | None = None
    period_to: datetime | None = None
    timezone: Literal["Asia/Tokyo"] = "Asia/Tokyo"
    evidence: tuple[EvidenceCandidate, ...] = Field(
        default=(),
        description=(
            "answer内の各測定値・件数・Tool返却済み差分値に対応する根拠。"
            "AVAILABLEの数値回答では空にしない。"
        ),
    )
    calculations: tuple[CalculationCandidate, ...] = Field(
        default=(),
        description="answer内でTool結果から新たに計算した差または増減率の根拠。",
    )
    data_status: DataStatus


class AgentUsage(AgentSchema):
    """永続化するモデル利用量。"""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class AgentRunResult(AgentSchema):
    """バックエンド実行結果と利用量。"""

    candidate: AgentCandidate
    usage: AgentUsage = Field(default_factory=AgentUsage)
