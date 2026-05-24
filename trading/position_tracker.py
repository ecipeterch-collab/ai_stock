from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

POSITIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "positions.json"


@dataclass
class PositionState:
    code: str
    name: str
    entry_time: str
    entry_price: int
    peak_profit_pct: float = 0.0
    partial_sold: bool = False

    def update_peak(self, profit_pct: float) -> None:
        if profit_pct > self.peak_profit_pct:
            self.peak_profit_pct = profit_pct


class PositionTracker:
    """종목별 진입가·최고 수익률 추적 (트레일링/본전 스탑용)."""

    def __init__(self, path: Path = POSITIONS_FILE) -> None:
        self.path = path
        self._positions: dict[str, PositionState] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._positions = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._positions = {
                code: PositionState(**data)
                for code, data in raw.items()
            }
        except (json.JSONDecodeError, TypeError, KeyError):
            self._positions = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {code: asdict(state) for code, state in self._positions.items()}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, code: str) -> PositionState | None:
        return self._positions.get(code)

    def register(
        self,
        code: str,
        name: str,
        entry_price: int,
        profit_pct: float = 0.0,
    ) -> PositionState:
        state = PositionState(
            code=code,
            name=name,
            entry_time=datetime.now().isoformat(timespec="seconds"),
            entry_price=entry_price,
            peak_profit_pct=max(0.0, profit_pct),
        )
        self._positions[code] = state
        self.save()
        return state

    def sync_holding(
        self,
        code: str,
        name: str,
        purchase_price: int,
        profit_pct: float,
    ) -> PositionState:
        state = self._positions.get(code)
        if state is None:
            state = self.register(code, name, purchase_price, profit_pct)
        state.update_peak(profit_pct)
        self.save()
        return state

    def mark_partial_sold(self, code: str) -> None:
        state = self._positions.get(code)
        if state:
            state.partial_sold = True
            self.save()

    def remove(self, code: str) -> None:
        if code in self._positions:
            del self._positions[code]
            self.save()

    def codes(self) -> set[str]:
        return set(self._positions.keys())
