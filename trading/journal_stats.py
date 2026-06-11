"""trade_journal.jsonl 집계: 진입 채널·청산 사유·승률·평균 손익."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from trading.trade_journal import JOURNAL_FILE, TradeEvent, TradeJournal

ENTRY_LABELS = {
    "trend": "트렌드",
    "crash": "급락(우량)",
    "scalping_scan": "스캘핑(스캔)",
    "swing_scan": "스윙(스캔)",
    "unknown": "미매칭",
}

EXIT_CATEGORY_LABELS = {
    "stop_loss": "손절",
    "take_profit": "익절",
    "trailing": "트레일링",
    "eod": "장마감",
    "defensive": "방어모드",
    "momentum": "모멘텀 둔화",
    "time_limit": "보유시간",
    "partial_tp": "부분익절",
    "other": "기타",
}

EXIT_MODE_LABELS = {
    "scalping": "스캘핑",
    "swing": "스윙",
    "unknown": "기타",
}


@dataclass
class OpenLot:
    entry_channel: str
    ts: str
    code: str
    name: str
    qty: int
    price: int
    buy_reason: str


@dataclass
class ClosedTrade:
    ts: str
    code: str
    name: str
    qty: int
    entry_channel: str
    entry_ts: str
    buy_reason: str
    sell_reason: str
    exit_category: str
    exit_mode: str
    profit_pct: float
    entry_price: int | None
    sell_price: int | None


def _base_reason(reason: str) -> str:
    if not reason:
        return ""
    return reason.split(" / ")[0].strip()


def classify_entry(event: str, reason: str) -> str:
    if event == "trend_buy_order":
        return "trend"
    if event == "crash_buy_order":
        return "crash"
    if event != "buy_order":
        return "unknown"
    r = reason or ""
    if "스캘프" in r:
        return "scalping_scan"
    if "양호" in r or "약세" in r:
        return "swing_scan"
    return "swing_scan"


def classify_exit_mode(reason: str) -> str:
    base = _base_reason(reason)
    if not base:
        return "unknown"
    if base.startswith("스캘핑") or "스캘핑 " in base:
        return "scalping"
    scalp_hints = ("빠른 익절", "보유시간 초과", "모멘텀 둔화", "응급 손절")
    if any(h in base for h in scalp_hints) and "스캘핑" not in base:
        # 구버전 로그 (예: "스캘핑 손절" 없이 "스캘핑 빠른 익절")
        if "스캘핑" in base:
            return "scalping"
    swing_hints = (
        "수익실현",
        "트레일링 스탑",
        "장마감 전량",
        "장마감 익절",
        "장마감 손실",
        "방어모드",
        "손절 (",
    )
    if any(base.startswith(h) or h in base for h in swing_hints):
        return "swing"
    if base.startswith("손절"):
        return "swing"
    return "unknown"


def classify_exit_category(reason: str) -> str:
    base = _base_reason(reason)
    if not base:
        return "other"
    lower = base.lower()
    if "장마감" in base or "eod" in lower:
        return "eod"
    if "방어모드" in base:
        return "defensive"
    if "모멘텀" in base or "둔화" in base:
        return "momentum"
    if "보유시간" in base:
        return "time_limit"
    if "트레일링" in base or "본전스탑" in base:
        return "trailing"
    if "손절" in base or "손실 정리" in base:
        return "stop_loss"
    if "익절" in base or "수익실현" in base or "빠른 익절" in base:
        if "부분" in base or "% 매도" in base:
            return "partial_tp"
        return "take_profit"
    return "other"


def _empty_bucket() -> dict:
    return {
        "count": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "win_rate_pct": None,
        "avg_profit_pct": None,
        "sum_profit_pct": 0.0,
        "best_pct": None,
        "worst_pct": None,
    }


def _update_bucket(bucket: dict, profit_pct: float) -> None:
    bucket["count"] += 1
    bucket["sum_profit_pct"] = round(bucket["sum_profit_pct"] + profit_pct, 4)
    if profit_pct > 0:
        bucket["wins"] += 1
    elif profit_pct < 0:
        bucket["losses"] += 1
    else:
        bucket["breakeven"] += 1
    if bucket["best_pct"] is None or profit_pct > bucket["best_pct"]:
        bucket["best_pct"] = round(profit_pct, 4)
    if bucket["worst_pct"] is None or profit_pct < bucket["worst_pct"]:
        bucket["worst_pct"] = round(profit_pct, 4)


def _finalize_bucket(bucket: dict) -> dict:
    n = bucket["count"]
    if n == 0:
        bucket["win_rate_pct"] = None
        bucket["avg_profit_pct"] = None
        return bucket
    bucket["win_rate_pct"] = round(bucket["wins"] / n * 100, 2)
    bucket["avg_profit_pct"] = round(bucket["sum_profit_pct"] / n, 4)
    bucket["sum_profit_pct"] = round(bucket["sum_profit_pct"], 4)
    return bucket


def _event_date(ts: str) -> date | None:
    try:
        return datetime.fromisoformat(ts).date()
    except ValueError:
        return None


def _labeled_buckets(
    buckets: dict[str, dict],
    labels: dict[str, str],
) -> list[dict]:
    rows = []
    for key, bucket in sorted(buckets.items(), key=lambda x: -x[1]["count"]):
        if bucket["count"] == 0:
            continue
        rows.append(
            {
                "key": key,
                "label": labels.get(key, key),
                **_finalize_bucket(bucket),
            }
        )
    return rows


def build_closed_trades(events: list[TradeEvent]) -> list[ClosedTrade]:
    """매수·매도 이벤트를 FIFO로 매칭해 완결 거래 목록 생성."""
    open_lots: dict[str, list[OpenLot]] = defaultdict(list)
    closed: list[ClosedTrade] = []

    for e in events:
        if e.event in ("buy_order", "trend_buy_order", "crash_buy_order"):
            if not e.code or e.qty is None or e.qty <= 0:
                continue
            open_lots[e.code].append(
                OpenLot(
                    entry_channel=classify_entry(e.event, e.reason),
                    ts=e.ts,
                    code=e.code,
                    name=e.name,
                    qty=e.qty,
                    price=e.price or 0,
                    buy_reason=e.reason,
                )
            )
            continue

        if e.event != "sell_order" or e.profit_pct is None:
            continue
        if not e.code or e.qty is None or e.qty <= 0:
            continue

        remaining = e.qty
        lots = open_lots.get(e.code, [])
        entry_channel = "unknown"
        entry_ts = ""
        buy_reason = ""
        entry_price: int | None = None

        while remaining > 0 and lots:
            lot = lots[0]
            take = min(remaining, lot.qty)
            entry_channel = lot.entry_channel
            entry_ts = lot.ts
            buy_reason = lot.buy_reason
            entry_price = lot.price or None
            lot.qty -= take
            remaining -= take
            if lot.qty <= 0:
                lots.pop(0)

        if remaining > 0 and not entry_ts:
            entry_channel = "unknown"

        closed.append(
            ClosedTrade(
                ts=e.ts,
                code=e.code,
                name=e.name,
                qty=e.qty,
                entry_channel=entry_channel,
                entry_ts=entry_ts,
                buy_reason=buy_reason,
                sell_reason=e.reason,
                exit_category=classify_exit_category(e.reason),
                exit_mode=classify_exit_mode(e.reason),
                profit_pct=float(e.profit_pct),
                entry_price=entry_price,
                sell_price=e.price,
            )
        )

    return closed


def build_journal_stats(
    *,
    path: Path | None = None,
    days: int | None = 30,
    from_date: date | None = None,
) -> dict:
    journal = TradeJournal(path or JOURNAL_FILE)
    events = journal.read_all()
    closed = build_closed_trades(events)

    if from_date is not None:
        cutoff = from_date
    elif days is not None and days > 0:
        cutoff = date.today() - timedelta(days=days - 1)
    else:
        cutoff = None

    if cutoff is not None:
        closed = [t for t in closed if (_event_date(t.ts) or date.min) >= cutoff]

    summary = _empty_bucket()
    by_entry: dict[str, dict] = defaultdict(_empty_bucket)
    by_exit_category: dict[str, dict] = defaultdict(_empty_bucket)
    by_exit_mode: dict[str, dict] = defaultdict(_empty_bucket)
    by_date: dict[str, dict] = defaultdict(_empty_bucket)

    for t in closed:
        _update_bucket(summary, t.profit_pct)
        _update_bucket(by_entry[t.entry_channel], t.profit_pct)
        _update_bucket(by_exit_category[t.exit_category], t.profit_pct)
        _update_bucket(by_exit_mode[t.exit_mode], t.profit_pct)
        d = _event_date(t.ts)
        if d:
            _update_bucket(by_date[d.isoformat()], t.profit_pct)

    daily_rows = []
    for dkey in sorted(by_date.keys(), reverse=True):
        b = _finalize_bucket(by_date[dkey])
        daily_rows.append({"date": dkey, **b})

    recent = []
    for t in reversed(closed[-20:]):
        recent.append(
            {
                "ts": t.ts,
                "code": t.code,
                "name": t.name,
                "qty": t.qty,
                "entry_label": ENTRY_LABELS.get(t.entry_channel, t.entry_channel),
                "exit_label": EXIT_CATEGORY_LABELS.get(
                    t.exit_category, t.exit_category
                ),
                "exit_mode_label": EXIT_MODE_LABELS.get(t.exit_mode, t.exit_mode),
                "profit_pct": round(t.profit_pct, 2),
                "sell_reason": _base_reason(t.sell_reason),
            }
        )
    recent.reverse()

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "journal_path": str(journal.path),
        "filter": {
            "days": days,
            "from_date": cutoff.isoformat() if cutoff else None,
        },
        "summary": _finalize_bucket(summary),
        "by_entry": _labeled_buckets(by_entry, ENTRY_LABELS),
        "by_exit_category": _labeled_buckets(by_exit_category, EXIT_CATEGORY_LABELS),
        "by_exit_mode": _labeled_buckets(by_exit_mode, EXIT_MODE_LABELS),
        "by_date": daily_rows,
        "recent_closed": recent,
    }


def format_stats_text(stats: dict) -> str:
    """텔레그램·터미널용 요약."""
    s = stats["summary"]
    if s["count"] == 0:
        return "【거래 통계】\n완결 매도 기록 없음 (기간 필터 확인)"

    flt = stats["filter"]
    if flt.get("days"):
        period = f"최근 {flt['days']}일"
    elif flt.get("from_date"):
        period = f"{flt['from_date']} 이후"
    else:
        period = "전체"
    lines = [
        f"【거래 통계】 {period}",
        f"완결 {s['count']}건 · 승 {s['wins']} / 패 {s['losses']}",
        f"승률 {s['win_rate_pct']}% · 평균 {s['avg_profit_pct']:+.2f}% · 합계 {s['sum_profit_pct']:+.2f}%",
        "",
        "■ 진입 채널",
    ]
    for row in stats["by_entry"]:
        lines.append(
            f"  {row['label']}: {row['count']}건 승률{row['win_rate_pct']}% "
            f"평균{row['avg_profit_pct']:+.2f}%"
        )
    lines.append("")
    lines.append("■ 청산 유형")
    for row in stats["by_exit_category"]:
        lines.append(
            f"  {row['label']}: {row['count']}건 승률{row['win_rate_pct']}% "
            f"평균{row['avg_profit_pct']:+.2f}%"
        )
    lines.append("")
    lines.append("■ 청산 모드(추정)")
    for row in stats["by_exit_mode"]:
        lines.append(
            f"  {row['label']}: {row['count']}건 승률{row['win_rate_pct']}% "
            f"평균{row['avg_profit_pct']:+.2f}%"
        )
    return "\n".join(lines)
