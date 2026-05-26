from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


US_MARKET_OPEN = time(9, 30)
US_MARKET_CLOSE = time(16, 0)


class RuleBasedTimezone(tzinfo):
    def __init__(self, name: str):
        self.name = name

    def utcoffset(self, dt: datetime | None) -> timedelta:
        if self.name == "America/New_York":
            return timedelta(hours=-4 if dt and _is_us_dst(dt) else -5)
        if self.name == "Europe/Berlin":
            return timedelta(hours=2 if dt and _is_eu_dst(dt) else 1)
        return timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        if self.name == "America/New_York":
            return timedelta(hours=1 if dt and _is_us_dst(dt) else 0)
        if self.name == "Europe/Berlin":
            return timedelta(hours=1 if dt and _is_eu_dst(dt) else 0)
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return self.name


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> int:
    current = datetime(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return 1 + offset + (n - 1) * 7


def _last_weekday(year: int, month: int, weekday: int) -> int:
    if month == 12:
        current = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = datetime(year, month + 1, 1) - timedelta(days=1)
    return current.day - ((current.weekday() - weekday) % 7)


def _is_us_dst(dt: datetime) -> bool:
    start = datetime(dt.year, 3, _nth_weekday(dt.year, 3, 6, 2), 2)
    end = datetime(dt.year, 11, _nth_weekday(dt.year, 11, 6, 1), 2)
    naive = dt.replace(tzinfo=None)
    return start <= naive < end


def _is_eu_dst(dt: datetime) -> bool:
    start = datetime(dt.year, 3, _last_weekday(dt.year, 3, 6), 2)
    end = datetime(dt.year, 10, _last_weekday(dt.year, 10, 6), 3)
    naive = dt.replace(tzinfo=None)
    return start <= naive < end


def get_timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return RuleBasedTimezone(name)


def now_in_market_tz(market_timezone: str = "America/New_York") -> datetime:
    return datetime.now(get_timezone(market_timezone))


def is_us_market_open(dt: datetime | None = None, market_timezone: str = "America/New_York") -> bool:
    market_dt = dt.astimezone(get_timezone(market_timezone)) if dt else now_in_market_tz(market_timezone)
    if market_dt.weekday() >= 5:
        return False
    return US_MARKET_OPEN <= market_dt.time() <= US_MARKET_CLOSE


def describe_market_window(local_timezone: str, market_timezone: str = "America/New_York") -> str:
    today_market = now_in_market_tz(market_timezone).date()
    market_zone = get_timezone(market_timezone)
    local_zone = get_timezone(local_timezone)
    open_dt = datetime.combine(today_market, US_MARKET_OPEN, market_zone).astimezone(local_zone)
    close_dt = datetime.combine(today_market, US_MARKET_CLOSE, market_zone).astimezone(local_zone)
    return f"{open_dt:%H:%M} to {close_dt:%H:%M} {local_timezone}"
