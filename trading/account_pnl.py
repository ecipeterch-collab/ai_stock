"""원금·수수료 반영 실계좌 손익 집계."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config.config import use_paper
from trading.account_settings import (
    fee_settings_snapshot,
    get_commission_rate_pct,
    get_initial_capital,
    get_sell_tax_rate_pct,
)
from trading.journal_stats import ClosedTrade, build_closed_trades
from trading.trade_journal import JOURNAL_FILE, TradeEvent, TradeJournal


def calc_trade_fees(
    *,
    entry_price: int,
    sell_price: int,
    qty: int,
    commission_rate_pct: float | None = None,
    sell_tax_rate_pct: float | None = None,
) -> dict[str, int]:
    """매수·매도 수수료 및 매도세(원)."""
    if qty <= 0 or entry_price <= 0 or sell_price <= 0:
        return {
            "buy_notional": 0,
            "sell_notional": 0,
            "buy_commission": 0,
            "sell_commission": 0,
            "sell_tax": 0,
            "total_fees": 0,
        }
    comm = commission_rate_pct if commission_rate_pct is not None else get_commission_rate_pct()
    tax = sell_tax_rate_pct if sell_tax_rate_pct is not None else get_sell_tax_rate_pct()
    buy_notional = entry_price * qty
    sell_notional = sell_price * qty
    buy_commission = round(buy_notional * comm / 100.0)
    sell_commission = round(sell_notional * comm / 100.0)
    sell_tax = round(sell_notional * tax / 100.0)
    total_fees = buy_commission + sell_commission + sell_tax
    return {
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "buy_commission": buy_commission,
        "sell_commission": sell_commission,
        "sell_tax": sell_tax,
        "total_fees": total_fees,
    }


def enrich_closed_trade_fees(
    trade: ClosedTrade,
    *,
    commission_rate_pct: float | None = None,
    sell_tax_rate_pct: float | None = None,
) -> dict[str, Any]:
    """완결 거래에 수수료·순손익 필드 추가."""
    gross = trade.pnl_krw or 0
    entry = trade.entry_price or 0
    sell = trade.sell_price or 0
    fees = calc_trade_fees(
        entry_price=entry,
        sell_price=sell,
        qty=trade.qty,
        commission_rate_pct=commission_rate_pct,
        sell_tax_rate_pct=sell_tax_rate_pct,
    )
    net = gross - fees["total_fees"]
    return {
        "ts": trade.ts,
        "code": trade.code,
        "name": trade.name,
        "qty": trade.qty,
        "entry_price": trade.entry_price,
        "sell_price": trade.sell_price,
        "profit_pct": round(trade.profit_pct, 2),
        "gross_pnl_krw": gross,
        "buy_commission_krw": fees["buy_commission"],
        "sell_commission_krw": fees["sell_commission"],
        "sell_tax_krw": fees["sell_tax"],
        "total_fees_krw": fees["total_fees"],
        "net_pnl_krw": net,
        "entry_channel": trade.entry_channel,
        "sell_reason": trade.sell_reason,
    }


def _fill_prices_by_ord_no(events: list[TradeEvent]) -> dict[str, int]:
    prices: dict[str, int] = {}
    for e in events:
        if e.event != "fill" or not e.ord_no or not e.price:
            continue
        prices[str(e.ord_no)] = int(e.price)
    return prices


def _apply_fill_prices(events: list[TradeEvent]) -> list[TradeEvent]:
    """주문가 대신 체결가가 있으면 가격 필드를 보정."""
    fill_px = _fill_prices_by_ord_no(events)
    if not fill_px:
        return events
    out: list[TradeEvent] = []
    for e in events:
        if e.ord_no and e.ord_no in fill_px and e.price:
            out.append(
                TradeEvent(
                    ts=e.ts,
                    event=e.event,
                    code=e.code,
                    name=e.name,
                    qty=e.qty,
                    price=fill_px[e.ord_no],
                    profit_pct=e.profit_pct,
                    reason=e.reason,
                    ord_no=e.ord_no,
                )
            )
        else:
            out.append(e)
    return out


def _month_key(ts: str) -> str:
    return ts[:7]


def _fetch_live_balance(client=None) -> dict[str, Any] | None:
    try:
        from kiwoom.client import get_shared_client

        client = client or get_shared_client()
        deposit = client.get_deposit()
        holdings = client.get_holdings()
        cash = client.parse_price(deposit.get("entr", "0"))
        holdings_eval = 0
        held = []
        for item in holdings:
            qty = client.parse_qty(item.get("rmnd_qty", "0"))
            if qty <= 0:
                continue
            eval_amt = client.parse_price(item.get("evlt_amt", "0"))
            if eval_amt <= 0:
                cur = client.parse_price(item.get("cur_prc", "0"))
                eval_amt = cur * qty
            holdings_eval += eval_amt
            held.append(
                {
                    "code": client.normalize_stock_code(item.get("stk_cd", "")),
                    "name": item.get("stk_nm", ""),
                    "qty": qty,
                    "eval_amount": eval_amt,
                }
            )
        total_assets = cash + holdings_eval
        return {
            "cash_krw": cash,
            "holdings_eval_krw": holdings_eval,
            "total_assets_krw": total_assets,
            "holdings": held,
            "orderable_krw": client.parse_price(deposit.get("ord_alow_amt", "0")),
        }
    except Exception as exc:
        return {"error": str(exc)}


def build_account_summary(
    *,
    path: Path | None = None,
    from_date: date | None = None,
    include_live_balance: bool = True,
) -> dict[str, Any]:
    """원금 대비 실계좌 손익 요약 (수수료·세금 반영)."""
    journal = TradeJournal(path or JOURNAL_FILE)
    events = _apply_fill_prices(journal.read_all())
    closed = build_closed_trades(events)
    if from_date is not None:
        closed = [
            t
            for t in closed
            if datetime.fromisoformat(t.ts).date() >= from_date
        ]

    comm_rate = get_commission_rate_pct()
    tax_rate = get_sell_tax_rate_pct()
    initial = get_initial_capital()

    enriched: list[dict[str, Any]] = []
    gross_total = 0
    fee_total = 0
    net_total = 0
    buy_comm_total = 0
    sell_comm_total = 0
    tax_total = 0
    wins = losses = breakeven = 0

    by_month: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "count": 0,
            "gross_pnl_krw": 0,
            "total_fees_krw": 0,
            "net_pnl_krw": 0,
            "wins": 0,
            "losses": 0,
        }
    )

    for t in closed:
        row = enrich_closed_trade_fees(
            t,
            commission_rate_pct=comm_rate,
            sell_tax_rate_pct=tax_rate,
        )
        enriched.append(row)
        gross = int(row["gross_pnl_krw"])
        fees = int(row["total_fees_krw"])
        net = int(row["net_pnl_krw"])
        gross_total += gross
        fee_total += fees
        net_total += net
        buy_comm_total += int(row["buy_commission_krw"])
        sell_comm_total += int(row["sell_commission_krw"])
        tax_total += int(row["sell_tax_krw"])
        if net > 0:
            wins += 1
        elif net < 0:
            losses += 1
        else:
            breakeven += 1
        mk = _month_key(t.ts)
        by_month[mk]["count"] += 1
        by_month[mk]["gross_pnl_krw"] += gross
        by_month[mk]["total_fees_krw"] += fees
        by_month[mk]["net_pnl_krw"] += net
        if net > 0:
            by_month[mk]["wins"] += 1
        elif net < 0:
            by_month[mk]["losses"] += 1

    count = len(enriched)
    win_rate = round(wins / count * 100, 2) if count else None
    expected_balance = initial + net_total if initial > 0 else None
    return_on_trading_net_pct = (
        round(net_total / initial * 100, 4) if initial > 0 else None
    )

    live: dict[str, Any] | None = None
    if include_live_balance:
        live = _fetch_live_balance()

    balance_delta: int | None = None
    return_on_capital_pct: float | None = None
    unreconciled: int | None = None
    total_assets: int | None = None

    if live and "error" not in live and initial > 0:
        total_assets = int(live["total_assets_krw"])
        balance_delta = total_assets - initial
        return_on_capital_pct = round(balance_delta / initial * 100, 4)
        if expected_balance is not None:
            unreconciled = total_assets - expected_balance

    monthly_rows = [{"month": mk, **vals} for mk, vals in sorted(by_month.items())]

    first_ts = closed[0].ts if closed else None
    last_ts = closed[-1].ts if closed else None

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trade_mode": "paper" if use_paper else "real",
        "trade_mode_label": "모의투자" if use_paper else "실전투자",
        "journal_path": str(journal.path),
        "filter": {"from_date": from_date.isoformat() if from_date else None},
        "settings": fee_settings_snapshot(),
        "trading_period": {"first_trade": first_ts, "last_trade": last_ts},
        "initial_capital_krw": initial,
        "live_balance": live,
        "trading_summary": {
            "count": count,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate_pct": win_rate,
            "gross_pnl_krw": gross_total,
            "buy_commission_krw": buy_comm_total,
            "sell_commission_krw": sell_comm_total,
            "sell_tax_krw": tax_total,
            "total_fees_krw": fee_total,
            "net_pnl_krw": net_total,
        },
        "account_summary": {
            "expected_balance_krw": expected_balance,
            "total_assets_krw": total_assets,
            "balance_delta_krw": balance_delta,
            "return_on_capital_pct": return_on_capital_pct,
            "return_on_trading_net_pct": return_on_trading_net_pct,
            "unreconciled_krw": unreconciled,
        },
        "by_month": monthly_rows,
        "closed_trades": enriched,
    }


def _fmt_krw(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:+,}원"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.4f}%"


def format_account_summary_text(summary: dict[str, Any]) -> str:
    """원금 대비 실계좌 손익 보고 (텔레그램·터미널)."""
    mode = summary.get("trade_mode_label", "")
    initial = int(summary.get("initial_capital_krw") or 0)
    settings = summary.get("settings") or {}
    ts = summary.get("trading_summary") or {}
    acct = summary.get("account_summary") or {}
    live = summary.get("live_balance") or {}
    period = summary.get("trading_period") or {}

    lines = [
        f"【원금 대비 손익】 {mode}",
        f"시작 원금: {_fmt_krw(initial)}",
        (
            f"수수료 {settings.get('commission_rate_pct', 0)}% "
            f"(매수·매도) · 매도세 {settings.get('sell_tax_rate_pct', 0)}%"
        ),
    ]

    if live.get("error"):
        lines.append(f"현재 잔고: 조회 실패 ({live['error']})")
    elif live:
        lines.extend(
            [
                f"현재 예수금: {_fmt_krw(live.get('cash_krw'))}",
                f"보유 평가: {_fmt_krw(live.get('holdings_eval_krw'))}",
                f"총자산: {_fmt_krw(live.get('total_assets_krw'))}",
            ]
        )

    if acct.get("balance_delta_krw") is not None:
        lines.append(
            f"원금 대비 변동: {_fmt_krw(acct.get('balance_delta_krw'))} "
            f"({_fmt_pct(acct.get('return_on_capital_pct'))})"
        )

    lines.extend(
        [
            "",
            "■ 거래 손익 (수수료·세금 반영)",
            (
                f"완결 {ts.get('count', 0)}건 · "
                f"승 {ts.get('wins', 0)} / 패 {ts.get('losses', 0)}"
                + (
                    f" (승률 {ts['win_rate_pct']}%)"
                    if ts.get("win_rate_pct") is not None
                    else ""
                )
            ),
            f"  세전 손익: {_fmt_krw(ts.get('gross_pnl_krw'))}",
            (
                f"  수수료: {_fmt_krw(ts.get('total_fees_krw'))} "
                f"(매수 {ts.get('buy_commission_krw', 0):,} · "
                f"매도 {ts.get('sell_commission_krw', 0):,} · "
                f"세금 {ts.get('sell_tax_krw', 0):,})"
            ),
            f"  순손익: {_fmt_krw(ts.get('net_pnl_krw'))} "
            f"({_fmt_pct(acct.get('return_on_trading_net_pct'))} / 원금)",
        ]
    )

    if acct.get("expected_balance_krw") is not None:
        lines.append(
            f"  거래 기준 예상 잔고: {_fmt_krw(acct.get('expected_balance_krw'))}"
        )
    if acct.get("unreconciled_krw") is not None:
        gap = int(acct["unreconciled_krw"])
        if gap != 0:
            lines.append(
                f"  실잔고 vs 예상 차이: {_fmt_krw(gap)} "
                "(체결가 차이·미기록 거래 등)"
            )

    by_month = summary.get("by_month") or []
    if by_month:
        lines.append("")
        lines.append("■ 월별 순손익")
        for row in by_month:
            lines.append(
                f"  {row['month']}: {_fmt_krw(row['net_pnl_krw'])} "
                f"({row['count']}건 · 승{row['wins']}/패{row['losses']})"
            )

    if period.get("first_trade"):
        lines.append("")
        lines.append(
            f"기간: {period['first_trade'][:10]} ~ "
            f"{(period.get('last_trade') or '')[:10]}"
        )
    lines.append("")
    lines.append("※ 순손익 = 체결가 손익 − 수수료 − 매도세")
    return "\n".join(lines)
