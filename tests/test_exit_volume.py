"""본전스탑·수익보호 청산을 분봉 거래량으로 확인."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from trading.chart_signals import Candle, classify_exit_volume, latest_vs_avg_volume_ratio
from trading.strategy import AutoTradingStrategy


def _bars(volumes: list[int]) -> list[Candle]:
    base = datetime(2026, 8, 14, 10, 0)
    out: list[Candle] = []
    for i, vol in enumerate(volumes):
        ts = (base + timedelta(minutes=5 * i)).strftime("%Y%m%d%H%M%S")
        out.append(
            Candle(ts=ts, open=100, high=101, low=99, close=100, volume=vol)
        )
    return out


def test_volume_ratio_is_last_bar_over_prior_average() -> None:
    candles = _bars([100] * 10 + [50])
    assert latest_vs_avg_volume_ratio(candles, lookback=10) == pytest.approx(0.5)


def test_volume_ratio_none_when_too_few_bars() -> None:
    assert latest_vs_avg_volume_ratio(_bars([100, 80]), lookback=10) is None


def test_volume_ratio_uses_available_bars_when_lookback_longer() -> None:
    candles = _bars([100] * 8 + [40])
    assert latest_vs_avg_volume_ratio(candles, lookback=20) == pytest.approx(0.4)


def test_classify_missing_ratio_as_normal() -> None:
    assert classify_exit_volume(None, light_ratio=0.8, heavy_ratio=1.5) == "normal"


def test_classify_light_and_heavy_volume() -> None:
    assert classify_exit_volume(0.5, light_ratio=0.8, heavy_ratio=1.5) == "light"
    assert classify_exit_volume(1.0, light_ratio=0.8, heavy_ratio=1.5) == "normal"
    assert classify_exit_volume(1.6, light_ratio=0.8, heavy_ratio=1.5) == "heavy"


def _confirm_strategy(tmp_path) -> AutoTradingStrategy:
    from trading.position_tracker import PositionTracker

    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.positions = PositionTracker(path=tmp_path / "positions.json")
    strat.positions.register("005930", "삼성전자", 265248, entry_qty=100)
    return strat


def test_light_volume_does_not_count_and_resets_confirm(tmp_path) -> None:
    strat = _confirm_strategy(tmp_path)
    reason = "본전스탑 50% 매도 (고점 3.30% → 현재 0.47%)"

    assert (
        strat._confirm_exit_signal("005930", reason, volume_class="normal") is None
    )
    assert (
        strat._confirm_exit_signal("005930", reason, volume_class="light") is None
    )
    assert (
        strat._confirm_exit_signal("005930", reason, volume_class="normal") is None
    )


def test_heavy_volume_fires_on_first_touch(tmp_path) -> None:
    strat = _confirm_strategy(tmp_path)
    reason = "수익보호 트레일링 (고점 5.22% → 현재 3.48%)"
    assert (
        strat._confirm_exit_signal("005930", reason, volume_class="heavy") == reason
    )


def test_exit_volume_class_light_from_minute_bars() -> None:
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.chart = MagicMock()
    strat.chart.load_minute_candles.return_value = _bars([100] * 20 + [50])

    kind, ratio = strat._exit_volume_class(
        "005930", "본전스탑 50% 매도 (고점 3.30% → 현재 0.47%)"
    )
    assert kind == "light"
    assert ratio == pytest.approx(0.5)


def test_exit_volume_class_heavy_from_minute_bars() -> None:
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.chart = MagicMock()
    strat.chart.load_minute_candles.return_value = _bars([100] * 20 + [180])

    kind, ratio = strat._exit_volume_class(
        "005930", "수익보호 트레일링 (고점 5.22% → 현재 3.48%)"
    )
    assert kind == "heavy"
    assert ratio == pytest.approx(1.8)


def test_exit_volume_class_chart_error_falls_back_to_normal() -> None:
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.chart = MagicMock()
    strat.chart.load_minute_candles.side_effect = RuntimeError("chart down")
    kind, ratio = strat._exit_volume_class(
        "005930", "본전스탑 50% 매도 (고점 3.30% → 현재 0.47%)"
    )
    assert kind == "normal"
    assert ratio is None


def test_exit_volume_class_skips_stop_loss() -> None:
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.chart = MagicMock()
    kind, ratio = strat._exit_volume_class("005930", "손절 (-4.20% <= -4.0%)")
    assert kind == "normal"
    assert ratio is None
    strat.chart.load_minute_candles.assert_not_called()
