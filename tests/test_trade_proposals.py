"""Advise-mode sell proposals and buy-watchlist copy."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from trading.trade_proposals import (
    TradeProposalStore,
    format_buy_watchlist,
    format_sell_proposal_text,
    sell_proposal_category,
    sell_proposal_markup,
)


def test_category_stop_and_eod() -> None:
    assert sell_proposal_category("손절 (-2.57% <= -2.5%)") == "stop_loss"
    assert sell_proposal_category("장마감 전량 청산 (15:20)") == "eod"
    assert sell_proposal_category("본전스탑 50% 매도 (고점 3.13% → 현재 0.46%)") == "breakeven"


def test_upsert_pending_does_not_renotify_same_category(tmp_path: Path) -> None:
    store = TradeProposalStore(tmp_path / "p.json")
    first, notify = store.upsert_pending(
        code="001820",
        name="삼화콘덴서",
        qty=1000,
        reason="손절 (-2.57% <= -2.5%)",
        profit_pct=-2.57,
        price=112064,
    )
    assert notify is True
    assert first.status == "pending"
    second, notify2 = store.upsert_pending(
        code="001820",
        name="삼화콘덴서",
        qty=1000,
        reason="손절 (-2.60% <= -2.5%)",
        profit_pct=-2.6,
        price=111700,
    )
    assert notify2 is False
    assert second.id == first.id
    assert second.profit_pct == -2.6


def test_held_blocks_same_category_until_next_day(tmp_path: Path) -> None:
    store = TradeProposalStore(tmp_path / "p.json")
    prop, _ = store.upsert_pending(
        code="002990",
        name="금호건설",
        qty=10,
        reason="손절 (-2.60% <= -2.5%)",
        profit_pct=-2.6,
        price=78000,
    )
    store.mark_held(prop.id, today=date(2026, 9, 20))
    assert store.is_held("002990", "stop_loss", date(2026, 9, 20)) is True
    _, notify = store.upsert_pending(
        code="002990",
        name="금호건설",
        qty=10,
        reason="손절 (-2.70% <= -2.5%)",
        profit_pct=-2.7,
        price=77000,
        today=date(2026, 9, 20),
    )
    assert notify is False
    store.reset_day(date(2026, 9, 21))
    assert store.is_held("002990", "stop_loss", date(2026, 9, 21)) is False


def test_ignore_cooldown(tmp_path: Path) -> None:
    store = TradeProposalStore(tmp_path / "p.json")
    prop, _ = store.upsert_pending(
        code="052690",
        name="한전기술",
        qty=7,
        reason="장마감 전량 청산 (15:20)",
        profit_pct=-0.84,
        price=137600,
    )
    now = datetime(2026, 9, 17, 15, 21)
    store.mark_ignored(prop.id, now=now)
    _, notify_soon = store.upsert_pending(
        code="052690",
        name="한전기술",
        qty=7,
        reason="장마감 전량 청산 (15:20)",
        profit_pct=-0.9,
        price=137500,
        now=now + timedelta(minutes=10),
        ignore_cooldown_min=20,
    )
    assert notify_soon is False
    _, notify_later = store.upsert_pending(
        code="052690",
        name="한전기술",
        qty=7,
        reason="장마감 전량 청산 (15:20)",
        profit_pct=-0.9,
        price=137500,
        now=now + timedelta(minutes=21),
        ignore_cooldown_min=20,
    )
    assert notify_later is True


def test_markup_callback_fits_64_bytes() -> None:
    markup = sell_proposal_markup("abc123")
    data = markup["inline_keyboard"][0][0]["callback_data"]
    assert data == "sell:ok:abc123"
    assert len(data.encode("utf-8")) <= 64


def test_sell_and_buy_copy() -> None:
    text = format_sell_proposal_text(
        name="삼화콘덴서",
        code="001820",
        profit_pct=-2.57,
        price=112064,
        qty=1000,
        reason="손절 (-2.57% <= -2.5%)",
    )
    assert "【매도 제안】" in text
    assert "삼화콘덴서" in text
    assert "-2.57" in text
    watch = format_buy_watchlist(
        [("KB금융", "105560", 18.0), ("LG에너지솔루션", "373220", 10.0)],
        skip_reason="일일 매수 한도 (10회)",
    )
    assert watch.startswith("【매수 후보】")
    assert "매수 없음" in watch
    empty = format_buy_watchlist([], skip_reason="후보 없음")
    assert "없음" in empty
    bought = format_buy_watchlist(
        [("삼성SDI", "006400", 16.0), ("KB금융", "105560", 18.0)],
        bought_code="006400",
    )
    assert "이번 후보" in bought
    assert "매수" in bought
