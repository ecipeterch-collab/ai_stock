from __future__ import annotations

from datetime import datetime

import requests

from config.config import use_paper
from kiwoom.client import KiwoomAPIError, get_shared_client
from trading.market_utils import market_status_text
from trading.account_pnl import build_account_summary
from trading.journal_stats import build_daily_summary, build_journal_stats
from trading.mode_settings import get_strategy_mode, mode_label
from trading.runtime_config import effective_max_buys_per_day, effective_max_positions
from trading.strategy import AutoTradingStrategy


def _resolve_strategy() -> AutoTradingStrategy:
    """웹·봇이 동일 Kiwoom 클라이언트·전략 상태를 공유."""
    try:
        from web.commands import _get_bot

        return _get_bot().strategy
    except Exception:
        return AutoTradingStrategy(get_shared_client())


def _deposit_numbers(client, deposit: dict) -> dict:
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
    strat = strategy or _resolve_strategy()
    client = strat.client
    strat._reset_daily_counter()

    # 저장 설정과 달리 strategy.enabled·루프는 프로세스 재시작 시 초기화됨 → 실제 상태 우선
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
        "daily_summary": None,
        "account_summary": None,
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

    try:
        snapshot["daily_summary"] = build_daily_summary()
    except OSError:
        snapshot["daily_summary"] = None

    try:
        acct = build_account_summary(include_live_balance=False)
        cash = int((snapshot.get("deposit") or {}).get("cash") or 0)
        holdings_eval = int(snapshot.get("portfolio_value") or 0)
        if cash or holdings_eval:
            initial = int(acct.get("initial_capital_krw") or 0)
            total_assets = cash + holdings_eval
            acct_summary = dict(acct.get("account_summary") or {})
            acct_summary["total_assets_krw"] = total_assets
            if initial > 0:
                acct_summary["balance_delta_krw"] = total_assets - initial
                acct_summary["return_on_capital_pct"] = round(
                    (total_assets - initial) / initial * 100, 4
                )
            acct["account_summary"] = acct_summary
            acct["live_totals"] = {
                "cash_krw": cash,
                "holdings_eval_krw": holdings_eval,
                "total_assets_krw": total_assets,
            }
        snapshot["account_summary"] = acct
    except OSError:
        snapshot["account_summary"] = None

    return snapshot
