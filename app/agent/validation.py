"""モデル候補をTool実行履歴と照合し、表示用根拠を再構築する。"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.agent.schemas import (
    AgentCandidate,
    CalculationCandidate,
    CalculationOperation,
    ToolCallRecord,
)
from app.schemas.query import DataStatus
from app.web.schemas import AgentDisplayResult

NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d+)?(?:[eE][+-]?\d+)?(?![A-Za-z0-9_])"
)
UNIT_PREFIXES = (
    ("℃", "℃"),
    ("度", "℃"),
    ("%", "%"),
    ("パーセント", "%"),
    ("件", "件"),
    ("回", "件"),
)
DISPLAY_ZONE = ZoneInfo("Asia/Tokyo")


class AgentResponseInvalid(ValueError):
    """モデル出力が実行済みToolの根拠で再現できないことを表す。"""


@dataclass(frozen=True)
class EvidenceMeaning:
    """Toolのsource pathからアプリケーションが確定する表示上の意味。"""

    label: str
    unit: str | None


def validate_and_build_display(
    candidate: AgentCandidate,
    history: list[ToolCallRecord],
    device_id: str,
) -> AgentDisplayResult:
    """構造済み候補の意味と数値を検証し、安全な表示モデルを返す。"""

    if candidate.timezone != "Asia/Tokyo" or not history:
        raise AgentResponseInvalid("timezone or tool history is invalid")

    rebuilt: list[str] = []
    evidence_records: list[ToolCallRecord] = []
    allowed_by_unit: dict[str | None, set[Decimal]] = {}
    allowed_any: set[Decimal] = set()
    for item in candidate.evidence:
        record = _record(history, item.source_call_index)
        actual = _resolve(record, item.source_path)
        meaning = _meaning(record, item.source_path)
        if not _same_value(actual, item.value):
            raise AgentResponseInvalid("evidence does not match tool result")
        if item.label != meaning.label or item.unit != meaning.unit:
            raise AgentResponseInvalid("evidence label or unit does not match source path")
        if item.observed_at is not None:
            serialized_result = str(record.result.data).replace("Z", "+00:00")
            if item.observed_at.isoformat() not in serialized_result:
                raise AgentResponseInvalid("evidence timestamp does not match tool result")
            allowed_any.update(_numbers(item.observed_at.isoformat()))
        numeric_value = _decimal_or_none(item.value)
        if numeric_value is not None:
            allowed_by_unit.setdefault(meaning.unit, set()).add(numeric_value)
            allowed_any.add(numeric_value)
        evidence_records.append(record)
        suffix = meaning.unit or ""
        rebuilt.append(f"{meaning.label}: {item.value}{suffix}")

    relevant_records = evidence_records or history
    if not any(
        record.result.data_status is candidate.data_status for record in relevant_records
    ):
        raise AgentResponseInvalid("data status is not backed by evidence tools")

    for calculation in candidate.calculations:
        result, unit = _validate_calculation(calculation, history)
        allowed_by_unit.setdefault(unit, set()).add(result)
        allowed_any.add(result)

    period = _validate_period(candidate, relevant_records)
    if candidate.period_from is not None and candidate.period_to is not None:
        allowed_any.update(_numbers(candidate.period_from.isoformat()))
        allowed_any.update(_numbers(candidate.period_to.isoformat()))

    _validate_answer_numbers(candidate.answer, allowed_any, allowed_by_unit)

    if candidate.data_status is DataStatus.NO_DATA and not rebuilt:
        rebuilt.append("該当データなし")
    return AgentDisplayResult(
        answer=candidate.answer,
        device_id=device_id,
        period=period,
        evidence=tuple(rebuilt),
    )


def _record(history: list[ToolCallRecord], index: int) -> ToolCallRecord:
    try:
        record = history[index - 1]
    except IndexError as error:
        raise AgentResponseInvalid("unknown tool call") from error
    if record.index != index:
        raise AgentResponseInvalid("tool call ordering is invalid")
    return record


def _resolve(record: ToolCallRecord, path: str) -> Any:
    value: Any = record.result.model_dump(mode="json")
    for component in path.split("."):
        if isinstance(value, dict) and component in value:
            value = value[component]
        elif isinstance(value, list) and component.isdigit():
            index = int(component)
            if index >= len(value):
                raise AgentResponseInvalid("unknown evidence path")
            value = value[index]
        else:
            raise AgentResponseInvalid("unknown evidence path")
    return value


def _meaning(record: ToolCallRecord, path: str) -> EvidenceMeaning:
    components = path.split(".")
    leaf = components[-1]
    parent = components[-2] if len(components) >= 2 else ""
    metric_names: dict[str, tuple[str, str | None]] = {
        "temperature": ("温度", "℃"),
        "humidity": ("湿度", "%"),
    }
    statistic_names = {
        "minimum": "最小値",
        "maximum": "最大値",
        "average": "平均値",
        "count": "測定件数",
    }
    if leaf == "temperature_c":
        return EvidenceMeaning("最新温度", "℃")
    if leaf == "humidity_percent":
        return EvidenceMeaning("最新湿度", "%")
    if parent in metric_names and leaf in statistic_names:
        metric_label, metric_unit = metric_names[parent]
        unit = "件" if leaf == "count" else metric_unit
        return EvidenceMeaning(f"{metric_label}{statistic_names[leaf]}", unit)
    if leaf == "temperature_average_difference":
        return EvidenceMeaning("温度平均との差", "℃")
    if leaf == "humidity_average_difference":
        return EvidenceMeaning("湿度平均との差", "%")
    if leaf == "total_count":
        return EvidenceMeaning("アラート総件数", "件")
    if leaf in {"threshold_value", "trigger_value", "hysteresis"}:
        parent_path = ".".join(components[:-1])
        metric = _resolve(record, f"{parent_path}.metric")
        metric_label, metric_unit = metric_names.get(str(metric), ("測定値", None))
        value_labels = {
            "threshold_value": "閾値",
            "trigger_value": "検出値",
            "hysteresis": "ヒステリシス",
        }
        return EvidenceMeaning(f"{metric_label}{value_labels[leaf]}", metric_unit)
    raise AgentResponseInvalid("evidence path is not displayable")


def _same_value(actual: Any, proposed: Any) -> bool:
    actual_decimal = _decimal_or_none(actual)
    proposed_decimal = _decimal_or_none(proposed)
    if actual_decimal is not None and proposed_decimal is not None:
        return actual_decimal == proposed_decimal
    return str(actual) == str(proposed)


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _validate_calculation(
    calculation: CalculationCandidate, history: list[ToolCallRecord]
) -> tuple[Decimal, str | None]:
    operands: list[Decimal] = []
    meanings: list[EvidenceMeaning] = []
    for qualified_path in calculation.operand_paths:
        call_text, separator, path = qualified_path.partition(":")
        if not separator or not call_text.isdigit():
            raise AgentResponseInvalid("invalid calculation operand")
        record = _record(history, int(call_text))
        value = _resolve(record, path)
        decimal_value = _decimal_or_none(value)
        if decimal_value is None:
            raise AgentResponseInvalid("calculation operand is not numeric")
        operands.append(decimal_value)
        meanings.append(_meaning(record, path))
    if meanings[0].unit != meanings[1].unit:
        raise AgentResponseInvalid("calculation operand units do not match")
    difference = operands[1] - operands[0]
    if calculation.operation is CalculationOperation.ABSOLUTE_DIFFERENCE:
        if calculation.expression != "abs(second - first)":
            raise AgentResponseInvalid("calculation expression does not match operation")
        expected = abs(difference)
        unit = meanings[0].unit
    elif calculation.operation is CalculationOperation.PERCENT_CHANGE:
        if calculation.expression != "(second - first) / first * 100":
            raise AgentResponseInvalid("calculation expression does not match operation")
        if operands[0] == 0:
            raise AgentResponseInvalid("division by zero")
        expected = difference / operands[0] * 100
        unit = "%"
    else:
        raise AgentResponseInvalid("calculation operation is not allowed")
    if expected.quantize(Decimal("0.01")) != calculation.result.quantize(Decimal("0.01")):
        raise AgentResponseInvalid("calculation cannot be reproduced")
    return calculation.result, unit


def _validate_period(
    candidate: AgentCandidate, relevant_records: list[ToolCallRecord]
) -> str | None:
    if candidate.period_from is None and candidate.period_to is None:
        return None
    if candidate.period_from is None or candidate.period_to is None:
        raise AgentResponseInvalid("period endpoints must be paired")
    for record in relevant_records:
        if _record_contains_period(record, candidate.period_from, candidate.period_to):
            local_start = candidate.period_from.astimezone(DISPLAY_ZONE)
            local_end = candidate.period_to.astimezone(DISPLAY_ZONE)
            return (
                f"{local_start.isoformat()}〜{local_end.isoformat()} "
                "(Asia/Tokyo)"
            )
    raise AgentResponseInvalid("period does not match one evidence tool call")


def _record_contains_period(record: ToolCallRecord, start: datetime, end: datetime) -> bool:
    pairs = (
        ("period_from", "period_to"),
        ("first_from", "first_to"),
        ("second_from", "second_to"),
    )
    for start_key, end_key in pairs:
        actual_start = _datetime_or_none(record.arguments.get(start_key))
        actual_end = _datetime_or_none(record.arguments.get(end_key))
        if actual_start == start and actual_end == end:
            return True
    return False


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _validate_answer_numbers(
    answer: str,
    allowed_any: set[Decimal],
    allowed_by_unit: dict[str | None, set[Decimal]],
) -> None:
    normalized_answer = unicodedata.normalize("NFKC", answer)
    for match in NUMBER.finditer(normalized_answer):
        value = Decimal(match.group().replace(",", ""))
        following = normalized_answer[match.end() :].lstrip()
        unit = next(
            (canonical for prefix, canonical in UNIT_PREFIXES if following.startswith(prefix)),
            None,
        )
        allowed = allowed_by_unit.get(unit, set()) if unit is not None else allowed_any
        if value not in allowed:
            raise AgentResponseInvalid("answer contains an unverified number")


def _numbers(value: str) -> set[Decimal]:
    normalized_value = unicodedata.normalize("NFKC", value)
    return {
        Decimal(match.group().replace(",", ""))
        for match in NUMBER.finditer(normalized_value)
    }
