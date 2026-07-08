#!/usr/bin/env python3
"""거래 저널 통계 CLI.

예:
  python scripts/journal_stats.py
  python scripts/journal_stats.py --today
  python scripts/journal_stats.py --account
  python scripts/journal_stats.py --days 7
  python scripts/journal_stats.py --all
  python scripts/journal_stats.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.account_pnl import build_account_summary, format_account_summary_text
from trading.journal_stats import (
    build_daily_summary,
    build_journal_stats,
    format_daily_summary_text,
    format_stats_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="trade_journal.jsonl 통계")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="집계 기간(일). 0이면 전체 (--all과 동일)",
    )
    parser.add_argument("--today", action="store_true", help="오늘 매매·손익 요약")
    parser.add_argument(
        "--account",
        action="store_true",
        help="원금 대비 실계좌 손익 (수수료·세금 포함)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="특정 일자 요약 (YYYY-MM-DD, --today 대신 사용 가능)",
    )
    parser.add_argument("--all", action="store_true", help="전체 기간")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="저널 파일 경로 (기본 data/trade_journal.jsonl)",
    )
    args = parser.parse_args()

    if args.account:
        summary = build_account_summary(path=args.path)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(format_account_summary_text(summary))
        return 0

    if args.today or args.date:
        target = date.fromisoformat(args.date) if args.date else date.today()
        summary = build_daily_summary(target_date=target, path=args.path)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(format_daily_summary_text(summary))
        return 0

    days = None if args.all or args.days == 0 else args.days
    stats = build_journal_stats(path=args.path, days=days)

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(format_stats_text(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
