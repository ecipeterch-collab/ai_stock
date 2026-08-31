"""시총 대형 vs 그 외 매도 규칙."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from trading.mega_cap import is_mega_cap
from trading.strategy import AutoTradingStrategy, HoldingView


def _strategy(monkeypatch: pytest.MonkeyPatch) -> AutoTradingStrategy:
    import trading.strategy as strat_mod

    monkeypatch.setattr(strat_mod, "is_scalping_mode", lambda: False)
    s = AutoTradingStrategy.__new__(AutoTradingStrategy)
    s.client = MagicMock()
    s.positions = MagicMock()
    s.positions.holding_minutes.return_value = 90.0
    s.positions.is_overnight.return_value = False
    monkeypatch.setattr(s, "_is_eod_sell_all_time", lambda now=None: False)
    monkeypatch.setattr(s, "_is_eod_cut_loss_time", lambda now=None: False)
    return s


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


def _state(*, qty: int, peak: float, be_scaled: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        entry_qty=qty,
        tp_stage=0,
        peak_profit_pct=peak,
        be_scaled=be_scaled,
        partial_sold=False,
    )


def test_is_mega_cap_strips_a_prefix() -> None:
    assert is_mega_cap("005930") is True
    assert is_mega_cap("A005930") is True
    assert is_mega_cap("002990") is False


def test_mega_holds_through_minus_two_point_six(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="005930", name="삼성전자", qty=2, profit=-2.6),
        _state(qty=2, peak=0.0),
    )
    assert reason is None
    assert qty == 0


def test_other_stops_at_minus_two_point_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="002990", name="금호건설", qty=10, profit=-2.6),
        _state(qty=10, peak=0.0),
    )
    assert reason is not None
    assert reason.startswith("손절")
    assert "-2.5" in reason
    assert qty == 10


def test_other_tight_trail_from_peak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="002990", name="금호건설", qty=10, profit=1.8),
        _state(qty=10, peak=3.0),
    )
    assert reason is not None
    assert "중소형 트레일링" in reason
    assert qty == 10


def test_mega_skips_four_percent_take_profit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="005930", name="삼성전자", qty=4, profit=4.05),
        _state(qty=4, peak=4.05),
    )
    assert reason is None or "수익실현" not in reason
    assert qty == 0 or reason is None


def test_other_eod_flattens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    monkeypatch.setattr(strat, "_is_eod_sell_all_time", lambda now=None: True)
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="002990", name="금호건설", qty=10, profit=0.8),
        _state(qty=10, peak=1.2),
    )
    assert reason is not None
    assert "장마감 전량 청산" in reason
    assert qty == 10


def test_mega_skips_eod_flatten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    monkeypatch.setattr(strat, "_is_eod_sell_all_time", lambda now=None: True)
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="005930", name="삼성전자", qty=4, profit=0.8),
        _state(qty=4, peak=1.2),
    )
    assert reason is None
    assert qty == 0


def test_other_overnight_flattens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    strat.positions.is_overnight.return_value = True
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="002990", name="금호건설", qty=10, profit=0.4),
        _state(qty=10, peak=0.8),
    )
    assert reason is not None
    assert "오버나잇" in reason
    assert qty == 10


def test_mega_overnight_not_flattened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    strat.positions.is_overnight.return_value = True
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="005930", name="삼성전자", qty=4, profit=0.4),
        _state(qty=4, peak=0.8),
    )
    assert reason is None
    assert qty == 0


def test_mega_skips_eod_cut_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strat = _strategy(monkeypatch)
    monkeypatch.setattr(strat, "_is_eod_cut_loss_time", lambda now=None: True)
    reason, qty, _ = strat._evaluate_sell(
        _holding(code="005930", name="삼성전자", qty=4, profit=-0.8),
        _state(qty=4, peak=0.4),
    )
    assert reason is None
    assert qty == 0
