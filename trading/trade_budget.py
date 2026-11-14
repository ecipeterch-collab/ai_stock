"""보유자금 대비 하루·1회 매수 금액."""

from __future__ import annotations

from datetime import date

from trading.trade_journal import TradeEvent


def amount_from_pct(capital: int, pct: float) -> int:
    if capital <= 0 or pct <= 0:
        return 0
    return int(int(capital) * float(pct) / 100.0)


def funds_from_balances(*, cash: int, holdings_eval: int, fallback: int) -> int:
    total = max(0, int(cash)) + max(0, int(holdings_eval))
    if total > 0:
        return total
    return max(0, int(fallback))


def today_buy_notional(events: list[TradeEvent], day: date) -> int:
    prefix = day.isoformat()
    total = 0
    for event in events:
        if event.event != "buy_order" or not str(event.ts).startswith(prefix):
            continue
        qty = int(event.qty or 0)
        price = int(event.price or 0)
        if qty > 0 and price > 0:
            total += qty * price
    return total


def format_budget_text(
    *,
    funds: int,
    daily_pct: float,
    order_pct: float,
    spent: int,
) -> str:
    daily_limit = amount_from_pct(funds, daily_pct)
    order_amt = amount_from_pct(funds, order_pct)
    remain = max(0, daily_limit - max(0, int(spent)))
    effective = min(order_amt, remain)
    return (
        "【거래 비율】\n"
        f"보유자금 {funds:,}원\n"
        f"하루 한도 {daily_pct:g}% · {daily_limit:,}원\n"
        f"오늘 사용 {max(0, int(spent)):,}원 · 남음 {remain:,}원\n"
        f"1회 매수 {order_pct:g}% · {order_amt:,}원"
        f" (이번 주문 상한 {effective:,}원)\n"
        "변경: /budget 10  (하루 한도 %)\n"
        "      /budget order 2  (1회 매수 %)"
    )
