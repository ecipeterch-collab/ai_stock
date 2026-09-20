"""Swing advise sells: propose below disaster, auto at -5%."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from trading.strategy import AutoRunResult, AutoTradingStrategy, HoldingView
from trading.trade_proposals import TradeProposalStore


def _holding(
    *,
    code: str,
    name: str,
    qty: int,
    profit: float,
    price: int = 100000,
) -> HoldingView:
    return HoldingView(
        code=code,
        name=name,
        qty=qty,
        sellable_qty=qty,
        profit_pct=profit,
        current_price=price,
        purchase_price=price,
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


def _strategy(tmp_path, monkeypatch: pytest.MonkeyPatch) -> AutoTradingStrategy:
    import trading.strategy as strat_mod

    monkeypatch.setattr(strat_mod, "is_scalping_mode", lambda: False)
    monkeypatch.setattr(strat_mod, "advise_sells_enabled", True)
    monkeypatch.setattr(strat_mod, "strategy_disaster_stop_pct", 5.0)
    monkeypatch.setattr(strat_mod, "advise_sell_ignore_cooldown_min", 20)
    s = AutoTradingStrategy.__new__(AutoTradingStrategy)
    s.client = MagicMock()
    s.positions = MagicMock()
    s.positions.holding_minutes.return_value = 90.0
    s.positions.is_overnight.return_value = False
    s.positions.get.side_effect = lambda code: _state(qty=10)
    s.positions.clear_exit_signal = MagicMock()
    s._error_notify_state = {}
    s.proposals = TradeProposalStore(tmp_path / "proposals.json")
    s._execute_sell = MagicMock(return_value=True)
    s._invalidate_holdings_cache = MagicMock()
    monkeypatch.setattr(s, "_is_eod_sell_all_time", lambda now=None: False)
    monkeypatch.setattr(s, "_is_eod_cut_loss_time", lambda now=None: False)
    monkeypatch.setattr(s, "_exit_volume_class", lambda code, reason: ("normal", None))
    return s


def test_soft_stop_proposes_and_does_not_sell(tmp_path, monkeypatch) -> None:
    strat = _strategy(tmp_path, monkeypatch)
    result = AutoRunResult()
    sold = strat._run_sell_phase(
        result,
        holdings=[_holding(code="001820", name="삼화콘덴서", qty=10, profit=-2.57)],
    )
    assert sold == 0
    strat._execute_sell.assert_not_called()
    assert any("【매도 제안】" in e for e in result.events)
    assert result.button_events
    pending = strat.proposals.get("001820")
    assert pending is not None
    assert pending.status == "pending"


def test_disaster_stop_auto_sells(tmp_path, monkeypatch) -> None:
    strat = _strategy(tmp_path, monkeypatch)
    result = AutoRunResult()
    sold = strat._run_sell_phase(
        result,
        holdings=[_holding(code="001820", name="삼화콘덴서", qty=10, profit=-5.01)],
    )
    assert sold == 1
    strat._execute_sell.assert_called_once()
    assert not any("【매도 제안】" in e for e in result.events)


def test_held_soft_stop_stays_quiet_disaster_still_sells(tmp_path, monkeypatch) -> None:
    strat = _strategy(tmp_path, monkeypatch)
    first = AutoRunResult()
    strat._run_sell_phase(
        first,
        holdings=[_holding(code="002990", name="금호건설", qty=10, profit=-2.6)],
    )
    prop = strat.proposals.get("002990")
    assert prop is not None
    strat.proposals.mark_held(prop.id)
    strat._execute_sell.reset_mock()
    quiet = AutoRunResult()
    sold = strat._run_sell_phase(
        quiet,
        holdings=[_holding(code="002990", name="금호건설", qty=10, profit=-2.65)],
    )
    assert sold == 0
    strat._execute_sell.assert_not_called()
    assert not any("【매도 제안】" in e for e in quiet.events)
    disaster = AutoRunResult()
    sold2 = strat._run_sell_phase(
        disaster,
        holdings=[_holding(code="002990", name="금호건설", qty=10, profit=-5.2)],
    )
    assert sold2 == 1
    strat._execute_sell.assert_called_once()


def test_duplicate_cycle_does_not_renotify(tmp_path, monkeypatch) -> None:
    strat = _strategy(tmp_path, monkeypatch)
    h = _holding(code="001820", name="삼화콘덴서", qty=10, profit=-2.57)
    first = AutoRunResult()
    strat._run_sell_phase(first, holdings=[h])
    second = AutoRunResult()
    strat._run_sell_phase(second, holdings=[h])
    assert sum(1 for e in first.events if "【매도 제안】" in e) == 1
    assert not any("【매도 제안】" in e for e in second.events)


def test_scalping_still_auto_sells_soft_stop(tmp_path, monkeypatch) -> None:
    import trading.strategy as strat_mod

    strat = _strategy(tmp_path, monkeypatch)
    monkeypatch.setattr(strat_mod, "is_scalping_mode", lambda: True)
    result = AutoRunResult()
    sold = strat._run_sell_phase(
        result,
        holdings=[_holding(code="001820", name="삼화콘덴서", qty=10, profit=-2.57)],
    )
    assert sold == 1
    strat._execute_sell.assert_called_once()
