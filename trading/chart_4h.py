"""60분봉을 국내장 4시간 구간으로 모아 스윙 매도 신호를 만든다.

정규장 09:00–15:30은 4시간으로 나누어떨어지지 않는다.
완성봉만 쓴다.

- 09:00–13:00 (4시간). 13:00 이후 완성.
- 13:00–15:30 (2시간 30분). 15:30 이후 완성.

분봉 시각은 봉의 시작 시각이다 (ORB와 동일).
"""

from __future__ import annotations

from datetime import date, datetime, time as dt_time

from trading.chart_signals import Candle, sma
from trading.notebook_patterns import detect_chart_patterns

MA_PERIOD = 20
MORNING_LABEL = "090000"
AFTERNOON_LABEL = "130000"
MORNING_START = dt_time(9, 0)
MORNING_END = dt_time(13, 0)
AFTERNOON_END = dt_time(15, 30)


def _parse_bar_dt(ts: str) -> datetime | None:
    raw = (ts or "").strip()
    if len(raw) >= 14 and raw[:14].isdigit():
        try:
            return datetime.strptime(raw[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None
    if len(raw) >= 12 and raw[:12].isdigit():
        try:
            return datetime.strptime(raw[:12], "%Y%m%d%H%M")
        except ValueError:
            return None
    return None


def _bucket(bar_dt: datetime) -> tuple[date, str] | None:
    clock = bar_dt.time()
    if MORNING_START <= clock < MORNING_END:
        return bar_dt.date(), MORNING_LABEL
    if MORNING_END <= clock < AFTERNOON_END:
        return bar_dt.date(), AFTERNOON_LABEL
    return None


def _bucket_complete(day: date, label: str, now: datetime) -> bool:
    if day < now.date():
        return True
    if day > now.date():
        return False
    if label == MORNING_LABEL:
        return now.time() >= MORNING_END
    return now.time() >= AFTERNOON_END


def completed_4h_bars(
    minute_candles: list[Candle],
    *,
    now: datetime | None = None,
) -> list[Candle]:
    """완성된 4시간(및 장마감 2시간 30분) 봉. 진행 중 구간은 뺀다."""
    current = now or datetime.now()
    groups: dict[tuple[date, str], list[Candle]] = {}
    for candle in minute_candles:
        bar_dt = _parse_bar_dt(candle.ts)
        if bar_dt is None:
            continue
        key = _bucket(bar_dt)
        if key is None or not _bucket_complete(key[0], key[1], current):
            continue
        groups.setdefault(key, []).append(candle)

    out: list[Candle] = []
    for (day, label), bars in groups.items():
        bars.sort(key=lambda c: c.ts)
        out.append(
            Candle(
                ts=f"{day.strftime('%Y%m%d')}{label}",
                open=bars[0].open,
                high=max(c.high for c in bars),
                low=min(c.low for c in bars),
                close=bars[-1].close,
                volume=sum(c.volume for c in bars),
            )
        )
    out.sort(key=lambda c: c.ts)
    return out


def evaluate_4h_sell(completed: list[Candle], *, period: int = MA_PERIOD) -> str | None:
    """마지막 완성봉이 20이평 아래이거나 약세 차트 패턴이면 매도 사유."""
    closes = [float(c.close) for c in completed if c.close > 0]
    if len(closes) < period:
        return None
    average = sma(closes, period)
    if average is None:
        return None
    last = completed[-1]
    parts: list[str] = []
    if last.close < average:
        parts.append(f"4시간 20이평 이탈 (종가 {last.close:,} < {average:,.0f})")
    if len(completed) >= 15:
        _bullish, bearish = detect_chart_patterns(completed)
        if bearish:
            parts.append(f"4시간 약세패턴 {bearish[0]}")
    if not parts:
        return None
    return " · ".join(parts)
