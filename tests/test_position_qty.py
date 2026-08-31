"""목표가보다 비싼 1주는 자동매수하지 않는다."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from trading.scoring import CandidateView
from trading.strategy import AutoRunResult, AutoTradingStrategy


def _strategy(monkeypatch: pytest.MonkeyPatch) -> AutoTradingStrategy:
    import trading.strategy as strat_mod

    monkeypatch.setattr(strat_mod, "position_sizing_enabled", True)
    monkeypatch.setattr(strat_mod, "position_target_krw", 1_000_000)
    monkeypatch.setattr(strat_mod, "position_min_qty", 1)
    monkeypatch.setattr(strat_mod, "position_max_qty", 100)
    s = AutoTradingStrategy.__new__(AutoTradingStrategy)
    s.client = MagicMock()
    s.positions = MagicMock()
    s.journal = MagicMock()
    s._buy_count = 0
    s._trend_buy_count = 0
    s._crash_buy_count = 0
    s._cycle_ctx = None
    return s


def test_base_order_qty_skips_when_one_share_exceeds_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    assert strat._base_order_qty(1_652_000) == 0


def test_base_order_qty_buys_one_when_share_fits_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    assert strat._base_order_qty(800_000) == 1


def test_execute_buy_does_not_order_when_qty_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    result = AutoRunResult()
    cand = CandidateView(
        code="000660",
        name="SK하이닉스",
        rank=1,
        prev_rank=1,
        flu_rt=0.0,
        current_price=1_652_000,
        trade_value="1000000",
        raw={},
    )
    strat._execute_buy(cand, 12.0, "차트 12점", result)
    strat.client.buy_market.assert_not_called()
