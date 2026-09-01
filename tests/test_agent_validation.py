"""Agent候補の根拠・数値・期間をTool履歴と照合する。"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.agent.schemas import (
    AgentCandidate,
    CalculationCandidate,
    CalculationOperation,
    EvidenceCandidate,
    ToolCallRecord,
    ToolResult,
)
from app.agent.validation import AgentResponseInvalid, validate_and_build_display
from app.schemas.query import DataStatus


def history() -> list[ToolCallRecord]:
    """最新測定値Toolの固定履歴を返す。"""

    return [
        ToolCallRecord(
            index=1,
            name="get_latest_measurement",
            arguments={"device_id": "living-room-01"},
            result=ToolResult(
                data_status=DataStatus.AVAILABLE,
                data={
                    "device_id": "living-room-01",
                    "temperature_c": "24.5",
                    "humidity_percent": "50.0",
                    "measured_at": "2026-08-24T00:00:00Z",
                },
            ),
        )
    ]


def candidate(value: Decimal = Decimal("24.5")) -> AgentCandidate:
    """最新温度を回答するモデル候補を返す。"""

    return AgentCandidate(
        answer=f"最新温度は{value}℃です。",
        timezone="Asia/Tokyo",
        data_status=DataStatus.AVAILABLE,
        evidence=(
            EvidenceCandidate(
                label="最新温度",
                value=value,
                unit="℃",
                observed_at=datetime(2026, 8, 24, tzinfo=UTC),
                source_call_index=1,
                source_path="data.temperature_c",
            ),
        ),
    )


def test_valid_candidate_rebuilds_evidence_from_tool_history() -> None:
    result = validate_and_build_display(candidate(), history(), "living-room-01")

    assert result.answer == "最新温度は24.5℃です。"
    assert result.evidence == ("最新温度: 24.5℃",)


def test_answer_rejects_value_from_different_meaning_in_same_tool_result() -> None:
    """同じTool内でも最高温度へ最低温度の値を流用させない。"""

    record = ToolCallRecord(
        index=1,
        name="get_measurement_statistics",
        arguments={
            "device_id": "living-room-01",
            "period_from": "2026-08-24T00:00:00Z",
            "period_to": "2026-08-25T00:00:00Z",
        },
        result=ToolResult(
            data_status=DataStatus.AVAILABLE,
            data={
                "temperature": {"minimum": "10.0", "maximum": "30.0"},
                "humidity": {"minimum": "40.0", "maximum": "60.0"},
            },
        ),
    )
    invalid = AgentCandidate(
        answer="最高温度は10.0℃です。",
        data_status=DataStatus.AVAILABLE,
        evidence=(
            EvidenceCandidate(
                label="最高温度",
                value=Decimal("30.0"),
                unit="℃",
                source_call_index=1,
                source_path="data.temperature.maximum",
            ),
        ),
    )

    with pytest.raises(AgentResponseInvalid, match="unverified number"):
        validate_and_build_display(invalid, [record], "living-room-01")


def test_latest_measurement_period_matches_measured_at() -> None:
    """最新値の測定時刻を一点の対象期間として表示する。"""

    measured_at = datetime(2026, 8, 24, tzinfo=UTC)
    valid = candidate().model_copy(
        update={"period_from": measured_at, "period_to": measured_at}
    )

    result = validate_and_build_display(valid, history(), "living-room-01")

    assert result.period == (
        "2026-08-24T09:00:00+09:00〜2026-08-24T09:00:00+09:00 (Asia/Tokyo)"
    )


def test_answer_allows_observed_at_rendered_in_asia_tokyo() -> None:
    """UTCの測定日時を東京時間へ変換した年月日時分秒を許可する。"""

    measured_at = datetime(2026, 8, 24, tzinfo=UTC)
    valid = candidate().model_copy(
        update={
            "answer": "対象日時は2026年8月24日9時0分0秒、最新温度は24.5℃です。",
            "period_from": measured_at,
            "period_to": measured_at,
        }
    )

    result = validate_and_build_display(valid, history(), "living-room-01")

    assert result.answer.startswith("対象日時は2026年8月24日9時0分0秒")


def test_answer_allows_complete_utc_datetime_in_japanese_format() -> None:
    """UTCの完全日時をゼロ埋めした日本語表現でも許可する。"""

    measured_at = datetime(2026, 8, 24, tzinfo=UTC)
    valid = candidate().model_copy(
        update={
            "answer": "対象日時は2026年08月24日 00:00:00、最新温度は24.5℃です。",
            "period_from": measured_at,
            "period_to": measured_at,
        }
    )

    result = validate_and_build_display(valid, history(), "living-room-01")

    assert result.answer.startswith("対象日時は2026年08月24日 00:00:00")


def test_answer_allows_complete_local_date_from_evidence_datetime() -> None:
    """根拠日時の東京日付と完全一致する日付全体を許可する。"""

    measured_at = datetime(2026, 8, 24, tzinfo=UTC)
    valid = candidate().model_copy(
        update={
            "answer": "対象日は2026年8月24日、最新温度は24.5℃です。",
            "period_from": measured_at,
            "period_to": measured_at,
        }
    )

    result = validate_and_build_display(valid, history(), "living-room-01")

    assert result.answer.startswith("対象日は2026年8月24日")


def test_answer_allows_complete_local_month_and_day() -> None:
    """根拠日時の東京月日と完全一致する省略日付全体を許可する。"""

    measured_at = datetime(2026, 8, 24, tzinfo=UTC)
    valid = candidate().model_copy(
        update={
            "answer": "対象日は8月24日、最新温度は24.5℃です。",
            "period_from": measured_at,
            "period_to": measured_at,
        }
    )

    result = validate_and_build_display(valid, history(), "living-room-01")

    assert result.answer.startswith("対象日は8月24日")


def test_answer_allows_complete_hour_and_minute_from_period() -> None:
    """根拠期間と完全一致する時分表現を一体として許可する。"""

    measured_at = datetime(2026, 8, 24, tzinfo=UTC)
    valid = candidate().model_copy(
        update={
            "answer": "対象時刻は09:00、最新温度は24.5℃です。",
            "period_from": measured_at,
            "period_to": measured_at,
        }
    )

    result = validate_and_build_display(valid, history(), "living-room-01")

    assert result.answer.startswith("対象時刻は09:00")


def test_answer_rejects_recombined_datetime_components() -> None:
    """根拠日時の構成要素を別の位置へ流用した存在しない日時を拒否する。"""

    measured_at = datetime(2026, 8, 24, tzinfo=UTC)
    invalid = candidate().model_copy(
        update={
            "answer": "対象日時は2026年9月24日9時0分0秒、最新温度は24.5℃です。",
            "period_from": measured_at,
            "period_to": measured_at,
        }
    )

    with pytest.raises(AgentResponseInvalid, match="unverified datetime"):
        validate_and_build_display(invalid, history(), "living-room-01")


def test_value_not_in_tool_result_is_rejected() -> None:
    with pytest.raises(AgentResponseInvalid, match="evidence"):
        validate_and_build_display(candidate(Decimal("99.9")), history(), "living-room-01")


def test_unverified_number_in_answer_is_rejected() -> None:
    invalid = candidate().model_copy(update={"answer": "最新温度は24.5℃、予測は30℃です。"})

    with pytest.raises(AgentResponseInvalid, match="unverified number"):
        validate_and_build_display(invalid, history(), "living-room-01")


@pytest.mark.parametrize(
    "answer",
    ["温度は99度です。", "測定件数は999回です。", "温度は９９℃です。", "温度は9.9e1℃です。"],
)
def test_unverified_number_with_alternate_unit_is_rejected(answer: str) -> None:
    """単位表記を変えても根拠にない数値を許可しない。"""

    invalid = candidate().model_copy(update={"answer": answer})

    with pytest.raises(AgentResponseInvalid, match="unverified number"):
        validate_and_build_display(invalid, history(), "living-room-01")


@pytest.mark.parametrize(
    ("label", "unit"),
    [("最新湿度", "℃"), ("最新温度", "%")],
)
def test_evidence_label_and_unit_must_match_source_path(label: str, unit: str) -> None:
    """温度値を湿度名や%単位へ置換した根拠を拒否する。"""

    evidence = candidate().evidence[0].model_copy(update={"label": label, "unit": unit})
    invalid = candidate().model_copy(update={"evidence": (evidence,)})

    with pytest.raises(AgentResponseInvalid, match="label or unit"):
        validate_and_build_display(invalid, history(), "living-room-01")


def test_statistics_synonym_is_accepted_and_rebuilt_with_canonical_label() -> None:
    """自然な最高温度を許可し、表示根拠は正規ラベルへ戻す。"""

    records = [
        ToolCallRecord(
            index=1,
            name="get_measurement_statistics",
            arguments={"device_id": "living-room-01"},
            result=ToolResult(
                data_status=DataStatus.AVAILABLE,
                data={"temperature": {"maximum": "25.0"}},
            ),
        )
    ]
    valid = AgentCandidate(
        answer="最高温度は25.0℃です。",
        timezone="Asia/Tokyo",
        data_status=DataStatus.AVAILABLE,
        evidence=(
            EvidenceCandidate(
                label="最高温度",
                value=Decimal("25.0"),
                unit="℃",
                source_call_index=1,
                source_path="data.temperature.maximum",
            ),
        ),
    )

    result = validate_and_build_display(valid, records, "living-room-01")

    assert result.evidence == ("温度最大値: 25.0℃",)


def test_statistics_synonym_for_other_metric_is_rejected() -> None:
    """温度の参照先を最高湿度というラベルへ置換できない。"""

    records = [
        ToolCallRecord(
            index=1,
            name="get_measurement_statistics",
            arguments={"device_id": "living-room-01"},
            result=ToolResult(
                data_status=DataStatus.AVAILABLE,
                data={"temperature": {"maximum": "25.0"}},
            ),
        )
    ]
    invalid = AgentCandidate(
        answer="最高温度は25.0℃です。",
        timezone="Asia/Tokyo",
        data_status=DataStatus.AVAILABLE,
        evidence=(
            EvidenceCandidate(
                label="最高湿度",
                value=Decimal("25.0"),
                unit="℃",
                source_call_index=1,
                source_path="data.temperature.maximum",
            ),
        ),
    )

    with pytest.raises(AgentResponseInvalid, match="label or unit"):
        validate_and_build_display(invalid, records, "living-room-01")


def test_series_and_alert_array_paths_are_resolved() -> None:
    """時系列点とアラート配列内の値を根拠として再構築する。"""

    records = [
        ToolCallRecord(
            index=1,
            name="get_measurement_series",
            arguments={"device_id": "living-room-01"},
            result=ToolResult(
                data_status=DataStatus.AVAILABLE,
                data={"points": [{"temperature": {"average": "22.5"}}]},
            ),
        ),
        ToolCallRecord(
            index=2,
            name="get_alert_history",
            arguments={"device_id": "living-room-01"},
            result=ToolResult(
                data_status=DataStatus.AVAILABLE,
                data={"alerts": [{"metric": "humidity", "trigger_value": "75.0"}]},
            ),
        ),
    ]
    valid = AgentCandidate(
        answer="平均温度は22.5℃、湿度検出値は75.0%です。",
        data_status=DataStatus.AVAILABLE,
        evidence=(
            EvidenceCandidate(
                label="温度平均値",
                value=Decimal("22.5"),
                unit="℃",
                source_call_index=1,
                source_path="data.points.0.temperature.average",
            ),
            EvidenceCandidate(
                label="湿度検出値",
                value=Decimal("75.0"),
                unit="%",
                source_call_index=2,
                source_path="data.alerts.0.trigger_value",
            ),
        ),
    )

    result = validate_and_build_display(valid, records, "living-room-01")

    assert result.evidence == ("温度平均値: 22.5℃", "湿度検出値: 75.0%")


def test_calculation_expression_must_match_structured_operation() -> None:
    """合計など未許可の式を絶対差として解釈しない。"""

    records = [
        ToolCallRecord(
            index=1,
            name="compare_periods",
            arguments={"device_id": "living-room-01"},
            result=ToolResult(
                data_status=DataStatus.AVAILABLE,
                data={
                    "first": {"temperature": {"average": "10"}},
                    "second": {"temperature": {"average": "20"}},
                },
            ),
        )
    ]
    invalid = AgentCandidate(
        answer="差は10℃です。",
        data_status=DataStatus.AVAILABLE,
        calculations=(
            CalculationCandidate(
                operation=CalculationOperation.ABSOLUTE_DIFFERENCE,
                expression="合計",
                result=Decimal("10"),
                operand_paths=(
                    "1:data.first.temperature.average",
                    "1:data.second.temperature.average",
                ),
            ),
        ),
    )

    with pytest.raises(AgentResponseInvalid, match="expression"):
        validate_and_build_display(invalid, records, "living-room-01")


def test_period_endpoints_must_come_from_same_evidence_tool_call() -> None:
    """別々のTool引数を継ぎ合わせた未照会期間を拒否する。"""

    first = datetime(2026, 8, 1, tzinfo=UTC)
    middle = datetime(2026, 8, 2, tzinfo=UTC)
    last = datetime(2026, 8, 3, tzinfo=UTC)
    records = [
        ToolCallRecord(
            index=1,
            name="get_measurement_statistics",
            arguments={"period_from": first.isoformat(), "period_to": middle.isoformat()},
            result=ToolResult(data_status=DataStatus.NO_DATA, data={}),
        ),
        ToolCallRecord(
            index=2,
            name="get_measurement_statistics",
            arguments={"period_from": middle.isoformat(), "period_to": last.isoformat()},
            result=ToolResult(data_status=DataStatus.NO_DATA, data={}),
        ),
    ]
    invalid = AgentCandidate(
        answer="該当データなし",
        period_from=first,
        period_to=last,
        data_status=DataStatus.NO_DATA,
    )

    with pytest.raises(AgentResponseInvalid, match="one evidence tool"):
        validate_and_build_display(invalid, records, "living-room-01")


def test_period_is_displayed_in_asia_tokyo() -> None:
    """UTCで照会した期間を東京時間へ変換して表示する。"""

    start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 2, 0, 0, tzinfo=UTC)
    records = [
        ToolCallRecord(
            index=1,
            name="get_measurement_statistics",
            arguments={"period_from": start.isoformat(), "period_to": end.isoformat()},
            result=ToolResult(data_status=DataStatus.NO_DATA, data={}),
        )
    ]
    valid = AgentCandidate(
        answer="該当データなし",
        period_from=start,
        period_to=end,
        data_status=DataStatus.NO_DATA,
    )

    result = validate_and_build_display(valid, records, "living-room-01")

    assert result.period == (
        "2026-08-01T09:00:00+09:00〜2026-08-02T09:00:00+09:00 (Asia/Tokyo)"
    )
