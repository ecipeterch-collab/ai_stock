#!/usr/bin/env python3
"""매매 저널 기반 매수 채널·시간대·청산 유형별 성과 분석."""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.account_pnl import _apply_fill_prices, build_account_summary
from trading.journal_stats import ENTRY_LABELS, build_closed_trades, classify_exit_category
from trading.trade_journal import TradeJournal


def main() -> int:
    journal = TradeJournal()
    events = _apply_fill_prices(journal.read_all())
    closed = build_closed_trades(events)
    acct = build_account_summary(include_live_balance=False)
    trades = acct["closed_trades"]

    by_entry: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "net": 0, "gross": 0, "fees": 0, "wins": 0}
    )
    by_exit: dict[str, dict] = defaultdict(lambda: {"n": 0, "net": 0, "wins": 0})
    by_hour: dict[int, dict] = defaultdict(lambda: {"n": 0, "net": 0, "wins": 0})
    hold_buckets: dict[str, dict] = defaultdict(lambda: {"n": 0, "net": 0, "wins": 0})

    closed_map = {(c.ts, c.code): c for c in closed}

    for t in trades:
        c = closed_map.get((t["ts"], t["code"]))
        ch = ENTRY_LABELS.get(t.get("entry_channel", ""), t.get("entry_channel", ""))
        by_entry[ch]["n"] += 1
        by_entry[ch]["net"] += t["net_pnl_krw"]
        by_entry[ch]["gross"] += t["gross_pnl_krw"]
        by_entry[ch]["fees"] += t["total_fees_krw"]
        if t["net_pnl_krw"] > 0:
            by_entry[ch]["wins"] += 1

        if c:
            ex = classify_exit_category(c.sell_reason)
            by_exit[ex]["n"] += 1
            by_exit[ex]["net"] += t["net_pnl_krw"]
            if t["net_pnl_krw"] > 0:
                by_exit[ex]["wins"] += 1

            try:
                entry = datetime.fromisoformat(c.entry_ts)
                exit_ = datetime.fromisoformat(c.ts)
                mins = (exit_ - entry).total_seconds() / 60
            except ValueError:
                mins = None
            if mins is not None:
                if mins < 60:
                    b = "<1h"
                elif mins < 180:
                    b = "1-3h"
                elif mins < 240:
                    b = "3-4h"
                else:
                    b = "4h+"
                hold_buckets[b]["n"] += 1
                hold_buckets[b]["net"] += t["net_pnl_krw"]
                if t["net_pnl_krw"] > 0:
                    hold_buckets[b]["wins"] += 1

        h = int(t["ts"][11:13])
        by_hour[h]["n"] += 1
        by_hour[h]["net"] += t["net_pnl_krw"]
        if t["net_pnl_krw"] > 0:
            by_hour[h]["wins"] += 1

    def wr(v: dict) -> float:
        return v["wins"] / v["n"] * 100 if v["n"] else 0.0

    print("=== 진입 채널별 (순손익) ===")
    for k, v in sorted(by_entry.items(), key=lambda x: x[1]["net"], reverse=True):
        print(
            f"  {k}: {v['n']}건 순{v['net']:+,}원 "
            f"(세전{v['gross']:+,} 수수료{v['fees']:,}) 승률{wr(v):.0f}%"
        )

    print("\n=== 청산 유형별 (순손익) ===")
    for k, v in sorted(by_exit.items(), key=lambda x: x[1]["net"], reverse=True):
        print(f"  {k}: {v['n']}건 순{v['net']:+,}원 승률{wr(v):.0f}%")

    print("\n=== 매수 시간대 (sell 기준 근사) ===")
    for h in sorted(by_hour):
        v = by_hour[h]
        if v["n"]:
            print(f"  {h:02d}시대: {v['n']}건 순{v['net']:+,}원 승률{wr(v):.0f}%")

    print("\n=== 보유 시간 ===")
    for k in ("<1h", "1-3h", "3-4h", "4h+"):
        v = hold_buckets[k]
        if v["n"]:
            print(f"  {k}: {v['n']}건 순{v['net']:+,}원 승률{wr(v):.0f}%")

    print("\n=== 순수익 TOP5 ===")
    for t in sorted(trades, key=lambda x: x["net_pnl_krw"], reverse=True)[:5]:
        c = closed_map.get((t["ts"], t["code"]))
        reason = (c.buy_reason[:70] + "…") if c and len(c.buy_reason) > 70 else (c.buy_reason if c else "")
        print(f"  {t['ts'][:16]} {t['name']} 순{t['net_pnl_krw']:+,} | {reason}")

    print("\n=== 순손실 TOP5 ===")
    for t in sorted(trades, key=lambda x: x["net_pnl_krw"])[:5]:
        c = closed_map.get((t["ts"], t["code"]))
        reason = (c.buy_reason[:70] + "…") if c and len(c.buy_reason) > 70 else (c.buy_reason if c else "")
        print(f"  {t['ts'][:16]} {t['name']} 순{t['net_pnl_krw']:+,} | {reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
