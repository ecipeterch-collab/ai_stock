from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


JOURNAL_FILE = Path(__file__).resolve().parent.parent / "data" / "trade_journal.jsonl"


@dataclass
class TradeEvent:
    ts: str
    event: str
    code: str = ""
    name: str = ""
    qty: int | None = None
    price: int | None = None
    profit_pct: float | None = None
    reason: str = ""
    ord_no: str = ""


class TradeJournal:
    """간단한 거래 이벤트 로그 (jsonl)."""

    def __init__(self, path: Path = JOURNAL_FILE) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: TradeEvent) -> None:
        payload = asdict(event)
        line = json.dumps(payload, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def log(
        self,
        event: str,
        *,
        code: str = "",
        name: str = "",
        qty: int | None = None,
        price: int | None = None,
        profit_pct: float | None = None,
        reason: str = "",
        ord_no: str = "",
    ) -> None:
        self.record(
            TradeEvent(
                ts=datetime.now().isoformat(timespec="seconds"),
                event=event,
                code=code,
                name=name,
                qty=qty,
                price=price,
                profit_pct=profit_pct,
                reason=reason,
                ord_no=ord_no,
            )
        )

    def tail(self, n: int = 20) -> list[TradeEvent]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out: list[TradeEvent] = []
        for line in lines[-n:]:
            try:
                raw = json.loads(line)
                out.append(TradeEvent(**raw))
            except Exception:
                continue
        return out

    def format_recent_summary(self, n: int = 10) -> str:
        events = self.tail(n)
        if not events:
            return "【최근 거래 로그】\n기록 없음"
        lines = ["【최근 거래 로그】"]
        for e in events[-n:]:
            core = f"{e.ts} · {e.event}"
            if e.name or e.code:
                core += f" · {e.name}({e.code})"
            if e.qty is not None:
                core += f" {e.qty}주"
            if e.price is not None:
                core += f" @ {e.price:,}"
            if e.profit_pct is not None:
                core += f" ({e.profit_pct:+.2f}%)"
            if e.reason:
                core += f" · {e.reason}"
            lines.append(core)
        return "\n".join(lines)

