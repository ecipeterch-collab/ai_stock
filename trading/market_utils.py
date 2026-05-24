from __future__ import annotations

from datetime import datetime, time as dt_time


MARKET_OPEN = dt_time(9, 0)
MARKET_CLOSE = dt_time(15, 30)


def parse_hhmm(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(int(hour), int(minute))


def is_weekday(now: datetime | None = None) -> bool:
    current = now or datetime.now()
    return current.weekday() < 5


def is_market_open(now: datetime | None = None) -> bool:
    current = now or datetime.now()
    if not is_weekday(current):
        return False
    return MARKET_OPEN <= current.time() <= MARKET_CLOSE


def is_in_time_window(start: str, end: str, now: datetime | None = None) -> bool:
    current = now or datetime.now()
    start_t = parse_hhmm(start)
    end_t = parse_hhmm(end)
    return start_t <= current.time() <= end_t


def is_buy_window(
    morning_start: str,
    morning_end: str,
    afternoon_start: str,
    afternoon_end: str,
    now: datetime | None = None,
) -> bool:
    return is_in_time_window(morning_start, morning_end, now) or is_in_time_window(
        afternoon_start, afternoon_end, now
    )


def market_status_text(now: datetime | None = None) -> str:
    current = now or datetime.now()
    if not is_weekday(current):
        return "휴장 (주말)"
    if is_market_open(current):
        return "장중"
    if current.time() < MARKET_OPEN:
        return "장전"
    return "장마감"
