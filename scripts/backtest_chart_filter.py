#!/usr/bin/env python3
"""저널 매수에 차트 필터·config 조정을 소급 적용한 백테스트.

예:
  python scripts/backtest_chart_filter.py
  python scripts/backtest_chart_filter.py --json
  python scripts/backtest_chart_filter.py --limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kiwoom.client import KiwoomClient, KiwoomAPIError
from config.config import chart_cache_daily_ttl_sec, chart_cache_minute_ttl_sec
from trading.account_pnl import enrich_closed_trade_fees
from trading.chart_signals import ChartSignalAnalyzer
from trading.journal_stats import build_closed_trades, classify_entry
from trading.market_regime import parse_regime_from_reason, parse_scale_from_reason
from trading.trade_journal import TradeJournal


BUY_EVENTS = frozenset({"buy_order", "trend_buy_order", "crash_buy_order"})


def _infer_mode(event: str, reason: str) -> str:
    if "모멘텀" in (reason or ""):
        return "momentum"
    if event == "crash_buy_order":
        return "pullback"
    if event == "trend_buy_order":
        return "pullback"
    return "pullback"


def main() -> int:
    parser = argparse.ArgumentParser(description="차트 필터 백테스트")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument("--limit", type=int, default=0, help="분석 건수 제한(0=전체)")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="오류 후 추가 대기(초). 정상 호출은 Kiwoom 클라이언트 스로틀 사용",
    )
    args = parser.parse_args()

    journal = TradeJournal()
    events = journal.read_all()
    closed = build_closed_trades(events)
    closed_by_key = {(c.entry_ts, c.code): c for c in closed if c.entry_ts}

    buys = [e for e in events if e.event in BUY_EVENTS and e.code and e.price]
    buys.sort(key=lambda e: e.ts)
    if args.limit > 0:
        buys = buys[: args.limit]

    client = KiwoomClient()
    chart = ChartSignalAnalyzer(client)
    chart.prune_stale_cache()
    chart.prefetch_for_buy_events(
        [(buy.code, datetime.fromisoformat(buy.ts)) for buy in buys]
    )

    rows: list[dict] = []
    actual_net = 0
    filtered_net = 0
    blocked_net = 0
    passed = blocked = no_match = errors = 0

    for buy in buys:
        as_of = datetime.fromisoformat(buy.ts)
        mode = _infer_mode(buy.event, buy.reason or "")
        key = (buy.ts, buy.code)
        trade = closed_by_key.get(key)
        net_pnl = 0
        gross_pnl = 0
        if trade:
            row = enrich_closed_trade_fees(trade)
            net_pnl = int(row["net_pnl_krw"])
            gross_pnl = int(row["gross_pnl_krw"])

        actual_net += net_pnl

        try:
            result = chart.evaluate(
                code=buy.code,
                current_price=int(buy.price or 0),
                mode=mode,
                as_of=as_of,
            )
        except (KiwoomAPIError, OSError, ValueError, requests.RequestException) as exc:
            errors += 1
            rows.append(
                {
                    "ts": buy.ts,
                    "code": buy.code,
                    "name": buy.name,
                    "event": buy.event,
                    "mode": mode,
                    "chart_passed": None,
                    "chart_score": None,
                    "reject_reason": str(exc),
                    "net_pnl_krw": net_pnl,
                    "buy_reason": buy.reason,
                }
            )
            if args.sleep > 0:
                time.sleep(args.sleep)
            continue

        if result.passed:
            passed += 1
            filtered_net += net_pnl
        else:
            blocked += 1
            blocked_net += net_pnl

        if not trade:
            no_match += 1

        rows.append(
            {
                "ts": buy.ts,
                "code": buy.code,
                "name": buy.name,
                "event": buy.event,
                "entry_label": classify_entry(buy.event, buy.reason or ""),
                "regime": parse_regime_from_reason(buy.reason or ""),
                "scale_mult": parse_scale_from_reason(buy.reason or ""),
                "mode": mode,
                "chart_passed": result.passed,
                "chart_score": result.score,
                "chart_reasons": result.reasons,
                "reject_reason": result.reject_reason,
                "net_pnl_krw": net_pnl,
                "gross_pnl_krw": gross_pnl,
                "buy_reason": buy.reason,
            }
        )

    cache = chart.cache_stats()
    summary = {
        "analyzed_buys": len(rows),
        "matched_closed": len(rows) - no_match,
        "chart_passed": passed,
        "chart_blocked": blocked,
        "errors": errors,
        "actual_net_pnl_krw": actual_net,
        "filtered_net_pnl_krw": filtered_net,
        "blocked_net_pnl_krw": blocked_net,
        "filtered_vs_actual_delta": filtered_net - actual_net,
        "pass_rate_pct": round(passed / len(rows) * 100, 1) if rows else 0,
        "chart_cache_daily": cache["daily"],
        "chart_cache_minute": cache["minute"],
    }

    if args.json:
        print(json.dumps({"summary": summary, "trades": rows}, ensure_ascii=False, indent=2))
        return 0

    print("【차트 필터 백테스트】")
    print(f"분석 매수 {summary['analyzed_buys']}건 · 통과 {passed} / 차단 {blocked} / 오류 {errors}")
    print(
        f"캐시 적중 — 일봉 {cache['daily']}건 · 분봉 {cache['minute']}건 "
        f"(TTL {chart_cache_daily_ttl_sec}s / {chart_cache_minute_ttl_sec}s)"
    )
    print(f"실제 순손익(매칭): {actual_net:+,}원")
    print(f"필터 통과분만:     {filtered_net:+,}원")
    print(f"필터 차단분:       {blocked_net:+,}원")
    print(f"개선 효과:         {summary['filtered_vs_actual_delta']:+,}원")
    print()
    print("■ 차단된 매수 (손실 회피 후보)")
    for r in rows:
        if r.get("chart_passed") is False and (r.get("net_pnl_krw") or 0) < 0:
            print(
                f"  {r['ts'][:16]} {r['name']} 순{r['net_pnl_krw']:+,} "
                f"| {r.get('reject_reason', '')}"
            )
    print()
    print("■ 통과했지만 손실 (필터 한계)")
    for r in rows:
        if r.get("chart_passed") is True and (r.get("net_pnl_krw") or 0) < 0:
            print(
                f"  {r['ts'][:16]} {r['name']} 순{r['net_pnl_krw']:+,} "
                f"| {', '.join(r.get('chart_reasons') or [])}"
            )
    print()
    print("■ 차단됐지만 수익 (기회비용)")
    for r in rows:
        if r.get("chart_passed") is False and (r.get("net_pnl_krw") or 0) > 0:
            print(
                f"  {r['ts'][:16]} {r['name']} 순{r['net_pnl_krw']:+,} "
                f"| {r.get('reject_reason', '')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
