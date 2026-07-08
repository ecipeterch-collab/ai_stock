"""저널 기반 매매 종목 차트 데이터."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import requests

from kiwoom.client import KiwoomAPIError, get_shared_client
from trading.account_pnl import _apply_fill_prices, enrich_closed_trade_fees
from trading.chart_signals import _parse_candle_daily
from trading.journal_stats import build_closed_trades
from trading.trade_journal import TradeJournal

BUY_EVENTS = frozenset({"buy_order", "trend_buy_order", "crash_buy_order"})
SELL_EVENTS = frozenset({"sell_order"})


def _iso_date(ts: str) -> str:
    return ts[:10]


def _dt_key(dt: str) -> str:
    """YYYYMMDD → YYYY-MM-DD."""
    if len(dt) == 8 and dt.isdigit():
        return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
    return dt[:10]


def list_traded_stocks(*, days: int = 30, limit: int = 20) -> dict:
    """최근 매매 종목 목록 (차트 데이터 없음)."""
    journal = TradeJournal()
    events = _apply_fill_prices(journal.read_all())
    cutoff = datetime.now() - timedelta(days=max(1, days))

    by_code: dict[str, dict] = {}
    closed = build_closed_trades(events)
    closed_net: dict[str, int] = {}

    for t in closed:
        try:
            sell_dt = datetime.fromisoformat(t.ts)
        except ValueError:
            continue
        if sell_dt < cutoff:
            continue
        row = enrich_closed_trade_fees(t)
        closed_net[t.code] = closed_net.get(t.code, 0) + int(row["net_pnl_krw"])
        entry = by_code.get(t.code)
        if entry is None:
            by_code[t.code] = {
                "code": t.code,
                "name": t.name,
                "trade_count": 1,
                "last_ts": t.ts,
                "net_pnl_krw": int(row["net_pnl_krw"]),
            }
        else:
            entry["trade_count"] += 1
            entry["net_pnl_krw"] = closed_net[t.code]
            if t.ts > entry["last_ts"]:
                entry["last_ts"] = t.ts
                entry["name"] = t.name

    for e in events:
        if e.event not in BUY_EVENTS or not e.code:
            continue
        try:
            ts = datetime.fromisoformat(e.ts)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        entry = by_code.get(e.code)
        if entry is None:
            by_code[e.code] = {
                "code": e.code,
                "name": e.name or e.code,
                "trade_count": 0,
                "last_ts": e.ts,
                "net_pnl_krw": closed_net.get(e.code, 0),
            }
        elif e.ts > entry["last_ts"]:
            entry["last_ts"] = e.ts
            if e.name:
                entry["name"] = e.name

    stocks = sorted(by_code.values(), key=lambda x: x["last_ts"], reverse=True)
    if limit > 0:
        stocks = stocks[:limit]

    return {
        "days": days,
        "count": len(stocks),
        "stocks": stocks,
    }


def _markers_for_code(events, code: str) -> list[dict]:
    """매수·매도 마커 (체결가 우선)."""
    markers: list[dict] = []
    closed = [t for t in build_closed_trades(events) if t.code == code]
    for t in closed:
        if t.entry_ts and t.entry_price:
            markers.append(
                {
                    "time": _iso_date(t.entry_ts),
                    "ts": t.entry_ts,
                    "type": "buy",
                    "price": t.entry_price,
                    "qty": t.qty,
                    "label": "매수",
                }
            )
        if t.sell_price:
            markers.append(
                {
                    "time": _iso_date(t.ts),
                    "ts": t.ts,
                    "type": "sell",
                    "price": t.sell_price,
                    "qty": t.qty,
                    "profit_pct": round(t.profit_pct, 2),
                    "label": "매도",
                }
            )

    seen_ts: set[str] = {m["ts"] for m in markers}
    for e in events:
        if e.code != code or not e.price:
            continue
        if e.event in BUY_EVENTS and e.ts not in seen_ts:
            markers.append(
                {
                    "time": _iso_date(e.ts),
                    "ts": e.ts,
                    "type": "buy",
                    "price": int(e.price),
                    "qty": e.qty or 0,
                    "label": e.event.replace("_order", ""),
                }
            )
            seen_ts.add(e.ts)
        elif e.event in SELL_EVENTS and e.ts not in seen_ts:
            markers.append(
                {
                    "time": _iso_date(e.ts),
                    "ts": e.ts,
                    "type": "sell",
                    "price": int(e.price),
                    "qty": e.qty or 0,
                    "profit_pct": e.profit_pct,
                    "label": "매도",
                }
            )
            seen_ts.add(e.ts)

    markers.sort(key=lambda m: m["ts"])
    return markers


def build_stock_chart(
    code: str,
    *,
    client: KiwoomClient | None = None,
    days: int = 90,
) -> dict:
    """일봉 + 매매 마커."""
    client = client or get_shared_client()
    journal = TradeJournal()
    events = _apply_fill_prices(journal.read_all())
    code = client.normalize_stock_code(code)

    name = code
    for e in reversed(events):
        if e.code == code and e.name:
            name = e.name
            break

    markers = _markers_for_code(events, code)
    closed = [
        t
        for t in build_closed_trades(events)
        if t.code == code
    ]
    trade_rows = []
    for t in closed[-10:]:
        row = enrich_closed_trade_fees(t)
        trade_rows.append(
            {
                "entry_ts": t.entry_ts,
                "exit_ts": t.ts,
                "qty": t.qty,
                "entry_price": t.entry_price,
                "sell_price": t.sell_price,
                "profit_pct": round(t.profit_pct, 2),
                "net_pnl_krw": int(row["net_pnl_krw"]),
                "sell_reason": t.sell_reason.split(" / ")[0] if t.sell_reason else "",
            }
        )

    try:
        raw = client.get_daily_chart(code)
    except (KiwoomAPIError, requests.RequestException) as exc:
        return {
            "code": code,
            "name": name,
            "error": str(exc),
            "candles": [],
            "markers": markers,
            "trades": trade_rows,
        }

    cutoff = date.today() - timedelta(days=max(7, days))
    candles: list[dict] = []
    for item in raw:
        c = _parse_candle_daily(item)
        if c is None or not c.ts:
            continue
        bar_date = datetime.strptime(c.ts, "%Y%m%d").date()
        if bar_date < cutoff:
            continue
        candles.append(
            {
                "time": _dt_key(c.ts),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
        )
    candles.sort(key=lambda x: x["time"])

    return {
        "code": code,
        "name": name,
        "days": days,
        "candles": candles,
        "markers": markers,
        "trades": trade_rows,
    }
