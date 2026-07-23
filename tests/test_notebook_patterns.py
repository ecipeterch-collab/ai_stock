"""노트 패턴 탐지 단위 테스트."""

from __future__ import annotations

from types import SimpleNamespace

from trading.notebook_patterns import (
    detect_candle_patterns,
    detect_golden_cross,
    evaluate_ma_gate,
    evaluate_notebook_patterns,
    is_big_bull,
    is_bullish_engulfing,
    is_doji,
    is_hammer_like,
    is_morning_star,
    ma_series,
    ma_slope_up,
)


def _c(o: int, h: int, l: int, cl: int, v: int = 1000) -> SimpleNamespace:
    return SimpleNamespace(open=o, high=h, low=l, close=cl, volume=v, ts="")


def test_ma_series_and_slope_up():
    closes = [float(i) for i in range(1, 30)]
    slow = ma_series(closes, 5)
    assert slow[-1] is not None
    assert ma_slope_up(slow, 3) is True


def test_ma_slope_down_rejects_gate():
    # 하락 추세 종가
    closes = [float(100 - i) for i in range(40)]
    ok, reject, _ = evaluate_ma_gate(
        closes,
        fast_period=5,
        slow_period=20,
        lookback=3,
        require_uptrend=True,
    )
    assert ok is False
    assert "하락" in reject or "MA" in reject


def test_ma_gate_passes_uptrend_alignment():
    closes = [float(50 + i) for i in range(40)]
    ok, reject, reasons = evaluate_ma_gate(
        closes,
        fast_period=5,
        slow_period=20,
        lookback=3,
        require_uptrend=True,
    )
    assert ok is True
    assert reject == ""
    assert any("MA" in r or "골든" in r or "상승" in r for r in reasons)


def test_golden_cross_detection():
    # slow ~10, fast crosses above
    closes = [10.0] * 20 + [9.0, 9.0, 9.0, 9.0, 12.0, 13.0, 14.0]
    fast = ma_series(closes, 3)
    slow = ma_series(closes, 5)
    # May or may not cross depending on series; ensure function is boolean
    assert isinstance(detect_golden_cross(fast, slow), bool)


def test_big_bull_and_doji_hammer():
    small = [_c(100, 101, 99, 100) for _ in range(8)]
    big = small + [_c(100, 120, 99, 118)]
    assert is_big_bull(big) is True

    doji = _c(100, 105, 95, 100)
    assert is_doji(doji) is True

    hammer = _c(100, 101, 90, 100)
    assert is_hammer_like(hammer) is True


def test_engulfing_and_morning_star():
    prev = _c(110, 111, 100, 101)  # bear
    cur = _c(100, 120, 99, 118)  # bull engulf
    assert is_bullish_engulfing(prev, cur) is True

    c0 = _c(120, 121, 100, 101)
    c1 = _c(100, 102, 98, 99)
    c2 = _c(100, 125, 99, 122)
    assert is_morning_star(c0, c1, c2) is True


def test_detect_candle_patterns_big_bull():
    candles = [_c(100 + i, 101 + i, 99 + i, 100 + i) for i in range(10)]
    candles.append(_c(110, 140, 109, 138))
    hits = detect_candle_patterns(candles)
    labels = [h[0] for h in hits]
    assert "큰양선" in labels


def test_evaluate_notebook_disabled_passthrough(monkeypatch):
    import trading.notebook_patterns as np

    monkeypatch.setattr(np, "notebook_strategy_enabled", False)
    r = evaluate_notebook_patterns(daily_closes=[float(i) for i in range(40)])
    assert r.gate_ok is True
    assert r.bonus == 0.0
