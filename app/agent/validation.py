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
DATE_LIKE = re.compile(
    r"(?<!\d)\d{4}年\s*\d{1,2}月\s*\d{1,2}日|"
    r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)"
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
LABEL_ALIASES: dict[str, frozenset[str]] = {
    "最新温度": frozenset({"最新温度", "現在温度", "現在の温度"}),
    "最新湿度": frozenset({"最新湿度", "現在湿度", "現在の湿度"}),
    "温度最小値": frozenset({"温度最小値", "最小温度", "最低温度"}),
    "温度最大値": frozenset({"温度最大値", "最大温度", "最高温度"}),
    "温度平均値": frozenset({"温度平均値", "平均温度"}),
    "温度測定件数": frozenset({"温度測定件数", "温度件数", "測定件数"}),
    "湿度最小値": frozenset({"湿度最小値", "最小湿度", "最低湿度"}),
    "湿度最大値": frozenset({"湿度最大値", "最大湿度", "最高湿度"}),
    "湿度平均値": frozenset({"湿度平均値", "平均湿度"}),
    "湿度測定件数": frozenset({"湿度測定件数", "湿度件数", "測定件数"}),
}


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
    allowed_datetimes: set[datetime] = set()
    for item in candidate.evidence:
        record = _record(history, item.source_call_index)
        actual = _resolve(record, item.source_path)
        meaning = _meaning(record, item.source_path)
        if not _same_value(actual, item.value):
            raise AgentResponseInvalid("evidence does not match tool result")
        allowed_labels = LABEL_ALIASES.get(meaning.label, frozenset({meaning.label}))
        if item.label not in allowed_labels or item.unit != meaning.unit:
            raise AgentResponseInvalid("evidence label or unit does not match source path")
        if item.observed_at is not None:
            serialized_result = str(record.result.data).replace("Z", "+00:00")
            if item.observed_at.isoformat() not in serialized_result:
                raise AgentResponseInvalid("evidence timestamp does not match tool result")
            allowed_datetimes.add(item.observed_at)
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
        allowed_datetimes.add(candidate.period_from)
        allowed_datetimes.add(candidate.period_to)

    answer_without_datetimes = _mask_verified_datetimes(
        candidate.answer, allowed_datetimes
    )
    _validate_answer_numbers(answer_without_datetimes, allowed_any, allowed_by_unit)

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
    if record.name == "get_latest_measurement" and record.result.data is not None:
        measured_at = _datetime_or_none(record.result.data.get("measured_at"))
        return measured_at == start and measured_at == end

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


def _mask_verified_datetimes(answer: str, values: set[datetime]) -> str:
    """根拠時刻と完全一致する日時表現だけを数値検証対象から除外する。"""

    normalized = unicodedata.normalize("NFKC", answer)
    variants = {
        unicodedata.normalize("NFKC", variant)
        for value in values
        for variant in _datetime_variants(value)
    }
    for variant in sorted(variants, key=len, reverse=True):
        normalized = normalized.replace(variant, "<verified-datetime>")
    if DATE_LIKE.search(normalized):
        raise AgentResponseInvalid("answer contains an unverified datetime")
    return normalized


def _datetime_variants(value: datetime) -> set[str]:
    """UTCとAsia/Tokyoの許可済み完全日時表現を列挙する。"""

    utc_value = value.astimezone(ZoneInfo("UTC"))
    local_value = value.astimezone(DISPLAY_ZONE)
    utc_iso = utc_value.isoformat(timespec="seconds")
    local_iso = local_value.isoformat(timespec="seconds")
    return {
        utc_iso,
        utc_iso.replace("+00:00", "Z"),
        local_iso,
        f"{utc_value:%Y-%m-%d}",
        f"{local_value:%Y-%m-%d}",
        f"{utc_value.year}年{utc_value.month}月{utc_value.day}日",
        f"{utc_value:%Y年%m月%d日}",
        f"{local_value.year}年{local_value.month}月{local_value.day}日",
        f"{local_value:%Y年%m月%d日}",
        f"{utc_value.month}月{utc_value.day}日",
        f"{utc_value:%m月%d日}",
        f"{local_value.month}月{local_value.day}日",
        f"{local_value:%m月%d日}",
        *_readable_datetime_variants(utc_value),
        *_readable_datetime_variants(local_value),
    }


def _readable_datetime_variants(value: datetime) -> set[str]:
    """指定タイムゾーンの完全日時を日本語と数値表現で列挙する。"""

    dates = {
        f"{value.year}年{value.month}月{value.day}日",
        f"{value:%Y年%m月%d日}",
    }
    times = {
        f"{value.hour}時{value.minute}分{value.second}秒",
        f"{value:%H時%M分%S秒}",
        f"{value:%H:%M:%S}",
        f"{value.hour}時{value.minute}分",
        f"{value:%H時%M分}",
        f"{value:%H:%M}",
    }
    variants = {
        f"{value:%Y-%m-%d %H:%M:%S}",
        *(
            f"{date}{separator}{time}"
            for date in dates
            for time in times
            for separator in ("", " ")
        ),
    }
    variants.update(times)
    return variants
