"""モデル回答を採用できない場合の決定的な表示再構築を検証する。"""

from app.agent.fallback import build_verified_fallback
from app.agent.schemas import ToolCallRecord, ToolResult
from app.schemas.query import DataStatus


def test_temperature_and_humidity_phrase_selects_both_metrics() -> None:
    record = ToolCallRecord(
        index=1,
        name="get_latest_measurement",
        arguments={"device_id": "living-room-01"},
        result=ToolResult(
            data_status=DataStatus.AVAILABLE,
            data={
                "temperature_c": "24.5",
                "humidity_percent": "50.0",
            },
        ),
    )

    result = build_verified_fallback(
        "現在の温湿度を教えて", [record], "living-room-01"
    )

    assert result.answer == "最新温度は24.5℃です。最新湿度は50.0%です。"
    assert result.evidence == ("最新温度: 24.5℃", "最新湿度: 50.0%")


def test_series_fallback_lists_bucket_averages_in_time_order() -> None:
    record = ToolCallRecord(
        index=1,
        name="get_measurement_series",
        arguments={
            "period_from": "2026-08-31T00:00:00+09:00",
            "period_to": "2026-09-01T00:00:00+09:00",
        },
        result=ToolResult(
            data_status=DataStatus.AVAILABLE,
            data={
                "points": [
                    {
                        "bucket_from": "2026-08-30T15:00:00Z",
                        "temperature": {"average": "25.10"},
                    },
                    {
                        "bucket_from": "2026-08-30T16:00:00Z",
                        "temperature": {"average": "26.20"},
                    },
                ]
            },
        ),
    )

    result = build_verified_fallback(
        "過去24時間の温度推移", [record], "living-room-01"
    )

    assert result.answer == (
        "時刻別平均温度の推移は、2026-08-31T00:00:00+09:00 25.10℃、"
        "2026-08-31T01:00:00+09:00 26.20℃です。"
    )
    assert result.evidence == ("温度平均値: 25.10℃", "温度平均値: 26.20℃")


def test_series_fallback_samples_at_most_twelve_points() -> None:
    points = [
        {
            "bucket_from": f"2026-08-30T{hour:02d}:00:00Z",
            "temperature": {"average": str(20 + hour)},
        }
        for hour in range(13)
    ]
    record = ToolCallRecord(
        index=1,
        name="get_measurement_series",
        arguments={
            "period_from": "2026-08-31T00:00:00+09:00",
            "period_to": "2026-09-01T00:00:00+09:00",
        },
        result=ToolResult(
            data_status=DataStatus.AVAILABLE,
            data={"points": points},
        ),
    )

    result = build_verified_fallback(
        "過去24時間の温度推移", [record], "living-room-01"
    )

    assert len(result.evidence) == 12
    assert "20℃" in result.answer
    assert "32℃" in result.answer


def test_comparison_fallback_uses_both_periods_and_tool_difference() -> None:
    record = ToolCallRecord(
        index=1,
        name="compare_periods",
        arguments={},
        result=ToolResult(
            data_status=DataStatus.AVAILABLE,
            data={
                "first": {"temperature": {"average": "28.01"}},
                "second": {"temperature": {"average": "27.89"}},
                "temperature_average_difference": "0.12",
            },
        ),
    )

    result = build_verified_fallback(
        "今日と昨日の温度を比較して", [record], "living-room-01"
    )

    assert result.answer == (
        "前者の平均温度は28.01℃、後者は27.89℃で、差は0.12℃です。"
    )
    assert result.evidence == (
        "温度平均値: 28.01℃",
        "温度平均値: 27.89℃",
        "温度平均との差: 0.12℃",
    )
