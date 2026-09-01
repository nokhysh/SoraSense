"""質問中の期間表現を、Asia/Tokyo基準の決定的な日時区間へ変換する。"""

import calendar
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

Clock = Callable[[], datetime]
DISPLAY_ZONE = ZoneInfo("Asia/Tokyo")
MAX_PERIOD = timedelta(days=90)
UNSUPPORTED_PERIOD_SUFFIX = re.compile(
    r"^\s*(?:以外|以前|以降|より前|より後|ではない|じゃない|を除(?:く|いて)?)"
)
PERIOD_TOKEN = re.compile(
    # 長い表現を先に評価し、「先週末」を「先週」と誤認しない。
    r"先週末|一昨日|昨日|今日|先週(?!末)|今週(?!末)|"
    r"先月(?!末)|今月(?!末)|昨年(?!末)|今年(?!末)|"
    r"過去\s*\d+\s*(?:時間|日|週間|か月|ヶ月|月|年)|"
    r"\d{4}年\s*\d{1,2}月\s*\d{1,2}日|"
    r"\d{4}年\s*\d{1,2}月|"
    r"(?<!年)\d{1,2}月\s*\d{1,2}日"
)
ROLLING_PERIOD = re.compile(r"過去\s*(?P<count>\d+)\s*(?P<unit>時間|日|週間|か月|ヶ月|月|年)")
YEAR_MONTH_DAY = re.compile(r"(?P<year>\d{4})年\s*(?P<month>\d{1,2})月\s*(?P<day>\d{1,2})日")
YEAR_MONTH = re.compile(r"(?P<year>\d{4})年\s*(?P<month>\d{1,2})月")
MONTH_DAY = re.compile(r"(?P<month>\d{1,2})月\s*(?P<day>\d{1,2})日")


@dataclass(frozen=True)
class ResolvedPeriod:
    """照会へ強制する開始含む・終了含まない日時区間。"""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("resolved period must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("resolved period start must be earlier than end")


class PeriodResolver:
    """相対・明示期間を固定Clockから再現可能な区間へ解決する。"""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def resolve(self, question: str, *, expected_count: int) -> tuple[ResolvedPeriod, ...] | None:
        """必要数の期間を返し、曖昧・不正な指定は解決しない。"""

        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        local_now = now.astimezone(DISPLAY_ZONE)
        normalized = unicodedata.normalize("NFKC", question)
        try:
            matches = tuple(PERIOD_TOKEN.finditer(normalized))
            if any(
                UNSUPPORTED_PERIOD_SUFFIX.match(normalized[match.end() :])
                for match in matches
            ):
                return None
            periods = tuple(self._resolve_token(match.group(), local_now) for match in matches)
        except ValueError:
            return None

        if expected_count == 1 and len(periods) == 1:
            return periods if self._within_limit(periods) else None
        if (
            expected_count == 1
            and len(periods) == 2
            and "から" in normalized
            and "まで" in normalized
            and periods[0].start < periods[1].end
        ):
            combined = (ResolvedPeriod(periods[0].start, periods[1].end),)
            return combined if self._within_limit(combined) else None
        if expected_count == 2 and len(periods) == 2:
            return periods if self._within_limit(periods) else None
        return None

    @staticmethod
    def _within_limit(periods: tuple[ResolvedPeriod, ...]) -> bool:
        """QueryServiceと同じUTC経過時間で90日上限を確認する。"""

        return all(
            period.end.astimezone(UTC) - period.start.astimezone(UTC) <= MAX_PERIOD
            for period in periods
        )

    def _resolve_token(self, token: str, now: datetime) -> ResolvedPeriod:
        today = datetime.combine(now.date(), time.min, tzinfo=DISPLAY_ZONE)
        if token == "今日":
            return ResolvedPeriod(today, now)
        if token == "昨日":
            return ResolvedPeriod(today - timedelta(days=1), today)
        if token == "一昨日":
            return ResolvedPeriod(today - timedelta(days=2), today - timedelta(days=1))
        if token in {"今週", "先週"}:
            this_week = today - timedelta(days=today.weekday())
            if token == "今週":
                return ResolvedPeriod(this_week, now)
            return ResolvedPeriod(this_week - timedelta(days=7), this_week)
        if token == "先週末":
            this_week = today - timedelta(days=today.weekday())
            return ResolvedPeriod(
                this_week - timedelta(days=2),
                this_week,
            )
        if token in {"今月", "先月"}:
            this_month = datetime(now.year, now.month, 1, tzinfo=DISPLAY_ZONE)
            if token == "今月":
                return ResolvedPeriod(this_month, now)
            return ResolvedPeriod(_shift_months(this_month, -1), this_month)
        if token in {"今年", "昨年"}:
            this_year = datetime(now.year, 1, 1, tzinfo=DISPLAY_ZONE)
            if token == "今年":
                return ResolvedPeriod(this_year, now)
            return ResolvedPeriod(datetime(now.year - 1, 1, 1, tzinfo=DISPLAY_ZONE), this_year)

        rolling = ROLLING_PERIOD.fullmatch(token)
        if rolling is not None:
            count = int(rolling.group("count"))
            if count <= 0:
                raise ValueError("rolling period must be positive")
            unit = rolling.group("unit")
            if unit == "時間":
                start = now - timedelta(hours=count)
            elif unit == "日":
                start = now - timedelta(days=count)
            elif unit == "週間":
                start = now - timedelta(weeks=count)
            elif unit in {"か月", "ヶ月", "月"}:
                start = _shift_months(now, -count)
            else:
                start = _shift_years(now, -count)
            return ResolvedPeriod(start, now)

        explicit_day = YEAR_MONTH_DAY.fullmatch(token)
        if explicit_day is not None:
            start = _local_day(
                int(explicit_day.group("year")),
                int(explicit_day.group("month")),
                int(explicit_day.group("day")),
            )
            return ResolvedPeriod(start, start + timedelta(days=1))

        explicit_month = YEAR_MONTH.fullmatch(token)
        if explicit_month is not None:
            start = datetime(
                int(explicit_month.group("year")),
                int(explicit_month.group("month")),
                1,
                tzinfo=DISPLAY_ZONE,
            )
            return ResolvedPeriod(start, _shift_months(start, 1))

        month_day = MONTH_DAY.fullmatch(token)
        if month_day is not None:
            start = _local_day(
                now.year,
                int(month_day.group("month")),
                int(month_day.group("day")),
            )
            return ResolvedPeriod(start, start + timedelta(days=1))
        raise ValueError("unsupported period token")


def _local_day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=DISPLAY_ZONE)


def _shift_months(value: datetime, months: int) -> datetime:
    """日付を対象月の末日に収めながら月単位で移動する。"""

    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _shift_years(value: datetime, years: int) -> datetime:
    """うるう日を対象年の末日に収めながら年単位で移動する。"""

    year = value.year + years
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return value.replace(year=year, day=day)
