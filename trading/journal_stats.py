"""trade_journal.jsonl 집계: 진입 채널·청산 사유·승률·평균 손익."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from trading.market_utils import calc_pnl_krw, calc_profit_pct
from trading.market_regime import parse_regime_from_reason, parse_scale_from_reason
from trading.trade_journal import JOURNAL_FILE, TradeEvent, TradeJournal

ENTRY_LABELS = {
    "trend": "트렌드",
    "crash": "급락(우량)",
    "scalping_scan": "스캘핑(스캔)",
    "swing_scan": "스윙(스캔)",
    "momentum": "모멘텀(아침)",
    "addon": "추가매수",
    "unknown": "미매칭",
}

REGIME_LABELS = {
    "bull": "강세",
    "sideways": "횡보",
    "bear": "약세",
    "high_vol": "고변동",
    "unknown": "미기록",
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
    pnl_krw: int | None = None


def _base_reason(reason: str) -> str:
    if not reason:
        return ""
    return reason.split(" / ")[0].strip()


def classify_entry(event: str, reason: str) -> str:
    if event == "trend_buy_order":
        return "trend"
    if event == "crash_buy_order":
        return "crash"
    if event == "addon_buy_order":
        return "addon"
    if event != "buy_order":
        return "unknown"
    r = reason or ""
    if "모멘텀" in r:
        return "momentum"
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


def _labeled_channel_regime_buckets(buckets: dict[str, dict]) -> list[dict]:
    rows = []
    for key, bucket in sorted(buckets.items(), key=lambda x: -x[1]["count"]):
        if bucket["count"] == 0:
            continue
        channel, regime = key.split(":", 1) if ":" in key else (key, "unknown")
        ch_label = ENTRY_LABELS.get(channel, channel)
        r_label = REGIME_LABELS.get(regime, regime)
        rows.append(
            {
                "key": key,
                "channel": channel,
                "regime": regime,
                "label": f"{ch_label}·{r_label}",
                **_finalize_bucket(bucket),
            }
        )
    return rows


def _resolved_profit_pct(
    *,
    entry_price: int | None,
    sell_price: int | None,
    journal_pct: float | None,
) -> float:
    """체결가 기준 수익률 우선, 없으면 저널 기록값 사용."""
    if entry_price and sell_price:
        pct = calc_profit_pct(entry_price, sell_price)
        if pct is not None:
            return pct
    return float(journal_pct or 0.0)


def build_closed_trades(events: list[TradeEvent]) -> list[ClosedTrade]:
    """매수·매도 이벤트를 FIFO로 매칭해 완결 거래 목록 생성."""
    open_lots: dict[str, list[OpenLot]] = defaultdict(list)
    closed: list[ClosedTrade] = []

    for e in events:
        if e.event in (
            "buy_order",
            "trend_buy_order",
            "crash_buy_order",
            "addon_buy_order",
        ):
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

        if e.event != "sell_order":
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

        sell_price = e.price
        profit_pct = _resolved_profit_pct(
            entry_price=entry_price,
            sell_price=sell_price,
            journal_pct=e.profit_pct,
        )
        pnl_krw = (
            calc_pnl_krw(entry_price, sell_price, e.qty)
            if entry_price and sell_price
            else None
        )

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
                profit_pct=profit_pct,
                entry_price=entry_price,
                sell_price=sell_price,
                pnl_krw=pnl_krw,
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
    by_regime: dict[str, dict] = defaultdict(_empty_bucket)
    by_channel_regime: dict[str, dict] = defaultdict(_empty_bucket)
    by_date: dict[str, dict] = defaultdict(_empty_bucket)

    for t in closed:
        _update_bucket(summary, t.profit_pct)
        _update_bucket(by_entry[t.entry_channel], t.profit_pct)
        _update_bucket(by_exit_category[t.exit_category], t.profit_pct)
        _update_bucket(by_exit_mode[t.exit_mode], t.profit_pct)
        regime_key = parse_regime_from_reason(t.buy_reason)
        _update_bucket(by_regime[regime_key], t.profit_pct)
        ch_reg = f"{t.entry_channel}:{regime_key}"
        _update_bucket(by_channel_regime[ch_reg], t.profit_pct)
        d = _event_date(t.ts)
        if d:
            _update_bucket(by_date[d.isoformat()], t.profit_pct)

    daily_rows = []
    for dkey in sorted(by_date.keys(), reverse=True):
        b = _finalize_bucket(by_date[dkey])
        day_trades = [t for t in closed if (_event_date(t.ts) or date.min).isoformat() == dkey]
        day_pnl = sum(t.pnl_krw or 0 for t in day_trades)
        daily_rows.append({"date": dkey, "pnl_krw": day_pnl, **b})

    total_pnl_krw = sum(t.pnl_krw or 0 for t in closed)

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
                "entry_price": t.entry_price,
                "sell_price": t.sell_price,
                "pnl_krw": t.pnl_krw,
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
        "summary": {**_finalize_bucket(summary), "pnl_krw": total_pnl_krw},
        "by_entry": _labeled_buckets(by_entry, ENTRY_LABELS),
        "by_exit_category": _labeled_buckets(by_exit_category, EXIT_CATEGORY_LABELS),
        "by_exit_mode": _labeled_buckets(by_exit_mode, EXIT_MODE_LABELS),
        "by_regime": _labeled_buckets(by_regime, REGIME_LABELS),
        "by_channel_regime": _labeled_channel_regime_buckets(by_channel_regime),
        "by_date": daily_rows,
        "recent_closed": recent,
        "closed_trades": [
            {
                "ts": t.ts,
                "code": t.code,
                "name": t.name,
                "qty": t.qty,
                "entry_label": ENTRY_LABELS.get(t.entry_channel, t.entry_channel),
                "exit_label": EXIT_CATEGORY_LABELS.get(
                    t.exit_category, t.exit_category
                ),
                "profit_pct": round(t.profit_pct, 2),
                "entry_price": t.entry_price,
                "sell_price": t.sell_price,
                "pnl_krw": t.pnl_krw,
                "sell_reason": _base_reason(t.sell_reason),
            }
            for t in closed
        ],
    }


def build_daily_summary(*, target_date: date | None = None, path: Path | None = None) -> dict:
    """특정 일자(기본: 오늘) 매매·손익 요약."""
    from trading.account_pnl import enrich_closed_trade_fees

    day = target_date or date.today()
    journal = TradeJournal(path or JOURNAL_FILE)
    events = journal.read_all()
    closed = build_closed_trades(events)
    closed = [t for t in closed if (_event_date(t.ts) or date.min) == day]

    trades = []
    gross_total = fee_total = net_total = 0
    wins = losses = 0
    for t in closed:
        row = enrich_closed_trade_fees(t)
        row["entry_label"] = ENTRY_LABELS.get(t.entry_channel, t.entry_channel)
        row["exit_label"] = EXIT_CATEGORY_LABELS.get(t.exit_category, t.exit_category)
        row["sell_reason"] = _base_reason(t.sell_reason)
        trades.append(row)
        gross_total += int(row["gross_pnl_krw"])
        fee_total += int(row["total_fees_krw"])
        net_total += int(row["net_pnl_krw"])
        if row["net_pnl_krw"] > 0:
            wins += 1
        elif row["net_pnl_krw"] < 0:
            losses += 1

    count = len(trades)
    stats = build_journal_stats(path=path, from_date=day)
    summary = dict(stats.get("summary") or {})
    summary.update(
        {
            "gross_pnl_krw": gross_total,
            "total_fees_krw": fee_total,
            "net_pnl_krw": net_total,
            "net_wins": wins,
            "net_losses": losses,
        }
    )
    return {
        "date": day.isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "trades": trades,
        "by_entry": stats["by_entry"],
    }


def _fmt_krw(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:+,}원"


def format_daily_summary_text(summary: dict) -> str:
    """일별 매매·손익 요약 (텔레그램·터미널)."""
    s = summary.get("summary") or {}
    trades = summary.get("trades") or []
    day = summary.get("date") or date.today().isoformat()

    if s.get("count", 0) == 0:
        return f"【{day} 매매·손익】\n완결 거래 없음"

    lines = [
        f"【{day} 매매·손익】",
        (
            f"완결 {s['count']}건 · 승 {s['wins']} / 패 {s['losses']} "
            f"(승률 {s['win_rate_pct']}%)"
        ),
        (
            f"세전 {_fmt_krw(s.get('gross_pnl_krw', s.get('pnl_krw')))} · "
            f"수수료 {_fmt_krw(s.get('total_fees_krw'))} · "
            f"순손익 {_fmt_krw(s.get('net_pnl_krw', s.get('pnl_krw')))}"
        ),
        "",
        "■ 종목별",
    ]
    for t in trades:
        ts = t.get("ts", "")[11:16] if t.get("ts") else ""
        gross = _fmt_krw(t.get("gross_pnl_krw", t.get("pnl_krw")))
        net = _fmt_krw(t.get("net_pnl_krw", t.get("pnl_krw")))
        entry_px = t.get("entry_price")
        sell_px = t.get("sell_price")
        px_txt = ""
        if entry_px and sell_px:
            px_txt = f" · {entry_px:,}→{sell_px:,}"
        lines.append(
            f"  {ts} {t.get('name', '')}({t.get('code', '')}) "
            f"{t.get('qty', 0)}주 "
            f"{t.get('profit_pct', 0):+.2f}% "
            f"(세전 {gross} → 순 {net}){px_txt}"
        )
        exit_label = t.get("exit_label")
        if exit_label and exit_label != "기타":
            lines.append(f"    └ {exit_label} · {t.get('sell_reason', '')}")
        elif t.get("sell_reason"):
            lines.append(f"    └ {t.get('sell_reason', '')}")

    by_entry = summary.get("by_entry") or []
    if by_entry:
        lines.append("")
        lines.append("■ 진입 채널")
        for row in by_entry:
            lines.append(
                f"  {row['label']}: {row['count']}건 "
                f"평균{row['avg_profit_pct']:+.2f}%"
            )
    lines.append("")
    lines.append("※ 순손익 = 체결가 손익 − 수수료 − 매도세")
    return "\n".join(lines)


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
        (
            f"승률 {s['win_rate_pct']}% · 평균 {s['avg_profit_pct']:+.2f}% · "
            f"합계 {s['sum_profit_pct']:+.2f}% · 손익 {_fmt_krw(s.get('pnl_krw'))}"
        ),
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
    by_regime = stats.get("by_regime") or []
    if by_regime:
        lines.append("")
        lines.append("■ 시장 국면(진입 시)")
        for row in by_regime:
            lines.append(
                f"  {row['label']}: {row['count']}건 승률{row['win_rate_pct']}% "
                f"평균{row['avg_profit_pct']:+.2f}%"
            )
    by_cr = stats.get("by_channel_regime") or []
    if by_cr:
        lines.append("")
        lines.append("■ 채널×국면")
        for row in by_cr[:12]:
            lines.append(
                f"  {row['label']}: {row['count']}건 승률{row['win_rate_pct']}% "
                f"평균{row['avg_profit_pct']:+.2f}%"
            )
    return "\n".join(lines)
