"""自然言語の期間をAsia/Tokyo基準で決定的に解決する。"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent.period_resolver import PeriodResolver, ResolvedPeriod

TOKYO = ZoneInfo("Asia/Tokyo")
FIXED_NOW = datetime(2026, 8, 30, 3, 0, 0, tzinfo=UTC)


def resolver() -> PeriodResolver:
    return PeriodResolver(clock=lambda: FIXED_NOW)


@pytest.mark.parametrize(
    ("expression", "start", "end"),
    [
        ("今日", datetime(2026, 8, 30, tzinfo=TOKYO), datetime(2026, 8, 30, 12, tzinfo=TOKYO)),
        ("昨日", datetime(2026, 8, 29, tzinfo=TOKYO), datetime(2026, 8, 30, tzinfo=TOKYO)),
        ("一昨日", datetime(2026, 8, 28, tzinfo=TOKYO), datetime(2026, 8, 29, tzinfo=TOKYO)),
        ("今週", datetime(2026, 8, 24, tzinfo=TOKYO), datetime(2026, 8, 30, 12, tzinfo=TOKYO)),
        ("先週", datetime(2026, 8, 17, tzinfo=TOKYO), datetime(2026, 8, 24, tzinfo=TOKYO)),
        ("先週末", datetime(2026, 8, 22, tzinfo=TOKYO), datetime(2026, 8, 24, tzinfo=TOKYO)),
        ("今月", datetime(2026, 8, 1, tzinfo=TOKYO), datetime(2026, 8, 30, 12, tzinfo=TOKYO)),
        ("先月", datetime(2026, 7, 1, tzinfo=TOKYO), datetime(2026, 8, 1, tzinfo=TOKYO)),
    ],
)
def test_calendar_relative_periods(expression: str, start: datetime, end: datetime) -> None:
    periods = resolver().resolve(f"{expression}の平均湿度は？", expected_count=1)

    assert periods == (ResolvedPeriod(start, end),)


def test_rolling_hours_end_at_injected_clock() -> None:
    periods = resolver().resolve("過去24時間の温度推移", expected_count=1)

    assert periods == (
        ResolvedPeriod(
            datetime(2026, 8, 29, 12, 0, tzinfo=TOKYO),
            datetime(2026, 8, 30, 12, 0, tzinfo=TOKYO),
        ),
    )


@pytest.mark.parametrize(
    ("expression", "start"),
    [
        ("過去2時間", datetime(2026, 8, 30, 10, tzinfo=TOKYO)),
        ("過去2日", datetime(2026, 8, 28, 12, tzinfo=TOKYO)),
        ("過去2週間", datetime(2026, 8, 16, 12, tzinfo=TOKYO)),
        ("過去2か月", datetime(2026, 6, 30, 12, tzinfo=TOKYO)),
        ("過去2ヶ月", datetime(2026, 6, 30, 12, tzinfo=TOKYO)),
        ("過去2月", datetime(2026, 6, 30, 12, tzinfo=TOKYO)),
    ],
)
def test_all_rolling_period_units(expression: str, start: datetime) -> None:
    periods = resolver().resolve(f"{expression}の温度推移", expected_count=1)

    assert periods == (ResolvedPeriod(start, datetime(2026, 8, 30, 12, tzinfo=TOKYO)),)


@pytest.mark.parametrize(
    ("expression", "start", "end"),
    [
        ("2026年8月20日", datetime(2026, 8, 20, tzinfo=TOKYO), datetime(2026, 8, 21, tzinfo=TOKYO)),
        ("2026年8月", datetime(2026, 8, 1, tzinfo=TOKYO), datetime(2026, 9, 1, tzinfo=TOKYO)),
        ("8月20日", datetime(2026, 8, 20, tzinfo=TOKYO), datetime(2026, 8, 21, tzinfo=TOKYO)),
    ],
)
def test_all_explicit_period_forms(expression: str, start: datetime, end: datetime) -> None:
    periods = resolver().resolve(f"{expression}の平均温度", expected_count=1)

    assert periods == (ResolvedPeriod(start, end),)


def test_explicit_from_to_is_combined_into_one_half_open_period() -> None:
    periods = resolver().resolve("2026年8月1日から2026年8月20日までの平均温度", expected_count=1)

    assert periods == (
        ResolvedPeriod(
            datetime(2026, 8, 1, tzinfo=TOKYO),
            datetime(2026, 8, 21, tzinfo=TOKYO),
        ),
    )


def test_comparison_keeps_two_periods_in_question_order() -> None:
    periods = resolver().resolve("今週と先週の温度を比較", expected_count=2)

    assert periods == (
        ResolvedPeriod(
            datetime(2026, 8, 24, tzinfo=TOKYO),
            datetime(2026, 8, 30, 12, 0, tzinfo=TOKYO),
        ),
        ResolvedPeriod(
            datetime(2026, 8, 17, tzinfo=TOKYO),
            datetime(2026, 8, 24, tzinfo=TOKYO),
        ),
    )


def test_ambiguous_multiple_periods_are_not_resolved_as_one() -> None:
    assert resolver().resolve("昨日と今日の平均温度", expected_count=1) is None


def test_invalid_calendar_date_is_not_resolved() -> None:
    assert resolver().resolve("2026年2月30日の平均温度", expected_count=1) is None


@pytest.mark.parametrize("expression", ["今週末", "先月末", "昨年末"])
def test_unsupported_suffix_is_not_partially_resolved(expression: str) -> None:
    assert resolver().resolve(f"{expression}の平均温度", expected_count=1) is None


@pytest.mark.parametrize(
    "question",
    [
        "今日以外の平均温度",
        "昨日以前の平均温度",
        "今週以降の平均温度",
        "先月より前の平均温度",
        "今日ではない日の平均温度",
        "昨日を除く平均温度",
    ],
)
def test_meaning_changing_period_suffix_is_not_partially_resolved(question: str) -> None:
    assert resolver().resolve(question, expected_count=1) is None


@pytest.mark.parametrize("expression", ["今年", "昨年", "過去91日", "過去1年"])
def test_period_over_ninety_days_is_not_resolved(expression: str) -> None:
    assert resolver().resolve(f"{expression}の平均温度", expected_count=1) is None


def test_period_of_exactly_ninety_days_is_resolved() -> None:
    assert resolver().resolve("過去90日の平均温度", expected_count=1) is not None


def test_rolling_month_clamps_to_leap_day() -> None:
    leap_resolver = PeriodResolver(clock=lambda: datetime(2024, 3, 31, 3, 0, tzinfo=UTC))

    periods = leap_resolver.resolve("過去1か月の平均温度", expected_count=1)

    assert periods == (
        ResolvedPeriod(
            datetime(2024, 2, 29, 12, tzinfo=TOKYO),
            datetime(2024, 3, 31, 12, tzinfo=TOKYO),
        ),
    )


def test_rolling_year_over_limit_is_not_resolved() -> None:
    leap_resolver = PeriodResolver(clock=lambda: datetime(2024, 2, 29, 3, 0, tzinfo=UTC))

    periods = leap_resolver.resolve("過去1年の平均温度", expected_count=1)

    assert periods is None
