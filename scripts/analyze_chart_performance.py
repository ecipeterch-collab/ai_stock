#!/usr/bin/env python3
"""차트 점수·개별 신호별 승률·순손익 분석."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.account_pnl import enrich_closed_trade_fees
from trading.journal_stats import build_closed_trades
from trading.trade_journal import TradeJournal

CHART_RE = re.compile(r"차트\s+(\d+(?:\.\d+)?)점?\s*\(([^)]+)\)")
BUY_EVENTS = frozenset({"buy_order", "trend_buy_order", "crash_buy_order"})
VWAP_RE = re.compile(r"VWAP[^+]*([+-]?\d+\.?\d*)%")


def normalize_signal(sig: str) -> str:
    if sig.startswith("RSI"):
        return "RSI"
    if sig.startswith("VWAP근접"):
        return "VWAP근접"
    if sig.startswith("VWAP지지"):
        return "VWAP지지"
    if sig.startswith("VWAP "):
        return "VWAP(모멘텀)"
    if "MA>" in sig:
        return "MA정배열"
    if sig.startswith("일봉>"):
        return "일봉>MA"
    if "거래량" in sig:
        return sig.split()[0] if " " in sig else sig
    if sig.startswith("반등") or sig.startswith("단기"):
        return sig.split()[0]
    return sig


def wr(w: int, n: int) -> float:
    return w / n * 100 if n else 0.0


def main() -> int:
    journal = TradeJournal()
    events = journal.read_all()
    closed = build_closed_trades(events)
    closed_by_entry = {(t.entry_ts, t.code): t for t in closed if t.entry_ts}

    rows = []
    for e in events:
        if e.event not in BUY_EVENTS:
            continue
        m = CHART_RE.search(e.reason or "")
        score = float(m.group(1)) if m else None
        signals = [p.strip() for p in m.group(2).split(",")] if m else []
        trade = closed_by_entry.get((e.ts, e.code))
        net = win = None
        vwap_pct = None
        if trade:
            row = enrich_closed_trade_fees(trade)
            net = int(row["net_pnl_krw"])
            win = net > 0
            for sig in signals:
                vm = VWAP_RE.search(sig)
                if vm:
                    vwap_pct = float(vm.group(1))
                    break
        rows.append(
            {
                "score": score,
                "signals": signals,
                "net": net,
                "win": win,
                "vwap_pct": vwap_pct,
                "event": e.event,
            }
        )

    with_chart = [r for r in rows if r["score"] is not None]
    closed_rows = [r for r in with_chart if r["net"] is not None]

    print("=== 차트 점수별 (완결 거래) ===")
    by_score: dict[int, dict] = defaultdict(lambda: {"n": 0, "w": 0, "net": 0})
    for r in closed_rows:
        bucket = int(r["score"])
        by_score[bucket]["n"] += 1
        by_score[bucket]["net"] += r["net"]
        if r["win"]:
            by_score[bucket]["w"] += 1
    for s in sorted(by_score):
        b = by_score[s]
        print(f"  {s}점: {b['n']}건 승률{wr(b['w'], b['n']):.0f}% 순{b['net']:+,}원")

    print("\n=== 개별 신호별 (완결 거래, 승률순) ===")
    by_sig: dict[str, dict] = defaultdict(lambda: {"n": 0, "w": 0, "net": 0})
    for r in closed_rows:
        for sig in r["signals"]:
            key = normalize_signal(sig)
            by_sig[key]["n"] += 1
            by_sig[key]["net"] += r["net"]
            if r["win"]:
                by_sig[key]["w"] += 1
    ranked = sorted(by_sig.items(), key=lambda x: (wr(x[1]["w"], x[1]["n"]), x[1]["n"]), reverse=True)
    for k, b in ranked:
        if b["n"] < 2:
            continue
        print(f"  {k}: {b['n']}건 승률{wr(b['w'], b['n']):.0f}% 순{b['net']:+,}원")

    print("\n=== VWAP 괴리율 구간 (완결) ===")
    vwap_rows = [r for r in closed_rows if r["vwap_pct"] is not None]
    buckets = [
        ("VWAP근접 ±0.6% 이내", lambda v: abs(v) <= 0.6),
        ("VWAP지지 +0.6~+3%", lambda v: 0.6 < v <= 3.0),
        ("VWAP지지 +3~+10%", lambda v: 3.0 < v <= 10.0),
        ("VWAP지지 +10% 초과", lambda v: v > 10.0),
        ("VWAP 하회", lambda v: v < -0.3),
    ]
    for label, pred in buckets:
        subset = [r for r in vwap_rows if pred(r["vwap_pct"])]
        if not subset:
            continue
        wins = sum(1 for r in subset if r["win"])
        net = sum(r["net"] for r in subset)
        print(f"  {label}: {len(subset)}건 승률{wr(wins, len(subset)):.0f}% 순{net:+,}원")

    print("\n=== 신호 조합 TOP (3건+, 승률순) ===")
    by_combo: dict[str, dict] = defaultdict(lambda: {"n": 0, "w": 0, "net": 0})
    for r in closed_rows:
        keys = sorted(set(normalize_signal(s) for s in r["signals"]))
        combo = " + ".join(keys)
        by_combo[combo]["n"] += 1
        by_combo[combo]["net"] += r["net"]
        if r["win"]:
            by_combo[combo]["w"] += 1
    combo_ranked = sorted(
        by_combo.items(),
        key=lambda x: (wr(x[1]["w"], x[1]["n"]), x[1]["net"]),
        reverse=True,
    )
    for combo, b in combo_ranked:
        if b["n"] < 3:
            continue
        print(f"  [{b['n']}건 승{wr(b['w'], b['n']):.0f}%] {combo} → 순{b['net']:+,}원")

    print(f"\n차트 기록 매수 {len(with_chart)}건 / 완결 {len(closed_rows)}건 / 차트없음 {len(rows) - len(with_chart)}건")
    return 0


def analyze_backtest_summary() -> None:
    """backtest_chart_filter 결과를 JSON으로 재분석 (별도 실행용)."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backtest_chart_filter.py"), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout)
        return
    import json

    data = json.loads(proc.stdout)
    rows = [
        r
        for r in data["trades"]
        if r.get("chart_passed") is not None and r.get("net_pnl_krw") is not None
    ]

    def bucket(reason: str) -> str:
        if not reason:
            return "unknown"
        if "일봉 추세" in reason or "종가" in reason:
            return "일봉추세약함"
        if "RSI" in reason:
            return "RSI극단"
        if "VWAP" in reason:
            return "VWAP이탈"
        if "분봉" in reason or reason.startswith("일봉 "):
            return "데이터부족"
        if "차트점수" in reason:
            return "점수미달"
        return "기타"

    print("\n=== [백테스트] 차단 사유별 ===")
    blocked = [r for r in rows if not r["chart_passed"]]
    by_rej: dict[str, dict] = defaultdict(lambda: {"n": 0, "w": 0, "net": 0})
    for r in blocked:
        k = bucket(r.get("reject_reason", ""))
        by_rej[k]["n"] += 1
        by_rej[k]["net"] += r["net_pnl_krw"]
        if r["net_pnl_krw"] > 0:
            by_rej[k]["w"] += 1
    for k, b in sorted(by_rej.items(), key=lambda x: x[1]["net"]):
        print(f"  {k}: {b['n']}건 승률{wr(b['w'], b['n']):.0f}% 순{b['net']:+,}원")

    print("\n=== [백테스트] 통과 매수 — 신호 개수별 ===")
    passed = [r for r in rows if r["chart_passed"]]
    by_n: dict[int, dict] = defaultdict(lambda: {"n": 0, "w": 0, "net": 0})
    for r in passed:
        cnt = len(r.get("chart_reasons") or [])
        by_n[cnt]["n"] += 1
        by_n[cnt]["net"] += r["net_pnl_krw"]
        if r["net_pnl_krw"] > 0:
            by_n[cnt]["w"] += 1
    for n in sorted(by_n):
        b = by_n[n]
        print(f"  신호{n}개: {b['n']}건 승률{wr(b['w'], b['n']):.0f}% 순{b['net']:+,}원")

    print("\n=== [백테스트] 통과 매수 — 개별 신호 (3건+) ===")
    by_sig: dict[str, dict] = defaultdict(lambda: {"n": 0, "w": 0, "net": 0})
    for r in passed:
        for s in r.get("chart_reasons") or []:
            key = normalize_signal(s)
            by_sig[key]["n"] += 1
            by_sig[key]["net"] += r["net_pnl_krw"]
            if r["net_pnl_krw"] > 0:
                by_sig[key]["w"] += 1
    for k, b in sorted(
        by_sig.items(),
        key=lambda x: (wr(x[1]["w"], x[1]["n"]), x[1]["net"]),
        reverse=True,
    ):
        if b["n"] < 3:
            continue
        print(f"  {k}: {b['n']}건 승률{wr(b['w'], b['n']):.0f}% 순{b['net']:+,}원")

    s = data["summary"]
    print(
        f"\n통과 {s['chart_passed']}건 순{s['filtered_net_pnl_krw']:+,} / "
        f"차단 {s['chart_blocked']}건 순{s['blocked_net_pnl_krw']:+,} / "
        f"개선 {s['filtered_vs_actual_delta']:+,}원"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--backtest":
        analyze_backtest_summary()
        raise SystemExit(0)
    raise SystemExit(main())
