"""뉴스 심리 스냅샷을 오전/오후로 나눠 기록·조회."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from config.config import news_block_buy_sentiment

SENTIMENT_LOG_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "news_sentiment.jsonl"
)

SESSION_WINDOWS: dict[str, tuple[time, time]] = {
    "morning": (time(9, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(15, 30)),
}

SESSION_LABELS = {
    "morning": "오전",
    "afternoon": "오후",
    "other": "장외",
}


def session_for_time(now: datetime) -> str:
    t = now.time()
    for name, (start, end) in SESSION_WINDOWS.items():
        if start <= t < end:
            return name
    return "other"


def _empty_session() -> dict[str, Any]:
    return {
        "count": 0,
        "avg_sentiment": None,
        "min_sentiment": None,
        "max_sentiment": None,
        "avg_risk": None,
        "last_sentiment": None,
        "last_risk": None,
        "last_ts": None,
        "block_ratio": None,
    }


def append_snapshot(
    ctx: Any,
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now()
    target = path or SENTIMENT_LOG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": current.isoformat(timespec="seconds"),
        "session": session_for_time(current),
        "sentiment": round(float(getattr(ctx, "sentiment", 0.0)), 4),
        "risk_score": round(float(getattr(ctx, "risk_score", 0.0)), 4),
        "allow_buy": bool(getattr(ctx, "allow_buy", True)),
        "defensive_mode": bool(getattr(ctx, "defensive_mode", False)),
        "themes": list(getattr(ctx, "themes", []) or [])[:6],
    }
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_session_summary(
    *,
    target_date: date | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    day = target_date or date.today()
    log_path = path or SENTIMENT_LOG_FILE
    sessions = {
        "morning": _empty_session(),
        "afternoon": _empty_session(),
        "other": _empty_session(),
    }
    for row in _read_rows(log_path):
        ts_raw = str(row.get("ts") or "")
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        if ts.date() != day:
            continue
        key = str(row.get("session") or session_for_time(ts))
        if key not in sessions:
            key = "other"
        bucket = sessions[key]
        sent = float(row.get("sentiment") or 0.0)
        risk = float(row.get("risk_score") or 0.0)
        n = int(bucket["count"])
        bucket["count"] = n + 1
        bucket["avg_sentiment"] = (
            sent if n == 0 else (float(bucket["avg_sentiment"]) * n + sent) / (n + 1)
        )
        bucket["avg_risk"] = (
            risk if n == 0 else (float(bucket["avg_risk"]) * n + risk) / (n + 1)
        )
        bucket["min_sentiment"] = (
            sent
            if bucket["min_sentiment"] is None
            else min(float(bucket["min_sentiment"]), sent)
        )
        bucket["max_sentiment"] = (
            sent
            if bucket["max_sentiment"] is None
            else max(float(bucket["max_sentiment"]), sent)
        )
        bucket["last_sentiment"] = sent
        bucket["last_risk"] = risk
        bucket["last_ts"] = ts_raw
        blocked = int(bucket.get("_blocked") or 0)
        if sent <= news_block_buy_sentiment:
            blocked += 1
        bucket["_blocked"] = blocked

    for bucket in sessions.values():
        n = int(bucket["count"])
        blocked = int(bucket.pop("_blocked", 0))
        if n:
            bucket["avg_sentiment"] = round(float(bucket["avg_sentiment"]), 4)
            bucket["avg_risk"] = round(float(bucket["avg_risk"]), 4)
            bucket["min_sentiment"] = round(float(bucket["min_sentiment"]), 4)
            bucket["max_sentiment"] = round(float(bucket["max_sentiment"]), 4)
            bucket["last_sentiment"] = round(float(bucket["last_sentiment"]), 4)
            bucket["last_risk"] = round(float(bucket["last_risk"]), 4)
            bucket["block_ratio"] = round(blocked / n, 4)
    return {
        "date": day.isoformat(),
        "block_threshold": news_block_buy_sentiment,
        "sessions": sessions,
    }


def format_session_summary_text(summary: dict[str, Any] | None = None) -> str:
    data = summary or build_session_summary()
    lines = [f"【뉴스 심리 시간대】 {data['date']}"]
    for key in ("morning", "afternoon"):
        label = SESSION_LABELS[key]
        sess = data["sessions"][key]
        n = int(sess["count"])
        if n == 0:
            lines.append(f"  {label}: 기록 없음")
            continue
        avg = float(sess["avg_sentiment"])
        lo = float(sess["min_sentiment"])
        hi = float(sess["max_sentiment"])
        block_pct = float(sess["block_ratio"] or 0.0) * 100
        lines.append(
            f"  {label}: 평균 {avg:+.2f} (범위 {lo:+.2f}~{hi:+.2f}) · "
            f"{n}회 · 매수중단 {block_pct:.0f}%"
        )
    return "\n".join(lines)
