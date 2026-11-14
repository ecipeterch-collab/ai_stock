"""60분봉을 장중 4시간봉으로 모아 스윙 매도 신호를 만든다."""

from __future__ import annotations

from datetime import datetime

from trading.chart_4h import completed_4h_bars, evaluate_4h_sell
from trading.chart_signals import Candle


def _c(ts: str, open_: int, high: int, low: int, close: int, volume: int = 10) -> Candle:
    return Candle(ts=ts, open=open_, high=high, low=low, close=close, volume=volume)


def _session(day: str, *, last: int = 100) -> list[Candle]:
    """09:00-13:00, 13:00-15:30 두 구간. 종가는 last로 고정."""
    morning = [
        _c(f"{day}090000", last, last + 5, last - 5, last),
        _c(f"{day}100000", last, last + 2, last - 2, last),
        _c(f"{day}110000", last, last + 2, last - 2, last),
        _c(f"{day}120000", last, last + 2, last - 2, last),
    ]
    afternoon = [
        _c(f"{day}130000", last, last + 3, last - 3, last),
        _c(f"{day}140000", last, last + 1, last - 1, last),
        _c(f"{day}150000", last, last + 1, last - 1, last),
    ]
    return morning + afternoon


def test_aggregates_completed_session_into_two_bars() -> None:
    day = "20261113"
    bars = [
        _c(f"{day}090000", 100, 110, 90, 105, 10),
        _c(f"{day}100000", 105, 120, 100, 115, 10),
        _c(f"{day}110000", 115, 118, 108, 110, 10),
        _c(f"{day}120000", 110, 112, 104, 108, 10),
        _c(f"{day}130000", 108, 109, 100, 102, 10),
        _c(f"{day}140000", 102, 107, 101, 106, 10),
        _c(f"{day}150000", 106, 108, 103, 104, 10),
    ]
    out = completed_4h_bars(bars, now=datetime(2026, 11, 13, 16, 0))
    assert len(out) == 2
    assert out[0].ts == f"{day}090000"
    assert (out[0].open, out[0].high, out[0].low, out[0].close, out[0].volume) == (
        100,
        120,
        90,
        108,
        40,
    )
    assert out[1].ts == f"{day}130000"
    assert (out[1].open, out[1].close, out[1].volume) == (108, 104, 30)


def test_hides_the_bar_that_is_still_forming() -> None:
    day = "20261113"
    bars = _session("20261112", last=100) + _session(day, last=110)
    at_11 = completed_4h_bars(bars, now=datetime(2026, 11, 13, 11, 0))
    assert [c.ts for c in at_11] == ["20261112090000", "20261112130000"]

    at_14 = completed_4h_bars(bars, now=datetime(2026, 11, 13, 14, 0))
    assert [c.ts for c in at_14] == [
        "20261112090000",
        "20261112130000",
        "20261113090000",
    ]


def test_ma_break_on_last_completed_bar() -> None:
    bars: list[Candle] = []
    for i in range(19):
        bars.append(_c(f"202610{i:02d}090000", 100, 101, 99, 100))
    bars.append(_c("20261113090000", 100, 101, 80, 90))
    reason = evaluate_4h_sell(bars)
    assert reason is not None
    assert reason.startswith("4시간 20이평 이탈")
    assert "90" in reason


def test_flat_closes_do_not_sell() -> None:
    bars = [_c(f"202610{i:02d}090000", 100, 101, 99, 100) for i in range(20)]
    assert evaluate_4h_sell(bars) is None


def test_short_history_does_not_sell() -> None:
    bars = [_c(f"202610{i:02d}090000", 100, 101, 50, 50) for i in range(10)]
    assert evaluate_4h_sell(bars) is None


def test_bearish_pattern_sells_while_price_holds_the_average(monkeypatch) -> None:
    monkeypatch.setattr(
        "trading.chart_4h.detect_chart_patterns",
        lambda candles: ([], ["쌍봉"]),
    )
    bars = [_c(f"202610{i:02d}090000", 100, 101, 99, 100) for i in range(20)]
    reason = evaluate_4h_sell(bars)
    assert reason == "4시간 약세패턴 쌍봉"


def test_strategy_loads_60m_and_returns_ma_break() -> None:
    from unittest.mock import MagicMock

    from trading.strategy import AutoTradingStrategy

    rows = []
    for day in range(1, 20):
        rows.append(
            {
                "cntr_tm": f"202610{day:02d}090000",
                "open_pric": "100",
                "high_pric": "101",
                "low_pric": "99",
                "cur_prc": "100",
                "trde_qty": "10",
            }
        )
    rows.append(
        {
            "cntr_tm": "20261113090000",
            "open_pric": "100",
            "high_pric": "101",
            "low_pric": "80",
            "cur_prc": "90",
            "trde_qty": "10",
        }
    )
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.client = MagicMock()
    strat.client.get_minute_chart.return_value = rows
    strat._h4_cache = {}
    reason = strat._chart_4h_reason("005930", now=datetime(2026, 11, 13, 14, 0))
    strat.client.get_minute_chart.assert_called_once_with("005930", tic_scope="60")
    assert reason is not None
    assert reason.startswith("4시간 20이평 이탈")
    cached = strat._chart_4h_reason("005930", now=datetime(2026, 11, 13, 14, 5))
    assert cached == reason
    assert strat.client.get_minute_chart.call_count == 1
