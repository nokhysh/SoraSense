"""検証不能なモデル回答を、実行済みTool結果だけから安全に再構築する。"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.agent.schemas import AgentCandidate, EvidenceCandidate, ToolCallRecord
from app.agent.validation import validate_and_build_display
from app.schemas.query import DataStatus
from app.web.schemas import AgentDisplayResult

MAX_SERIES_DISPLAY_POINTS = 12
DISPLAY_ZONE = ZoneInfo("Asia/Tokyo")


def build_verified_fallback(
    question: str, history: list[ToolCallRecord], device_id: str
) -> AgentDisplayResult:
    """先頭のTool結果を正本とし、モデル生成値を使わず表示結果を作る。"""

    if not history:
        raise ValueError("fallback requires tool history")
    record = history[0]
    if record.result.data_status is not DataStatus.AVAILABLE or record.result.data is None:
        answer = (
            "該当データはありません。"
            if record.result.data_status is DataStatus.NO_DATA
            else "現在データを取得できません。"
        )
        candidate = AgentCandidate(
            answer=answer,
            period_from=_period_endpoint(record, "from"),
            period_to=_period_endpoint(record, "to"),
            data_status=record.result.data_status,
        )
        return validate_and_build_display(candidate, [record], device_id)

    builders = {
        "get_latest_measurement": _latest_candidate,
        "get_measurement_statistics": _statistics_candidate,
        "get_measurement_series": _series_candidate,
        "compare_periods": _comparison_candidate,
        "get_alert_history": _alert_candidate,
    }
    try:
        candidate = builders[record.name](question, record)
    except KeyError as error:
        raise ValueError("unsupported fallback tool") from error
    return validate_and_build_display(candidate, [record], device_id)


def _latest_candidate(question: str, record: ToolCallRecord) -> AgentCandidate:
    data = _data(record)
    evidence: list[EvidenceCandidate] = []
    answers: list[str] = []
    for metric in _metrics(question):
        key, label, unit = (
            ("temperature_c", "最新温度", "℃")
            if metric == "temperature"
            else ("humidity_percent", "最新湿度", "%")
        )
        value = data.get(key)
        if value is not None:
            evidence.append(_evidence(label, value, unit, f"data.{key}"))
            answers.append(f"{label}は{value}{unit}です。")
    if not answers:
        raise ValueError("requested latest measurement is missing")
    measured_at = _datetime(data.get("measured_at"))
    return AgentCandidate(
        answer="".join(answers),
        period_from=measured_at,
        period_to=measured_at,
        evidence=tuple(evidence),
        data_status=record.result.data_status,
    )


def _statistics_candidate(question: str, record: ToolCallRecord) -> AgentCandidate:
    data = _data(record)
    statistic, suffix, unit_override = _requested_statistic(question)
    evidence: list[EvidenceCandidate] = []
    answers: list[str] = []
    for metric in _metrics(question):
        metric_label = "温度" if metric == "temperature" else "湿度"
        unit = unit_override or ("℃" if metric == "temperature" else "%")
        value = data[metric][statistic]
        label = f"{metric_label}{suffix}"
        evidence.append(_evidence(label, value, unit, f"data.{metric}.{statistic}"))
        answers.append(f"{label}は{value}{unit}です。")
    return AgentCandidate(
        answer="".join(answers),
        period_from=_period_endpoint(record, "from"),
        period_to=_period_endpoint(record, "to"),
        evidence=tuple(evidence),
        data_status=record.result.data_status,
    )


def _series_candidate(question: str, record: ToolCallRecord) -> AgentCandidate:
    data = _data(record)
    points = data["points"]
    evidence: list[EvidenceCandidate] = []
    answers: list[str] = []
    for metric in _metrics(question):
        metric_label = "温度" if metric == "temperature" else "湿度"
        unit = "℃" if metric == "temperature" else "%"
        entries: list[str] = []
        for index in _sample_indices(len(points)):
            point = points[index]
            value = point[metric]["average"]
            observed_at = _datetime(point["bucket_from"])
            if observed_at is None:
                raise ValueError("series bucket timestamp is missing")
            evidence.append(
                _evidence(
                    f"{metric_label}平均値",
                    value,
                    unit,
                    f"data.points.{index}.{metric}.average",
                    observed_at=observed_at,
                )
            )
            entries.append(f"{observed_at.astimezone(DISPLAY_ZONE).isoformat()} {value}{unit}")
        answers.append(f"時刻別平均{metric_label}の推移は、" + "、".join(entries) + "です。")
    return AgentCandidate(
        answer="".join(answers),
        period_from=_period_endpoint(record, "from"),
        period_to=_period_endpoint(record, "to"),
        evidence=tuple(evidence),
        data_status=record.result.data_status,
    )


def _comparison_candidate(question: str, record: ToolCallRecord) -> AgentCandidate:
    data = _data(record)
    evidence: list[EvidenceCandidate] = []
    answers: list[str] = []
    for metric in _metrics(question):
        metric_label = "温度" if metric == "temperature" else "湿度"
        unit = "℃" if metric == "temperature" else "%"
        first = data["first"][metric]["average"]
        second = data["second"][metric]["average"]
        difference_key = f"{metric}_average_difference"
        difference = data[difference_key]
        evidence.extend(
            (
                _evidence(f"{metric_label}平均値", first, unit, f"data.first.{metric}.average"),
                _evidence(f"{metric_label}平均値", second, unit, f"data.second.{metric}.average"),
                _evidence(f"{metric_label}平均との差", difference, unit, f"data.{difference_key}"),
            )
        )
        answers.append(
            f"前者の平均{metric_label}は{first}{unit}、後者は{second}{unit}で、"
            f"差は{difference}{unit}です。"
        )
    return AgentCandidate(
        answer="".join(answers),
        evidence=tuple(evidence),
        data_status=record.result.data_status,
    )


def _alert_candidate(question: str, record: ToolCallRecord) -> AgentCandidate:
    data = _data(record)
    count = data["total_count"]
    return AgentCandidate(
        answer=f"アラートは{count}件です。",
        period_from=_period_endpoint(record, "from"),
        period_to=_period_endpoint(record, "to"),
        evidence=(_evidence("アラート総件数", count, "件", "data.total_count"),),
        data_status=record.result.data_status,
    )


def _metrics(question: str) -> tuple[str, ...]:
    if "温湿度" in question:
        return ("temperature", "humidity")
    has_temperature = any(word in question for word in ("温度", "気温", "室温"))
    has_humidity = "湿度" in question
    if has_temperature and has_humidity:
        return ("temperature", "humidity")
    return ("humidity",) if has_humidity else ("temperature",)


def _requested_statistic(question: str) -> tuple[str, str, str | None]:
    if any(word in question for word in ("最大", "最高", "ピーク", "高い", "暑い")):
        return "maximum", "最大値", None
    if any(word in question for word in ("最小", "最低", "低い", "寒い")):
        return "minimum", "最小値", None
    if any(word in question for word in ("件数", "何件", "回数")):
        return "count", "測定件数", "件"
    return "average", "平均値", None


def _sample_indices(point_count: int) -> tuple[int, ...]:
    """先頭と末尾を含む最大12点を重複なく等間隔で選ぶ。"""

    if point_count <= MAX_SERIES_DISPLAY_POINTS:
        return tuple(range(point_count))
    last = point_count - 1
    return tuple(
        round(index * last / (MAX_SERIES_DISPLAY_POINTS - 1))
        for index in range(MAX_SERIES_DISPLAY_POINTS)
    )


def _evidence(
    label: str,
    value: Any,
    unit: str,
    path: str,
    *,
    observed_at: datetime | None = None,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        label=label,
        value=Decimal(str(value)),
        unit=unit,
        source_call_index=1,
        source_path=path,
        observed_at=observed_at,
    )


def _data(record: ToolCallRecord) -> dict[str, Any]:
    if record.result.data is None:
        raise ValueError("tool data is missing")
    return record.result.data


def _period_endpoint(record: ToolCallRecord, side: str) -> datetime | None:
    key = f"period_{side}"
    return _datetime(record.arguments.get(key))


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None
