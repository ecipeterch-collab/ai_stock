"""ORB (Opening Range Breakout) 단위 테스트."""

from __future__ import annotations

from datetime import datetime

from trading.chart_signals import Candle
from trading.orb import (
    compute_opening_range,
    evaluate_orb_breakout,
    is_orb_range_forming,
    is_orb_trade_window,
)


def _c(ts: str, high: int, low: int, close: int, volume: int) -> Candle:
    return Candle(
        ts=ts,
        open=(high + low) // 2,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _day_bars() -> list[Candle]:
    # 2026-08-10 시초 3개 5분봉 + 돌파봉
    return [
        _c("20260810090000", 10100, 10000, 10050, 1000),
        _c("20260810090500", 10200, 10050, 10150, 1200),
        _c("20260810091000", 10300, 10100, 10250, 1100),
        _c("20260810091500", 10500, 10300, 10450, 2000),
        _c("20260810092000", 10600, 10400, 10550, 1800),
    ]


def test_compute_opening_range_high_low() -> None:
    now = datetime(2026, 8, 10, 9, 20, 0)
    opening = compute_opening_range(_day_bars(), now=now)
    assert opening is not None
    assert opening.high == 10300
    assert opening.low == 10000
    assert opening.bar_count == 3


def test_orb_breakout_passes_with_volume() -> None:
    now = datetime(2026, 8, 10, 9, 20, 0)
    result = evaluate_orb_breakout(
        _day_bars(),
        current_price=10550,
        now=now,
        require_above_vwap=False,
        volume_breakout_ratio=1.3,
    )
    assert result.passed, result.reason
    assert result.range_high == 10300
    assert result.bonus > 0


def test_orb_rejects_before_range_end() -> None:
    now = datetime(2026, 8, 10, 9, 10, 0)
    result = evaluate_orb_breakout(
        _day_bars(),
        current_price=10550,
        now=now,
        require_above_vwap=False,
    )
    assert not result.passed
    assert "형성" in result.reason


def test_orb_rejects_no_breakout() -> None:
    now = datetime(2026, 8, 10, 9, 20, 0)
    result = evaluate_orb_breakout(
        _day_bars(),
        current_price=10200,
        now=now,
        require_above_vwap=False,
    )
    assert not result.passed
    assert "미돌파" in result.reason


def test_orb_window_helpers() -> None:
    assert is_orb_range_forming(datetime(2026, 8, 10, 9, 5, 0))
    assert not is_orb_range_forming(datetime(2026, 8, 10, 9, 15, 0))
    assert is_orb_trade_window(datetime(2026, 8, 10, 9, 30, 0))
    assert not is_orb_trade_window(datetime(2026, 8, 10, 11, 0, 0))
