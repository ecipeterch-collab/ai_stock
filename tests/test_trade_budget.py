"""하루 매수 금액은 보유자금의 비율로 제한한다."""

from __future__ import annotations

import json
from datetime import date

import pytest

from trading.trade_budget import (
    amount_from_pct,
    funds_from_balances,
    today_buy_notional,
)
from trading.trade_journal import TradeEvent


def test_default_slices_are_ten_percent_of_funds() -> None:
    assert amount_from_pct(10_000_000, 10) == 1_000_000
    assert amount_from_pct(10_000_000, 2.5) == 250_000


def test_funds_use_settled_cash_plus_holdings() -> None:
    assert funds_from_balances(cash=4_000_000, holdings_eval=6_000_000, fallback=1) == 10_000_000
    assert funds_from_balances(cash=0, holdings_eval=0, fallback=500_000_000) == 500_000_000


def test_today_buy_notional_ignores_other_days() -> None:
    events = [
        TradeEvent(ts="2026-11-14T10:00:00", event="buy_order", qty=2, price=100_000),
        TradeEvent(ts="2026-11-13T10:00:00", event="buy_order", qty=9, price=100_000),
        TradeEvent(ts="2026-11-14T11:00:00", event="sell_order", qty=2, price=100_000),
    ]
    assert today_buy_notional(events, date(2026, 11, 14)) == 200_000


def test_budget_settings_round_trip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import trading.mode_settings as ms
    from trading.account_settings import (
        get_daily_trade_pct,
        get_order_size_pct,
        set_daily_trade_pct,
        set_order_size_pct,
    )

    path = tmp_path / "runtime_settings.json"
    path.write_text(json.dumps({"strategy_mode": "swing"}), encoding="utf-8")
    monkeypatch.setattr(ms, "SETTINGS_FILE", path)

    assert get_daily_trade_pct() == 10
    assert get_order_size_pct() == 10
    assert set_daily_trade_pct(8) == 8
    assert set_order_size_pct(2.5) == 2.5
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["strategy_mode"] == "swing"
    assert saved["daily_trade_pct"] == 8
    assert saved["order_size_pct"] == 2.5
    with pytest.raises(ValueError):
        set_daily_trade_pct(0)
    with pytest.raises(ValueError):
        set_order_size_pct(101)


def test_order_qty_uses_percent_and_stops_at_daily_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trading.strategy as strat_mod
    from trading.strategy import AutoTradingStrategy

    monkeypatch.setattr(strat_mod, "get_daily_trade_pct", lambda: 10.0)
    monkeypatch.setattr(strat_mod, "get_order_size_pct", lambda: 10.0)
    monkeypatch.setattr(strat_mod, "position_sizing_enabled", True)
    monkeypatch.setattr(strat_mod, "position_min_qty", 1)
    monkeypatch.setattr(strat_mod, "position_max_qty", 100)
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    monkeypatch.setattr(strat, "_funds_krw", lambda: 10_000_000)
    monkeypatch.setattr(strat, "_spent_today", lambda: 0)
    monkeypatch.setattr(strat, "_channel_scale_mult", lambda channel: 1.0)
    assert strat._calc_order_qty(100_000) == 10

    monkeypatch.setattr(strat, "_spent_today", lambda: 800_000)
    assert strat._calc_order_qty(100_000) == 2
    assert strat._calc_order_qty(250_000) == 0


def test_budget_command_sets_daily_and_order_pct(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trading.mode_settings as ms
    from trading.bot import TelegramTradingBot

    monkeypatch.setattr(ms, "SETTINGS_FILE", tmp_path / "runtime_settings.json")
    bot = TelegramTradingBot.__new__(TelegramTradingBot)
    bot.strategy = type("S", (), {"budget_text": lambda self: "【거래 비율】 보유자금 1원"})()

    shown = bot._cmd_budget([])
    assert "거래 비율" in shown

    day = bot._cmd_budget(["10"])
    assert "하루 한도 10%" in day
    order = bot._cmd_budget(["order", "2"])
    assert "1회 매수 2%" in order
