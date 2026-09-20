"""Pending sell proposals and Telegram copy for advise-mode exits."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from pathlib import Path

PROPOSALS_FILE = Path(__file__).resolve().parent.parent / "data" / "trade_proposals.json"


@dataclass
class TradeProposal:
    id: str
    code: str
    name: str
    qty: int
    reason: str
    category: str
    profit_pct: float
    price: int
    ts: str
    status: str = "pending"  # pending | held | done | ignored
    held_date: str = ""
    ignored_at: str = ""


def sell_proposal_category(reason: str) -> str:
    base = (reason or "").split(" / ")[0].strip()
    if base.startswith("손절"):
        return "stop_loss"
    if "잔량 트레일링" in base:
        return "be_remainder"
    if base.startswith("본전스탑"):
        return "breakeven"
    if "수익보호 트레일링" in base:
        return "protect"
    if "장마감" in base:
        return "eod"
    if "오버나잇" in base:
        return "overnight"
    if "방어모드" in base:
        return "defensive"
    if "정체" in base:
        return "stagnation"
    if "중소형 트레일링" in base or "트레일링" in base:
        return "trailing"
    return base or "other"


def sell_proposal_markup(proposal_id: str) -> dict:
    pid = str(proposal_id)
    return {
        "inline_keyboard": [
            [
                {"text": "매도", "callback_data": f"sell:ok:{pid}"},
                {"text": "보류", "callback_data": f"sell:hold:{pid}"},
                {"text": "무시", "callback_data": f"sell:no:{pid}"},
            ]
        ]
    }


def format_sell_proposal_text(
    *,
    name: str,
    code: str,
    profit_pct: float,
    price: int,
    qty: int,
    reason: str,
) -> str:
    return (
        f"【매도 제안】 {name}({code})\n"
        f"수익률 {profit_pct:+.2f}% · {price:,}원 · {qty}주\n"
        f"사유: {reason}\n"
        "재해 손절(−5%) 전엔 자동 매도하지 않습니다."
    )


def format_buy_watchlist(
    rows: list[tuple[str, str, float]],
    *,
    skip_reason: str | None = None,
    bought_code: str | None = None,
) -> str:
    if bought_code:
        lines = ["이번 후보"]
        for i, (name, code, score) in enumerate(rows[:3], start=1):
            mark = " ← 매수" if code == bought_code else ""
            lines.append(f"{i}. {name}({code}) {score:.0f}점{mark}")
        return "\n".join(lines)
    if not rows:
        reason = skip_reason or "후보 없음"
        return f"【매수 후보】 없음\n매수 없음: {reason}"
    lines = ["【매수 후보】"]
    for i, (name, code, score) in enumerate(rows[:3], start=1):
        lines.append(f"{i}. {name}({code}) {score:.0f}점")
    if skip_reason:
        lines.append(f"매수 없음: {skip_reason}")
    return "\n".join(lines)


def _proposal_from_dict(data: dict) -> TradeProposal:
    allowed = {f.name for f in fields(TradeProposal)}
    return TradeProposal(**{k: v for k, v in (data or {}).items() if k in allowed})


class TradeProposalStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or PROPOSALS_FILE

    def _load(self) -> list[TradeProposal]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        items = raw.get("proposals", raw) if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []
        return [_proposal_from_dict(x) for x in items if isinstance(x, dict)]

    def _save(self, rows: list[TradeProposal]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"proposals": [asdict(r) for r in rows]}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, code: str) -> TradeProposal | None:
        code = str(code)
        for row in reversed(self._load()):
            if row.code == code:
                return row
        return None

    def get_pending(self, code: str) -> TradeProposal | None:
        code = str(code)
        for row in reversed(self._load()):
            if row.code == code and row.status == "pending":
                return row
        return None

    def get_by_id(self, proposal_id: str) -> TradeProposal | None:
        for row in self._load():
            if row.id == proposal_id:
                return row
        return None

    def is_held(self, code: str, category: str, today: date | None = None) -> bool:
        day = (today or date.today()).isoformat()
        for row in self._load():
            if (
                row.code == code
                and row.category == category
                and row.status == "held"
                and row.held_date == day
            ):
                return True
        return False

    def reset_day(self, today: date | None = None) -> None:
        day = (today or date.today()).isoformat()
        rows = []
        for row in self._load():
            if row.status == "held" and row.held_date and row.held_date < day:
                continue
            if row.status in {"done", "ignored"} and row.ts[:10] < day:
                continue
            rows.append(row)
        self._save(rows)

    def mark_held(self, proposal_id: str, *, today: date | None = None) -> TradeProposal | None:
        day = (today or date.today()).isoformat()
        rows = self._load()
        found = None
        for row in rows:
            if row.id == proposal_id:
                row.status = "held"
                row.held_date = day
                found = row
        if found:
            self._save(rows)
        return found

    def mark_ignored(
        self, proposal_id: str, *, now: datetime | None = None
    ) -> TradeProposal | None:
        ts = (now or datetime.now()).isoformat(timespec="seconds")
        rows = self._load()
        found = None
        for row in rows:
            if row.id == proposal_id:
                row.status = "ignored"
                row.ignored_at = ts
                found = row
        if found:
            self._save(rows)
        return found

    def mark_done(self, proposal_id: str) -> TradeProposal | None:
        rows = self._load()
        found = None
        for row in rows:
            if row.id == proposal_id:
                row.status = "done"
                found = row
        if found:
            self._save(rows)
        return found

    def upsert_pending(
        self,
        *,
        code: str,
        name: str,
        qty: int,
        reason: str,
        profit_pct: float,
        price: int,
        today: date | None = None,
        now: datetime | None = None,
        ignore_cooldown_min: int = 20,
    ) -> tuple[TradeProposal, bool]:
        """Return (proposal, should_notify)."""
        category = sell_proposal_category(reason)
        day = today or date.today()
        stamp = now or datetime.now()
        if self.is_held(code, category, day):
            existing = self.get(code)
            if existing is None:
                existing = TradeProposal(
                    id="",
                    code=code,
                    name=name,
                    qty=qty,
                    reason=reason,
                    category=category,
                    profit_pct=profit_pct,
                    price=price,
                    ts=stamp.isoformat(timespec="seconds"),
                    status="held",
                    held_date=day.isoformat(),
                )
            return existing, False

        rows = self._load()
        current: TradeProposal | None = None
        for row in rows:
            if row.code == code and row.status in {"pending", "ignored"}:
                current = row
        if current and current.status == "ignored" and current.ignored_at:
            try:
                ignored_at = datetime.fromisoformat(current.ignored_at)
            except ValueError:
                ignored_at = stamp
            elapsed = (stamp - ignored_at).total_seconds() / 60.0
            if elapsed < max(0, int(ignore_cooldown_min)):
                return current, False

        if current and current.status == "pending" and current.category == category:
            current.name = name
            current.qty = qty
            current.reason = reason
            current.profit_pct = profit_pct
            current.price = price
            current.ts = stamp.isoformat(timespec="seconds")
            self._save(rows)
            return current, False

        prop = TradeProposal(
            id=uuid.uuid4().hex[:12],
            code=code,
            name=name,
            qty=qty,
            reason=reason,
            category=category,
            profit_pct=profit_pct,
            price=price,
            ts=stamp.isoformat(timespec="seconds"),
            status="pending",
        )
        rows = [
            r
            for r in rows
            if not (r.code == code and r.status in {"pending", "ignored"})
        ]
        rows.append(prop)
        self._save(rows)
        return prop, True
