"""본전스탑 50% 스케일아웃 후 잔량 트레일링."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from trading.strategy import AutoTradingStrategy, HoldingView


def _strategy(monkeypatch: pytest.MonkeyPatch) -> AutoTradingStrategy:
    import trading.strategy as strat_mod

    monkeypatch.setattr(strat_mod, "is_scalping_mode", lambda: False)
    s = AutoTradingStrategy.__new__(AutoTradingStrategy)
    s.client = MagicMock()
    s.positions = MagicMock()
    s.positions.holding_minutes.return_value = 90.0
    s.positions.is_overnight.return_value = False
    return s


def _holding(*, qty: int, profit: float, code: str = "005930", name: str = "삼성전자") -> HoldingView:
    return HoldingView(
        code=code,
        name=name,
        qty=qty,
        sellable_qty=qty,
        profit_pct=profit,
        current_price=15370,
        purchase_price=15390,
        order_code=code,
        raw={},
    )


def _state(*, qty: int, peak: float, be_scaled: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        entry_qty=qty,
        tp_stage=0,
        peak_profit_pct=peak,
        be_scaled=be_scaled,
        partial_sold=False,
    )


def test_breakeven_stop_sells_half_when_qty_ge_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, stage = strat._evaluate_sell(
        _holding(qty=64, profit=0.40),
        _state(qty=64, peak=4.35),
    )

    assert reason is not None
    assert reason.startswith("본전스탑")
    assert "50%" in reason
    assert qty == 32
    assert stage is None


def test_breakeven_stop_sells_all_when_one_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, stage = strat._evaluate_sell(
        _holding(qty=1, profit=0.40),
        _state(qty=1, peak=4.35),
    )

    assert reason is not None
    assert reason.startswith("본전스탑")
    assert qty == 1
    assert stage is None


def test_breakeven_stop_skips_when_profit_below_round_trip_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """왕복비용(약 0.23%) 아래면 본전스탑을 걸지 않는다."""
    strat = _strategy(monkeypatch)
    reason, qty, _stage = strat._evaluate_sell(
        _holding(qty=1, profit=0.09),
        _state(qty=1, peak=4.93),
    )
    assert reason is None
    assert qty == 0


def test_breakeven_remainder_trails_after_scale_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, stage = strat._evaluate_sell(
        _holding(qty=32, profit=-0.13),
        _state(qty=64, peak=4.35, be_scaled=True),
    )

    assert reason is not None
    assert "잔량 트레일링" in reason
    assert qty == 32
    assert stage is None


def test_breakeven_remainder_holds_when_above_trail_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    # 고점 4.35% − 1.5%p = 2.85% 바닥. 현재 3.2%면 잔량 유지.
    reason, qty, _stage = strat._evaluate_sell(
        _holding(qty=32, profit=3.2),
        _state(qty=64, peak=4.35, be_scaled=True),
    )

    assert reason is None
    assert qty == 0


def test_protect_trailing_still_exits_full_before_breakeven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, _stage = strat._evaluate_sell(
        _holding(qty=2, profit=3.32),
        _state(qty=2, peak=5.15),
    )

    assert reason is not None
    assert "수익보호 트레일링" in reason
    assert qty == 2


def test_mark_be_scaled_persists(tmp_path) -> None:
    from trading.position_tracker import PositionTracker

    path = tmp_path / "positions.json"
    tracker = PositionTracker(path=path)
    tracker.register("002990", "금호건설", 15390, entry_qty=64)
    tracker.mark_be_scaled("002990")

    reloaded = PositionTracker(path=path)
    state = reloaded.get("002990")
    assert state is not None
    assert state.be_scaled is True


def test_be_remainder_holds_samsung_style_shallow_dip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """고점 3.30% 잔량 바닥 max(0, 3.30-3.0)=0.30%. +0.66%면 유지."""
    strat = _strategy(monkeypatch)
    reason, qty, _stage = strat._evaluate_sell(
        _holding(qty=50, profit=0.66),
        _state(qty=100, peak=3.30, be_scaled=True),
    )

    assert reason is None
    assert qty == 0


def test_be_remainder_exits_below_zero_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, _stage = strat._evaluate_sell(
        _holding(qty=50, profit=-0.10),
        _state(qty=100, peak=3.30, be_scaled=True),
    )

    assert reason is not None
    assert "잔량 트레일링" in reason
    assert qty == 50


def test_exit_confirm_blocks_first_touch(tmp_path) -> None:
    from trading.position_tracker import PositionTracker

    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.positions = PositionTracker(path=tmp_path / "positions.json")
    strat.positions.register("005930", "삼성전자", 265248, entry_qty=100)

    first = strat._confirm_exit_signal(
        "005930", "본전스탑 50% 매도 (고점 3.30% → 현재 0.47%)"
    )
    assert first is None


def test_exit_confirm_fires_on_second_touch(tmp_path) -> None:
    from trading.position_tracker import PositionTracker

    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.positions = PositionTracker(path=tmp_path / "positions.json")
    strat.positions.register("005930", "삼성전자", 265248, entry_qty=100)
    reason = "본전스탑 50% 매도 (고점 3.30% → 현재 0.47%)"

    assert strat._confirm_exit_signal("005930", reason) is None
    assert strat._confirm_exit_signal("005930", reason) == reason


def test_exit_confirm_resets_after_recovery(tmp_path) -> None:
    from trading.position_tracker import PositionTracker

    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.positions = PositionTracker(path=tmp_path / "positions.json")
    strat.positions.register("005930", "삼성전자", 265248, entry_qty=100)
    reason = "수익보호 트레일링 (고점 5.22% → 현재 3.48%)"

    assert strat._confirm_exit_signal("005930", reason) is None
    assert strat._confirm_exit_signal("005930", None) is None
    assert strat._confirm_exit_signal("005930", reason) is None


def test_stop_loss_skips_exit_confirm(tmp_path) -> None:
    from trading.position_tracker import PositionTracker

    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.positions = PositionTracker(path=tmp_path / "positions.json")
    strat.positions.register("005930", "삼성전자", 265248, entry_qty=100)

    reason = "손절 (-4.20% <= -4.0%)"
    assert strat._confirm_exit_signal("005930", reason) == reason


def test_mega_does_not_take_profit_at_four_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, stage = strat._evaluate_sell(
        _holding(qty=10, profit=4.05),
        _state(qty=10, peak=4.05),
    )

    assert reason is None
    assert qty == 0
    assert stage is None
