"""노트 매매법 패턴 탐지 (MA 기울기·캔들·차트형).

chart_signals와 순환 import를 피하기 위해 OHLC는 duck-typing 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from config.config import (
    chart_ma_fast,
    chart_ma_slow,
    notebook_bonus_asc_triangle,
    notebook_bonus_big_bull,
    notebook_bonus_bull_flag,
    notebook_bonus_doji_reversal,
    notebook_bonus_double_bottom,
    notebook_bonus_engulfing,
    notebook_bonus_hammer_harami,
    notebook_bonus_inv_head_shoulders,
    notebook_bonus_morning_star,
    notebook_candle_bonus_enabled,
    notebook_ma_slope_lookback,
    notebook_max_bonus,
    notebook_pattern_block_bearish,
    notebook_require_ma_uptrend,
    notebook_strategy_enabled,
)


@dataclass
class NotebookPatternResult:
    gate_ok: bool
    gate_reject: str = ""
    bonus: float = 0.0
    reasons: list[str] = field(default_factory=list)
    bearish_block: str = ""


def ma_series(closes: Sequence[float], period: int) -> list[float | None]:
    """각 인덱스 i에 대해 closes[i-period+1:i+1] SMA. 부족하면 None."""
    out: list[float | None] = [None] * len(closes)
    if period <= 0:
        return out
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        out[i] = sum(window) / period
    return out


def ma_slope_up(ma_values: Sequence[float | None], lookback: int) -> bool:
    """최근 MA가 lookback 봉 전 대비 상승했는지."""
    if lookback <= 0 or len(ma_values) <= lookback:
        return False
    cur = ma_values[-1]
    prev = ma_values[-1 - lookback]
    if cur is None or prev is None:
        return False
    return cur > prev


def detect_golden_cross(
    fast: Sequence[float | None],
    slow: Sequence[float | None],
) -> bool:
    """직전: fast <= slow, 현재: fast > slow."""
    if len(fast) < 2 or len(slow) < 2:
        return False
    f0, f1 = fast[-2], fast[-1]
    s0, s1 = slow[-2], slow[-1]
    if None in (f0, f1, s0, s1):
        return False
    return f0 <= s0 and f1 > s1


def evaluate_ma_gate(
    closes: Sequence[float],
    *,
    fast_period: int | None = None,
    slow_period: int | None = None,
    lookback: int | None = None,
    require_uptrend: bool | None = None,
) -> tuple[bool, str, list[str]]:
    """장기 MA 상승 + 단기≥장기. (reject_reason, reasons)."""
    fast_n = fast_period if fast_period is not None else int(chart_ma_fast)
    slow_n = slow_period if slow_period is not None else int(chart_ma_slow)
    lb = lookback if lookback is not None else int(notebook_ma_slope_lookback)
    need_up = (
        notebook_require_ma_uptrend if require_uptrend is None else require_uptrend
    )
    reasons: list[str] = []

    if len(closes) < slow_n + max(lb, 1):
        return False, f"일봉 {len(closes)}개 부족(노트MA)", reasons

    fast = ma_series(closes, fast_n)
    slow = ma_series(closes, slow_n)
    f_cur, s_cur = fast[-1], slow[-1]
    if f_cur is None or s_cur is None:
        return False, "노트MA 계산 불가", reasons

    if need_up and not ma_slope_up(slow, lb):
        return False, "장기MA 하락중(매수금지)", reasons

    if f_cur < s_cur:
        return False, f"{fast_n}MA<{slow_n}MA(노트)", reasons

    if need_up:
        reasons.append("장기MA상승")
    if detect_golden_cross(fast, slow):
        reasons.append("골든크로스")
    else:
        reasons.append(f"{fast_n}MA≥{slow_n}MA")
    return True, "", reasons


def _body(c: Any) -> float:
    return abs(float(c.close) - float(c.open))


def _range(c: Any) -> float:
    return max(float(c.high) - float(c.low), 1e-9)


def _upper_wick(c: Any) -> float:
    return float(c.high) - max(float(c.open), float(c.close))


def _lower_wick(c: Any) -> float:
    return min(float(c.open), float(c.close)) - float(c.low)


def _is_bull(c: Any) -> bool:
    return float(c.close) > float(c.open)


def _is_bear(c: Any) -> bool:
    return float(c.close) < float(c.open)


def _avg_body(candles: Sequence[Any], n: int = 10) -> float:
    recent = list(candles[-n:]) if len(candles) >= n else list(candles)
    if not recent:
        return 0.0
    return sum(_body(c) for c in recent) / len(recent)


def _downtrend(closes: Sequence[float], bars: int = 4) -> bool:
    if len(closes) < bars + 1:
        return False
    return closes[-1] < closes[-1 - bars]


def _uptrend(closes: Sequence[float], bars: int = 4) -> bool:
    if len(closes) < bars + 1:
        return False
    return closes[-1] > closes[-1 - bars]


def is_big_bull(candles: Sequence[Any]) -> bool:
    if not candles:
        return False
    c = candles[-1]
    avg = _avg_body(candles[:-1] or candles)
    return _is_bull(c) and _body(c) >= max(avg * 1.5, 1.0)


def is_doji(c: Any, max_body_ratio: float = 0.1) -> bool:
    return _body(c) / _range(c) <= max_body_ratio


def is_hammer_like(c: Any) -> bool:
    """작은 몸통 + 아랫꼬리 ≥ 몸통×2 (색 무관)."""
    body = _body(c)
    if body <= 0:
        body = 1.0
    if _lower_wick(c) < body * 2:
        return False
    if _upper_wick(c) > body:
        return False
    return _body(c) / _range(c) <= 0.35


def is_bullish_engulfing(prev: Any, cur: Any) -> bool:
    if not (_is_bear(prev) and _is_bull(cur)):
        return False
    return (
        float(cur.open) <= float(prev.close)
        and float(cur.close) >= float(prev.open)
    )


def is_morning_star(c0: Any, c1: Any, c2: Any) -> bool:
    """긴 음봉 → 작은 몸통 → 긴 양봉(첫 음봉 중위 이상 종가)."""
    if not _is_bear(c0) or not _is_bull(c2):
        return False
    avg_ref = (_body(c0) + _body(c2)) / 2.0
    if _body(c0) < avg_ref * 0.8:
        return False
    if _body(c1) > _body(c0) * 0.5:
        return False
    mid = (float(c0.open) + float(c0.close)) / 2.0
    return float(c2.close) >= mid


def detect_candle_patterns(candles: Sequence[Any]) -> list[tuple[str, float]]:
    """(reason, bonus) list for latest bar context."""
    hits: list[tuple[str, float]] = []
    if len(candles) < 2:
        return hits
    closes = [float(c.close) for c in candles]
    cur = candles[-1]

    if is_big_bull(candles):
        hits.append(("큰양선", float(notebook_bonus_big_bull)))

    if is_doji(cur) and _downtrend(closes):
        hits.append(("도지반전", float(notebook_bonus_doji_reversal)))

    if is_hammer_like(cur) and _downtrend(closes):
        hits.append(("하라미망치", float(notebook_bonus_hammer_harami)))

    if len(candles) >= 2 and is_bullish_engulfing(candles[-2], cur):
        hits.append(("상승포선", float(notebook_bonus_engulfing)))

    if len(candles) >= 3 and is_morning_star(candles[-3], candles[-2], cur):
        hits.append(("모닝스타", float(notebook_bonus_morning_star)))

    return hits


def _swing_indices(values: Sequence[float], order: int = 2) -> tuple[list[int], list[int]]:
    """로컬 고점·저점 인덱스."""
    peaks: list[int] = []
    troughs: list[int] = []
    n = len(values)
    if n < order * 2 + 1:
        return peaks, troughs
    for i in range(order, n - order):
        window = values[i - order : i + order + 1]
        v = values[i]
        if v == max(window) and window.count(v) == 1:
            peaks.append(i)
        if v == min(window) and window.count(v) == 1:
            troughs.append(i)
    return peaks, troughs


def _near(a: float, b: float, tol_pct: float = 2.0) -> bool:
    base = max(abs(a), abs(b), 1.0)
    return abs(a - b) / base * 100.0 <= tol_pct


def detect_chart_patterns(candles: Sequence[Any]) -> tuple[list[tuple[str, float]], list[str]]:
    """Returns (bullish hits with bonus, bearish block labels)."""
    bullish: list[tuple[str, float]] = []
    bearish: list[str] = []
    if len(candles) < 15:
        return bullish, bearish

    highs = [float(c.high) for c in candles]
    lows = [float(c.low) for c in candles]
    closes = [float(c.close) for c in candles]
    last = closes[-1]
    peaks, troughs = _swing_indices(highs, order=2)
    # troughs from lows
    _, troughs_l = _swing_indices(lows, order=2)
    troughs = troughs_l

    # Double bottom: two similar troughs, break neckline
    if len(troughs) >= 2:
        t1, t2 = troughs[-2], troughs[-1]
        if t2 > t1 and _near(lows[t1], lows[t2], 2.5):
            neck = max(highs[t1 : t2 + 1]) if t2 > t1 else highs[t2]
            if last > neck:
                bullish.append(("쌍바닥", float(notebook_bonus_double_bottom)))

    # Inverse H&S: three troughs, middle lowest, break neckline
    if len(troughs) >= 3:
        a, b, c = troughs[-3], troughs[-2], troughs[-1]
        if lows[b] < lows[a] and lows[b] < lows[c] and _near(lows[a], lows[c], 4.0):
            left_peak = max(highs[a : b + 1])
            right_peak = max(highs[b : c + 1])
            neck = (left_peak + right_peak) / 2.0
            if last > neck:
                bullish.append(
                    ("역머리어깨", float(notebook_bonus_inv_head_shoulders))
                )

    # Double top → bearish block
    if len(peaks) >= 2:
        p1, p2 = peaks[-2], peaks[-1]
        if p2 > p1 and _near(highs[p1], highs[p2], 2.5):
            neck = min(lows[p1 : p2 + 1])
            if last < neck:
                bearish.append("쌍봉")

    # Head & shoulders → bearish
    if len(peaks) >= 3:
        a, b, c = peaks[-3], peaks[-2], peaks[-1]
        if highs[b] > highs[a] and highs[b] > highs[c] and _near(highs[a], highs[c], 4.0):
            left_t = min(lows[a : b + 1])
            right_t = min(lows[b : c + 1])
            neck = (left_t + right_t) / 2.0
            if last < neck:
                bearish.append("머리어깨")

    # Ascending triangle: flat resistance + rising lows + breakout
    window = candles[-20:]
    wh = [float(c.high) for c in window]
    wl = [float(c.low) for c in window]
    res = max(wh)
    # resistance touches: highs near res
    near_res = sum(1 for h in wh if _near(h, res, 1.5))
    if near_res >= 2 and wl[-1] > wl[0] and last > res * 0.998:
        # rising lows roughly
        mid = len(wl) // 2
        if min(wl[mid:]) >= min(wl[:mid]) * 0.995:
            bullish.append(("상승삼각형", float(notebook_bonus_asc_triangle)))

    # Bull flag: sharp rise then short pullback, break above pullback high
    if len(candles) >= 12:
        pole = candles[-12:-5]
        flag = candles[-5:]
        pole_move = float(pole[-1].close) - float(pole[0].open)
        if pole_move > 0:
            flag_high = max(float(c.high) for c in flag)
            flag_low = min(float(c.low) for c in flag)
            pullback = float(pole[-1].close) - flag_low
            if 0 < pullback < pole_move * 0.6 and last >= flag_high:
                bullish.append(("상승깃발", float(notebook_bonus_bull_flag)))

    # Bear flag / descending triangle (block)
    if len(candles) >= 12:
        pole = candles[-12:-5]
        flag = candles[-5:]
        pole_move = float(pole[-1].close) - float(pole[0].open)
        if pole_move < 0:
            flag_low = min(float(c.low) for c in flag)
            flag_high = max(float(c.high) for c in flag)
            bounce = flag_high - float(pole[-1].close)
            if 0 < bounce < abs(pole_move) * 0.6 and last <= flag_low:
                bearish.append("하락깃발")

    w = candles[-20:]
    wh = [float(c.high) for c in w]
    wl = [float(c.low) for c in w]
    support = min(wl)
    near_sup = sum(1 for x in wl if _near(x, support, 1.5))
    if near_sup >= 2 and wh[-1] < wh[0] and last < support * 1.002:
        mid = len(wh) // 2
        if max(wh[mid:]) <= max(wh[:mid]) * 1.005:
            bearish.append("하락삼각형")

    return bullish, bearish


def evaluate_notebook_patterns(
    *,
    daily_closes: Sequence[float],
    minute_candles: Sequence[Any] | None = None,
) -> NotebookPatternResult:
    """노트 전략 종합 평가."""
    if not notebook_strategy_enabled:
        return NotebookPatternResult(gate_ok=True)

    ok, reject, ma_reasons = evaluate_ma_gate(daily_closes)
    if not ok:
        return NotebookPatternResult(gate_ok=False, gate_reject=reject, reasons=ma_reasons)

    reasons = list(ma_reasons)
    bonus = 0.0
    bearish_block = ""

    candles = minute_candles if minute_candles else []
    # Prefer minute for candle patterns; fall back unused if empty
    if notebook_candle_bonus_enabled and len(candles) >= 3:
        for label, pts in detect_candle_patterns(candles):
            bonus += pts
            reasons.append(label)

        bullish, bearish = detect_chart_patterns(candles)
        for label, pts in bullish:
            bonus += pts
            reasons.append(label)
        if bearish and notebook_pattern_block_bearish:
            bearish_block = bearish[0]
            return NotebookPatternResult(
                gate_ok=False,
                gate_reject=f"약세패턴 {bearish_block}",
                bonus=0.0,
                reasons=reasons,
                bearish_block=bearish_block,
            )
        elif bearish:
            reasons.append(f"약세참고:{','.join(bearish)}")

    bonus = min(bonus, float(notebook_max_bonus))
    return NotebookPatternResult(
        gate_ok=True,
        bonus=bonus,
        reasons=reasons,
    )
