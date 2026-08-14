"""Opening Range Breakout (ORB) — 시초 N분 고가 돌파 + 거래량 확인.

공개 ORB 규칙(15분 레인지·거래량 확인)을 키움 분봉에 맞게 단순화한 구현.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dt_time

from trading.chart_signals import Candle, vwap
from trading.market_utils import parse_hhmm


@dataclass(frozen=True)
class OpeningRange:
    high: int
    low: int
    bar_count: int
    avg_volume: float
    start: dt_time
    end: dt_time


@dataclass(frozen=True)
class OrbCheckResult:
    passed: bool
    reason: str
    range_high: int = 0
    range_low: int = 0
    breakout_pct: float = 0.0
    volume_ratio: float = 0.0
    bonus: float = 0.0


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


def _bars_in_window(
    candles: list[Candle],
    *,
    day: date,
    start: dt_time,
    end: dt_time,
) -> list[Candle]:
    """[start, end) 구간의 분봉. end 시각 봉은 레인지에 포함하지 않는다."""
    out: list[Candle] = []
    for c in candles:
        dt = _parse_bar_dt(c.ts)
        if dt is None or dt.date() != day:
            continue
        t = dt.time()
        if start <= t < end:
            out.append(c)
    out.sort(key=lambda x: x.ts)
    return out


def compute_opening_range(
    candles: list[Candle],
    *,
    now: datetime | None = None,
    range_start: str = "09:00",
    range_end: str = "09:15",
) -> OpeningRange | None:
    """시초 오프닝 레인지(고·저·평균거래량) 계산."""
    current = now or datetime.now()
    start_t = parse_hhmm(range_start)
    end_t = parse_hhmm(range_end)
    bars = _bars_in_window(
        candles, day=current.date(), start=start_t, end=end_t
    )
    if not bars:
        return None
    high = max(c.high for c in bars)
    low = min(c.low for c in bars)
    if high <= 0 or low <= 0 or high < low:
        return None
    vols = [c.volume for c in bars if c.volume > 0]
    avg_vol = (sum(vols) / len(vols)) if vols else 0.0
    return OpeningRange(
        high=int(high),
        low=int(low),
        bar_count=len(bars),
        avg_volume=avg_vol,
        start=start_t,
        end=end_t,
    )


def evaluate_orb_breakout(
    candles: list[Candle],
    *,
    current_price: int,
    now: datetime | None = None,
    range_start: str = "09:00",
    range_end: str = "09:15",
    trade_end: str = "10:00",
    volume_breakout_ratio: float = 1.3,
    require_above_vwap: bool = True,
    min_range_pct: float = 0.2,
    max_range_pct: float = 6.0,
    score_bonus: float = 4.0,
) -> OrbCheckResult:
    """시초 고가 돌파 + 거래량 확인. 레인지 형성 전·매매창 외는 미통과."""
    current = now or datetime.now()
    t = current.time()
    start_t = parse_hhmm(range_start)
    end_t = parse_hhmm(range_end)
    trade_end_t = parse_hhmm(trade_end)

    if t < end_t:
        return OrbCheckResult(False, f"ORB 시초구간 형성 중 (~{range_end})")
    if t > trade_end_t:
        return OrbCheckResult(False, f"ORB 매매창 종료 ({trade_end} 이후)")

    opening = compute_opening_range(
        candles,
        now=current,
        range_start=range_start,
        range_end=range_end,
    )
    if opening is None:
        return OrbCheckResult(False, "ORB 시초 분봉 부족")

    mid = (opening.high + opening.low) / 2.0
    if mid <= 0:
        return OrbCheckResult(False, "ORB 레인지 이상")
    range_pct = (opening.high - opening.low) / mid * 100.0
    if range_pct < min_range_pct:
        return OrbCheckResult(
            False,
            f"ORB 레인지 과협 ({range_pct:.2f}% < {min_range_pct:.1f}%)",
            range_high=opening.high,
            range_low=opening.low,
        )
    if range_pct > max_range_pct:
        return OrbCheckResult(
            False,
            f"ORB 레인지 과대 ({range_pct:.2f}% > {max_range_pct:.1f}%)",
            range_high=opening.high,
            range_low=opening.low,
        )

    if current_price <= opening.high:
        return OrbCheckResult(
            False,
            f"ORB 고가 미돌파 (가 {current_price} ≤ 고 {opening.high})",
            range_high=opening.high,
            range_low=opening.low,
        )

    # 돌파 이후(레인지 종료~현재) 봉의 거래량 확인
    post = _bars_in_window(
        candles, day=current.date(), start=end_t, end=t
    )
    # 현재 시각이 봉 경계에 있으면 마지막 봉까지 포함되도록 end를 조금 여유
    if not post:
        post = [
            c
            for c in candles
            if (dt := _parse_bar_dt(c.ts)) is not None
            and dt.date() == current.date()
            and dt.time() >= end_t
        ]
        post.sort(key=lambda x: x.ts)
    breakout_vol = post[-1].volume if post else 0
    vol_ratio = (
        breakout_vol / opening.avg_volume if opening.avg_volume > 0 else 0.0
    )
    if opening.avg_volume > 0 and vol_ratio < volume_breakout_ratio:
        return OrbCheckResult(
            False,
            f"ORB 거래량 미달 ({vol_ratio:.2f}x < {volume_breakout_ratio:.1f}x)",
            range_high=opening.high,
            range_low=opening.low,
            volume_ratio=vol_ratio,
        )

    if require_above_vwap:
        session = [
            c
            for c in candles
            if (dt := _parse_bar_dt(c.ts)) is not None
            and dt.date() == current.date()
            and dt.time() >= start_t
        ]
        session.sort(key=lambda x: x.ts)
        session_vwap = vwap(session) if session else None
        if session_vwap and current_price < session_vwap:
            return OrbCheckResult(
                False,
                f"ORB VWAP 하회 (가 {current_price} < VWAP {session_vwap:.0f})",
                range_high=opening.high,
                range_low=opening.low,
                volume_ratio=vol_ratio,
            )

    breakout_pct = (current_price - opening.high) / opening.high * 100.0
    return OrbCheckResult(
        True,
        (
            f"ORB 돌파 +{breakout_pct:.2f}% "
            f"(고 {opening.high}·저 {opening.low}·{vol_ratio:.1f}x)"
        ),
        range_high=opening.high,
        range_low=opening.low,
        breakout_pct=breakout_pct,
        volume_ratio=vol_ratio,
        bonus=float(score_bonus),
    )


def is_orb_trade_window(
    now: datetime | None = None,
    *,
    range_end: str = "09:15",
    trade_end: str = "10:00",
) -> bool:
    t = (now or datetime.now()).time()
    return parse_hhmm(range_end) <= t <= parse_hhmm(trade_end)


def is_orb_range_forming(
    now: datetime | None = None,
    *,
    range_start: str = "09:00",
    range_end: str = "09:15",
) -> bool:
    t = (now or datetime.now()).time()
    return parse_hhmm(range_start) <= t < parse_hhmm(range_end)
