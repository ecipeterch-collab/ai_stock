"""수동매수 가격 누락·지정가 실패 후 시장가 재시도 저널 보정."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kiwoom.client import KiwoomAPIError
from trading.account_pnl import _apply_fill_prices, enrich_closed_trade_fees
from trading.bot import TelegramTradingBot
from trading.journal_stats import build_closed_trades
from trading.strategy import AutoRunResult, AutoTradingStrategy, HoldingView
from trading.trade_journal import TradeEvent


def _ev(**kwargs) -> TradeEvent:
    base = dict(
        ts="2026-08-13T09:39:55",
        event="buy_order",
        code="",
        name="",
        qty=None,
        price=None,
        profit_pct=None,
        reason="",
        ord_no="",
    )
    base.update(kwargs)
    return TradeEvent(**base)


def test_apply_fill_prices_patches_none_buy_price() -> None:
    events = [
        _ev(
            event="buy_order",
            code="005930",
            name="삼성전자",
            qty=100,
            price=None,
            reason="수동매수(웹/텔레그램)",
            ord_no="0050303",
        ),
        _ev(
            ts="2026-08-13T09:43:24",
            event="fill",
            code="005930",
            name="삼성전자",
            qty=100,
            price=265248,
            ord_no="0050303",
        ),
    ]

    patched = _apply_fill_prices(events)

    assert patched[0].event == "buy_order"
    assert patched[0].price == 265248


def test_closed_trade_uses_fill_price_when_buy_price_missing() -> None:
    events = [
        _ev(
            event="buy_order",
            code="005930",
            name="삼성전자",
            qty=100,
            price=None,
            reason="수동매수(웹/텔레그램)",
            ord_no="0050303",
        ),
        _ev(
            ts="2026-08-13T09:43:24",
            event="fill",
            code="005930",
            name="삼성전자",
            qty=100,
            price=265248,
            ord_no="0050303",
        ),
        _ev(
            ts="2026-08-14T10:13:11",
            event="sell_order",
            code="005930",
            name="삼성전자",
            qty=50,
            price=266640,
            profit_pct=0.52,
            reason="본전스탑 50% 매도",
            ord_no="0071803",
        ),
    ]

    closed = build_closed_trades(events)

    assert len(closed) == 1
    assert closed[0].entry_price == 265248
    assert closed[0].sell_price == 266640
    assert closed[0].pnl_krw == (266640 - 265248) * 50
    row = enrich_closed_trade_fees(closed[0])
    assert row["net_pnl_krw"] != 0


def test_unmatched_fill_closes_open_lot_like_sell() -> None:
    events = [
        _ev(
            ts="2026-08-13T10:48:00",
            event="buy_order",
            code="066570",
            name="LG전자",
            qty=4,
            price=205500,
            reason="스윙 스캔",
            ord_no="0083114",
        ),
        _ev(
            ts="2026-08-13T10:53:36",
            event="fill",
            code="066570",
            name="LG전자",
            qty=4,
            price=205500,
            ord_no="0083114",
        ),
        _ev(
            ts="2026-08-14T09:13:39",
            event="fill",
            code="066570",
            name="LG전자",
            qty=4,
            price=216250,
            ord_no="0023467",
        ),
    ]

    closed = build_closed_trades(events)

    assert len(closed) == 1
    assert closed[0].code == "066570"
    assert closed[0].entry_price == 205500
    assert closed[0].sell_price == 216250
    assert closed[0].qty == 4
    assert closed[0].pnl_krw == (216250 - 205500) * 4
    assert "주문 로그 없음" in closed[0].sell_reason


def test_buy_fill_does_not_close_lot() -> None:
    events = [
        _ev(
            event="buy_order",
            code="005930",
            name="삼성전자",
            qty=100,
            price=265248,
            ord_no="0050303",
        ),
        _ev(
            ts="2026-08-13T09:43:24",
            event="fill",
            code="005930",
            name="삼성전자",
            qty=100,
            price=265248,
            ord_no="0050303",
        ),
        _ev(
            ts="2026-08-13T21:19:02",
            event="fill",
            code="005930",
            name="삼성전자",
            qty=100,
            price=265248,
            ord_no="0050303",
        ),
    ]

    assert build_closed_trades(events) == []


def test_cmd_buy_logs_fill_price(monkeypatch: pytest.MonkeyPatch) -> None:
    import trading.bot as bot_mod

    monkeypatch.setattr(bot_mod, "is_market_open", lambda now=None: True)
    bot = TelegramTradingBot.__new__(TelegramTradingBot)
    bot.client = MagicMock()
    bot.client.normalize_stock_code = lambda c: c.lstrip("A")[-6:].zfill(6)
    bot.client.buy_market.return_value = {"ord_no": "0050303", "return_msg": "ok"}
    bot.strategy = MagicMock()
    bot.strategy.check_order_fill.return_value = "체결"
    bot.strategy.latest_fill_price.return_value = 265248
    bot.strategy.journal = MagicMock()
    bot.strategy.positions = MagicMock()
    bot.strategy._invalidate_holdings_cache = MagicMock()
    bot.notify = MagicMock()

    bot._cmd_buy(["005930", "100"])

    buy_calls = [
        kwargs
        for args, kwargs in bot.strategy.journal.log.call_args_list
        if args and args[0] == "buy_order"
    ]
    assert buy_calls
    assert buy_calls[0]["price"] == 265248
    bot.strategy.positions.register.assert_called()
    assert bot.strategy.positions.register.call_args.kwargs.get("entry_price") in (
        265248,
        None,
    ) or bot.strategy.positions.register.call_args.args[2] == 265248


def test_execute_sell_market_fallback_logs_sell_order() -> None:
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.client = MagicMock()
    strat.client.normalize_stock_code = lambda c: c
    strat.client.sell_limit.side_effect = KiwoomAPIError("지정가 거부")
    strat.client.sell_market.return_value = {
        "ord_no": "0023467",
        "return_msg": "ok",
    }
    strat.journal = MagicMock()
    strat.positions = MagicMock()
    strat.positions.get.return_value = None
    strat.check_order_fill = MagicMock(return_value=None)
    strat._exit_limit_price = MagicMock(return_value=215000)

    holding = HoldingView(
        code="066570",
        name="LG전자",
        qty=4,
        sellable_qty=4,
        profit_pct=5.23,
        current_price=216250,
        purchase_price=205500,
        order_code="066570",
        raw={},
    )

    ok = strat._execute_sell(holding, "수익보호 트레일링", 4, AutoRunResult())

    assert ok is True
    sell_calls = [
        (args, kwargs)
        for args, kwargs in strat.journal.log.call_args_list
        if args and args[0] == "sell_order"
    ]
    assert sell_calls
    _args, kwargs = sell_calls[0]
    assert kwargs["code"] == "066570"
    assert kwargs["qty"] == 4
    assert kwargs["ord_no"] == "0023467"
    assert kwargs["price"] == 216250
    assert "시장가" in kwargs["reason"]
