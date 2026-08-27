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


def _deposit_amt(client, deposit: dict, key: str) -> int:
    return int(client.parse_price(deposit.get(key, "0")))


def _deposit_numbers(client, deposit: dict) -> dict:
    fmt = client.format_amount
    cash = _deposit_amt(client, deposit, "entr")
    d1_cash = _deposit_amt(client, deposit, "d1_entra")
    d2_cash = _deposit_amt(client, deposit, "d2_entra")
    settled_cash = d2_cash or d1_cash or cash
    return {
        "cash": cash,
        "d1_cash": d1_cash,
        "d2_cash": d2_cash,
        "settled_cash": settled_cash,
        "orderable": _deposit_amt(client, deposit, "ord_alow_amt"),
        "withdrawable": _deposit_amt(client, deposit, "pymn_alow_amt"),
        "d1_buy_exct": _deposit_amt(client, deposit, "d1_buy_exct_amt"),
        "d1_sel_exct": _deposit_amt(client, deposit, "d1_sel_exct_amt"),
        "cash_fmt": fmt(deposit.get("entr", "0")),
        "d1_cash_fmt": fmt(deposit.get("d1_entra", "0")),
        "d2_cash_fmt": fmt(deposit.get("d2_entra", "0")),
        "orderable_fmt": fmt(deposit.get("ord_alow_amt", "0")),
        "withdrawable_fmt": fmt(deposit.get("pymn_alow_amt", "0")),
    }


def apply_live_account_totals(
    acct: dict,
    *,
    settled_cash: int,
    holdings_eval: int,
) -> dict:
    """총자산 = 결제 반영 예수금(D+2 우선) + 보유평가. D+0 예수금은 쓰지 않는다."""
    initial = int(acct.get("initial_capital_krw") or 0)
    total_assets = int(settled_cash) + int(holdings_eval)
    acct_summary = dict(acct.get("account_summary") or {})
    acct_summary["total_assets_krw"] = total_assets
    if initial > 0:
        delta = total_assets - initial
        acct_summary["balance_delta_krw"] = delta
        acct_summary["return_on_capital_pct"] = round(delta / initial * 100, 4)
    acct["account_summary"] = acct_summary
    acct["live_totals"] = {
        "cash_krw": int(settled_cash),
        "holdings_eval_krw": int(holdings_eval),
        "total_assets_krw": total_assets,
    }
    return acct


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
        "news_sessions": None,
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
                if state.be_scaled:
                    tags.append("본전스케일")
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
        deposit = snapshot.get("deposit") or {}
        settled_cash = int(deposit.get("settled_cash") or deposit.get("cash") or 0)
        holdings_eval = int(snapshot.get("portfolio_value") or 0)
        if settled_cash or holdings_eval:
            apply_live_account_totals(
                acct,
                settled_cash=settled_cash,
                holdings_eval=holdings_eval,
            )
        snapshot["account_summary"] = acct
    except OSError:
        snapshot["account_summary"] = None

    try:
        from trading.news_sentiment_log import build_session_summary

        snapshot["news_sessions"] = build_session_summary()
    except OSError:
        snapshot["news_sessions"] = None

    return snapshot
