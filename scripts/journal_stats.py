#!/usr/bin/env python3
"""거래 저널 통계 CLI.

예:
  python scripts/journal_stats.py
  python scripts/journal_stats.py --days 7
  python scripts/journal_stats.py --all
  python scripts/journal_stats.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.journal_stats import build_journal_stats, format_stats_text


def main() -> int:
    parser = argparse.ArgumentParser(description="trade_journal.jsonl 통계")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="집계 기간(일). 0이면 전체 (--all과 동일)",
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

    days = None if args.all or args.days == 0 else args.days
    stats = build_journal_stats(path=args.path, days=days)

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(format_stats_text(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
