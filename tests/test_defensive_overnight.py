"""오버나잇 스윙은 방어모드 제외, 손절만 적용."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from trading.news_analyzer import MarketNewsContext
from trading.position_tracker import PositionTracker
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


def _holding(*, code: str, name: str, qty: int, profit: float) -> HoldingView:
    return HoldingView(
        code=code,
        name=name,
        qty=qty,
        sellable_qty=qty,
        profit_pct=profit,
        current_price=218500,
        purchase_price=225563,
        order_code=code,
        raw={},
    )


def _state(*, qty: int, peak: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        entry_qty=qty,
        tp_stage=0,
        peak_profit_pct=peak,
        be_scaled=False,
        partial_sold=False,
    )


def test_is_overnight_true_when_entry_was_previous_day(tmp_path) -> None:
    tracker = PositionTracker(path=tmp_path / "positions.json")
    tracker.register("035420", "NAVER", 225563, entry_qty=4)
    state = tracker.get("035420")
    assert state is not None
    state.entry_time = "2026-08-14T10:05:43"
    tracker.save()
    now = datetime(2026, 8, 18, 11, 45, 0)
    assert tracker.is_overnight("035420", now=now) is True


def test_is_overnight_false_on_same_calendar_day(tmp_path) -> None:
    tracker = PositionTracker(path=tmp_path / "positions.json")
    tracker.register("005380", "현대차", 454000, entry_qty=2)
    state = tracker.get("005380")
    assert state is not None
    state.entry_time = "2026-08-18T09:47:22"
    tracker.save()
    now = datetime(2026, 8, 18, 11, 44, 0)
    assert tracker.is_overnight("005380", now=now) is False


def test_defensive_skips_overnight_hold_uses_stop_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    strat.positions.is_overnight.return_value = True
    strat.positions.holding_minutes.return_value = 5000.0
    news = MarketNewsContext(
        sentiment=-0.88,
        risk_score=0.52,
        defensive_mode=True,
    )
    reason, qty, _stage = strat._evaluate_sell(
        _holding(code="035420", name="NAVER", qty=4, profit=-3.10),
        _state(qty=4),
        news,
    )
    assert reason is None
    assert qty == 0


def test_defensive_still_sells_same_day_loser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    strat.positions.is_overnight.return_value = False
    news = MarketNewsContext(
        sentiment=-0.88,
        risk_score=0.52,
        defensive_mode=True,
    )
    reason, qty, _stage = strat._evaluate_sell(
        _holding(code="005380", name="현대차", qty=2, profit=-2.97),
        _state(qty=2),
        news,
    )
    assert reason is not None
    assert "방어모드" in reason
    assert qty == 2
