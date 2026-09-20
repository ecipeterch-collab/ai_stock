"""Telegram sell callbacks and approved-sell execution."""

from __future__ import annotations

from unittest.mock import MagicMock

from trading.bot import TelegramTradingBot
from trading.strategy import AutoRunResult, AutoTradingStrategy, HoldingView
from trading.trade_proposals import TradeProposalStore
from tests.test_manual_orders import _bot_with_mocks


def _holding(*, sellable: int = 10) -> HoldingView:
    return HoldingView(
        code="001820",
        name="삼화콘덴서",
        qty=sellable,
        sellable_qty=sellable,
        profit_pct=-2.57,
        current_price=112064,
        purchase_price=115000,
        order_code="001820",
        raw={},
    )


def test_callback_sell_ok_invokes_execute() -> None:
    bot = _bot_with_mocks()
    bot.strategy.execute_approved_sell.return_value = "【자동매도】 완료"
    msg = bot.handle_callback_data("sell:ok:abc123def456")
    bot.strategy.execute_approved_sell.assert_called_once_with("abc123def456")
    assert "자동매도" in msg


def test_callback_missing_id_expired() -> None:
    bot = _bot_with_mocks()
    bot.strategy.execute_approved_sell.return_value = (
        "【매도 제안】 만료되었거나 이미 처리된 제안입니다."
    )
    msg = bot.handle_callback_data("sell:ok:missing")
    assert "만료" in msg


def test_callback_hold_and_ignore() -> None:
    bot = _bot_with_mocks()
    bot.handle_callback_data("sell:hold:pid1")
    bot.strategy.hold_sell_proposal.assert_called_once_with("pid1")
    bot.handle_callback_data("sell:no:pid2")
    bot.strategy.ignore_sell_proposal.assert_called_once_with("pid2")


def test_handle_update_answers_callback(monkeypatch) -> None:
    import trading.bot as bot_mod

    monkeypatch.setattr(bot_mod, "TARGET_CHAT_ID", 123)
    answered: list[tuple] = []
    sent: list[str] = []
    monkeypatch.setattr(
        bot_mod,
        "answer_callback_query",
        lambda cq_id, text="": answered.append((cq_id, text)) or {"ok": True},
    )
    monkeypatch.setattr(bot_mod, "send_message", lambda text, **k: sent.append(text))
    bot = _bot_with_mocks()
    bot.strategy.execute_approved_sell.return_value = "매도 완료"
    bot._handle_update(
        {
            "callback_query": {
                "id": "cq1",
                "data": "sell:ok:abc",
                "message": {"chat": {"id": 123}},
            }
        }
    )
    assert answered == [("cq1", "매도 완료")]
    assert sent == ["매도 완료"]


def test_notify_cycle_attaches_reply_markup(monkeypatch) -> None:
    import trading.bot as bot_mod

    monkeypatch.setattr(bot_mod, "notify_on_auto_events_only", True)
    sent: list[tuple] = []
    bot = _bot_with_mocks()

    def _send(text, reply_markup=None, **_k):
        sent.append((text, reply_markup))
        return {"ok": True}

    bot.notify = TelegramTradingBot.notify.__get__(bot, TelegramTradingBot)
    monkeypatch.setattr(bot_mod, "send_message", _send)
    result = AutoRunResult()
    markup = {"inline_keyboard": [[{"text": "매도", "callback_data": "sell:ok:x"}]]}
    result.add_button_event("【매도 제안】 삼화", markup)
    bot._notify_cycle_events(result)
    assert sent == [("【매도 제안】 삼화", markup)]


def test_execute_approved_sell_zero_qty_keeps_pending(tmp_path) -> None:
    store = TradeProposalStore(tmp_path / "p.json")
    prop, _ = store.upsert_pending(
        code="001820",
        name="삼화콘덴서",
        qty=1000,
        reason="손절 (-2.57% <= -2.5%)",
        profit_pct=-2.57,
        price=112064,
    )
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.proposals = store
    strat.positions = MagicMock()
    strat._parse_holdings = MagicMock(return_value=[_holding(sellable=0)])
    strat._execute_sell = MagicMock(return_value=True)
    strat._invalidate_holdings_cache = MagicMock()
    msg = strat.execute_approved_sell(prop.id)
    assert "매도 불가" in msg
    assert store.get_by_id(prop.id).status == "pending"
    strat._execute_sell.assert_not_called()


def test_execute_approved_sell_marks_done(tmp_path) -> None:
    store = TradeProposalStore(tmp_path / "p.json")
    prop, _ = store.upsert_pending(
        code="001820",
        name="삼화콘덴서",
        qty=10,
        reason="손절 (-2.57% <= -2.5%)",
        profit_pct=-2.57,
        price=112064,
    )
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.proposals = store
    strat.positions = MagicMock()
    strat._parse_holdings = MagicMock(return_value=[_holding(sellable=10)])
    strat._execute_sell = MagicMock(
        side_effect=lambda holding, reason, qty, result, **k: result.add_event("【자동매도】 ok")
        or True
    )
    strat._invalidate_holdings_cache = MagicMock()
    msg = strat.execute_approved_sell(prop.id)
    assert "【자동매도】" in msg
    assert store.get_by_id(prop.id).status == "done"
    strat._execute_sell.assert_called_once()


def test_get_pending_skips_done(tmp_path) -> None:
    store = TradeProposalStore(tmp_path / "p.json")
    prop, _ = store.upsert_pending(
        code="001820",
        name="삼화콘덴서",
        qty=10,
        reason="손절",
        profit_pct=-2.6,
        price=1,
    )
    store.mark_done(prop.id)
    assert store.get_pending("001820") is None
    assert store.get("001820") is not None
