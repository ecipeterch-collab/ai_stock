from __future__ import annotations

from datetime import datetime

import requests

from config.config import use_paper
from kiwoom.client import KiwoomAPIError, KiwoomClient
from trading.market_utils import market_status_text
from trading.journal_stats import build_journal_stats
from trading.mode_settings import get_auto_trading_enabled, get_strategy_mode, mode_label
from trading.runtime_config import effective_max_buys_per_day, effective_max_positions
from trading.strategy import AutoTradingStrategy


def _deposit_numbers(client: KiwoomClient, deposit: dict) -> dict:
    fmt = client.format_amount
    return {
        "cash": int(client.parse_price(deposit.get("entr", "0"))),
        "orderable": int(client.parse_price(deposit.get("ord_alow_amt", "0"))),
        "withdrawable": int(client.parse_price(deposit.get("pymn_alow_amt", "0"))),
        "cash_fmt": fmt(deposit.get("entr", "0")),
        "orderable_fmt": fmt(deposit.get("ord_alow_amt", "0")),
        "withdrawable_fmt": fmt(deposit.get("pymn_alow_amt", "0")),
    }


def build_dashboard_snapshot(strategy: AutoTradingStrategy | None = None) -> dict:
    """웹 대시보드용 JSON 스냅샷."""
    strat = strategy or AutoTradingStrategy(KiwoomClient())
    client = strat.client
    strat._reset_daily_counter()

    auto_saved = get_auto_trading_enabled()
    if auto_saved is not None:
        auto_on = auto_saved
    else:
        auto_on = strat.enabled

    snapshot: dict = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "trade_mode": "paper" if use_paper else "real",
        "trade_mode_label": "모의투자" if use_paper else "실전투자",
        "strategy_mode": get_strategy_mode(),
        "strategy_label": mode_label(),
        "market_status": market_status_text(),
        "auto_trading": auto_on,
        "buy_count": strat._buy_count,
        "buy_max": effective_max_buys_per_day(),
        "max_positions": effective_max_positions(),
        "deposit": None,
        "deposit_error": None,
        "holdings": [],
        "holdings_error": None,
        "portfolio_value": 0,
        "portfolio_value_fmt": "0",
        "buy_status": {},
        "recent_trades": [],
        "journal_stats": None,
    }

    try:
        deposit = client.get_deposit()
        snapshot["deposit"] = _deposit_numbers(client, deposit)
    except (KiwoomAPIError, requests.RequestException) as exc:
        snapshot["deposit_error"] = str(exc)

    try:
        holdings = strat._parse_holdings()
        total_eval = 0
        rows = []
        for h in holdings:
            eval_amt = h.qty * h.current_price
            total_eval += eval_amt
            state = strat.positions.get(h.code)
            peak = state.peak_profit_pct if state else h.profit_pct
            hold_min = strat.positions.holding_minutes(h.code)
            tags: list[str] = []
            if state:
                if state.partial_sold:
                    tags.append("부분익절")
                if state.tp_stage:
                    tags.append(f"TP{state.tp_stage}")
            rows.append(
                {
                    "code": h.code,
                    "name": h.name,
                    "qty": h.qty,
                    "sellable_qty": h.sellable_qty,
                    "current_price": h.current_price,
                    "purchase_price": h.purchase_price,
                    "entry_price": state.entry_price if state else h.purchase_price,
                    "profit_pct": round(h.profit_pct, 2),
                    "peak_profit_pct": round(peak, 2),
                    "hold_minutes": round(hold_min, 1) if hold_min is not None else None,
                    "eval_amount": eval_amt,
                    "tags": tags,
                }
            )
        snapshot["holdings"] = rows
        snapshot["portfolio_value"] = total_eval
        snapshot["portfolio_value_fmt"] = client.format_amount(str(total_eval))
    except (KiwoomAPIError, requests.RequestException) as exc:
        snapshot["holdings_error"] = str(exc)

    reasons = strat.peek_buy_block_reasons()
    pnl_pct = strat._compute_today_pnl_pct()
    snapshot["buy_status"] = {
        "can_buy": len(reasons) == 0,
        "block_reasons": reasons,
        "today_pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
    }

    for e in strat.journal.tail(8):
        snapshot["recent_trades"].append(
            {
                "ts": e.ts,
                "event": e.event,
                "code": e.code,
                "name": e.name,
                "qty": e.qty,
                "price": e.price,
                "profit_pct": e.profit_pct,
                "reason": e.reason,
            }
        )

    try:
        snapshot["journal_stats"] = build_journal_stats(days=30)
    except OSError:
        snapshot["journal_stats"] = None

    return snapshot
