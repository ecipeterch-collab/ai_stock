"""웹/텔레그램 수동 /buy /sell 가드."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from trading.bot import TelegramTradingBot
from web.commands import run_command


def _bot_with_mocks() -> TelegramTradingBot:
    bot = TelegramTradingBot.__new__(TelegramTradingBot)
    bot.client = MagicMock()
    bot.client.normalize_stock_code = lambda c: c.lstrip("A")[-6:].zfill(6)
    bot.client.parse_qty = lambda v: int(str(v).replace(",", "") or 0)
    bot.client.buy_market = MagicMock()
    bot.client.sell_market = MagicMock()
    bot.client.get_holdings = MagicMock(return_value=[])
    bot.strategy = MagicMock()
    bot.strategy.journal = MagicMock()
    bot.strategy.positions = MagicMock()
    bot.strategy.check_order_fill = MagicMock(return_value=None)
    bot.strategy._invalidate_holdings_cache = MagicMock()
    bot.notify = MagicMock()
    return bot


def test_cmd_buy_blocks_when_market_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import trading.bot as bot_mod

    monkeypatch.setattr(bot_mod, "is_market_open", lambda now=None: False)
    monkeypatch.setattr(bot_mod, "market_status_text", lambda now=None: "장마감")
    bot = _bot_with_mocks()

    msg = bot._cmd_buy(["005930", "1"])

    assert "장마감" in msg or "장중" in msg
    assert "매수" in msg
    bot.client.buy_market.assert_not_called()


def test_cmd_sell_blocks_when_market_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import trading.bot as bot_mod

    monkeypatch.setattr(bot_mod, "is_market_open", lambda now=None: False)
    monkeypatch.setattr(bot_mod, "market_status_text", lambda now=None: "장마감")
    bot = _bot_with_mocks()
    bot.client.get_holdings.return_value = [
        {"stk_cd": "035420", "trde_able_qty": "4", "stk_nm": "NAVER"}
    ]

    msg = bot._cmd_sell(["035420", "1"])

    assert "장마감" in msg or "장중" in msg
    bot.client.sell_market.assert_not_called()


def test_cmd_buy_rejects_non_positive_qty(monkeypatch: pytest.MonkeyPatch) -> None:
    import trading.bot as bot_mod

    monkeypatch.setattr(bot_mod, "is_market_open", lambda now=None: True)
    bot = _bot_with_mocks()

    msg = bot._cmd_buy(["005930", "0"])

    assert "수량" in msg
    bot.client.buy_market.assert_not_called()


def test_run_command_marks_api_error_as_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = MagicMock()
    fake.handle_command.return_value = (
        "API 오류: kt10000 오류: [2000](RC4058:모의투자 장종료)"
    )
    monkeypatch.setattr("web.commands._get_bot", lambda: fake)

    result = run_command("/buy 005930 1")

    assert result["ok"] is False
    assert "장종료" in result["text"] or "API 오류" in result["text"]


def test_run_command_marks_market_closed_guard_as_not_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = MagicMock()
    fake.handle_command.return_value = (
        "【매수 불가】 현재 장마감입니다.\n모의투자는 정규장(09:00~15:30)에만 주문됩니다."
    )
    monkeypatch.setattr("web.commands._get_bot", lambda: fake)

    result = run_command("/buy 005930 1")

    assert result["ok"] is False
