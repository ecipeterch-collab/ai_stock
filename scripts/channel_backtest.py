#!/usr/bin/env python3
"""채널·국면·드로다운 스케일별 매매 성과 백테스트 (저널 기반).

예:
  python scripts/channel_backtest.py
  python scripts/channel_backtest.py --days 30
  python scripts/channel_backtest.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.account_pnl import enrich_closed_trade_fees
from trading.journal_stats import (
    ENTRY_LABELS,
    REGIME_LABELS,
    build_closed_trades,
    build_journal_stats,
    classify_entry,
    format_stats_text,
)
from trading.market_regime import parse_regime_from_reason, parse_scale_from_reason
from trading.trade_journal import TradeJournal


BUY_EVENTS = frozenset(
    {"buy_order", "trend_buy_order", "crash_buy_order", "addon_buy_order"}
)


def _scale_bucket(mult: float) -> str:
    if mult <= 1.0:
        return "1.0x"
    if mult <= 1.25:
        return "1.25x"
    if mult <= 1.5:
        return "1.5x"
    return "2.0x+"


def build_scale_stats(closed: list) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "wins": 0, "net_pnl_krw": 0}
    )
    for t in closed:
        mult = parse_scale_from_reason(t.buy_reason)
        key = _scale_bucket(mult)
        row = enrich_closed_trade_fees(t)
        net = int(row["net_pnl_krw"])
        buckets[key]["count"] += 1
        buckets[key]["net_pnl_krw"] += net
        if net > 0:
            buckets[key]["wins"] += 1

    out = []
    for key in ("1.0x", "1.25x", "1.5x", "2.0x+"):
        b = buckets.get(key)
        if not b or b["count"] == 0:
            continue
        out.append(
            {
                "scale": key,
                "count": b["count"],
                "win_rate_pct": round(b["wins"] / b["count"] * 100, 1),
                "net_pnl_krw": b["net_pnl_krw"],
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="채널·국면 백테스트")
    parser.add_argument("--days", type=int, default=30, help="분석 일수 (0=전체)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    days = None if args.days <= 0 else args.days
    stats = build_journal_stats(days=days)
    journal = TradeJournal()
    events = journal.read_all()
    closed = build_closed_trades(events)
    if days:
        cutoff = date.today() - timedelta(days=days - 1)
        closed = [
            t
            for t in closed
            if t.ts and date.fromisoformat(t.ts[:10]) >= cutoff
        ]

    scale_stats = build_scale_stats(closed)
    buys = [e for e in events if e.event in BUY_EVENTS]

    payload = {
        "summary": stats["summary"],
        "by_entry": stats["by_entry"],
        "by_regime": stats.get("by_regime", []),
        "by_channel_regime": stats.get("by_channel_regime", []),
        "by_scale": scale_stats,
        "buy_events": len(buys),
        "buys_with_regime_tag": sum(
            1 for e in buys if parse_regime_from_reason(e.reason or "") != "unknown"
        ),
        "buys_with_scale_tag": sum(
            1 for e in buys if parse_scale_from_reason(e.reason or "") > 1.0
        ),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(format_stats_text(stats))
    print()
    print("【드로다운 스케일】")
    if scale_stats:
        for row in scale_stats:
            print(
                f"  {row['scale']}: {row['count']}건 "
                f"승률{row['win_rate_pct']}% "
                f"순손익 {row['net_pnl_krw']:+,}원"
            )
    else:
        print("  스케일 태그 매매 없음 (신규 매수부터 기록됨)")
    print()
    print(
        f"매수 이벤트 {len(buys)}건 · "
        f"국면태그 {payload['buys_with_regime_tag']}건 · "
        f"스케일>1x {payload['buys_with_scale_tag']}건"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
