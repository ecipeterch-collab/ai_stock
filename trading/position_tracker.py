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
        self._cooldowns: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._positions = {}
            self._cooldowns = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "positions" in raw:
                positions_raw = raw.get("positions") or {}
                cooldowns_raw = raw.get("cooldowns") or {}
                self._positions = {
                    code: PositionState(**data)
                    for code, data in positions_raw.items()
                }
                self._cooldowns = {
                    str(code): str(ts) for code, ts in cooldowns_raw.items()
                }
            else:
                # backward compatible: older format was {code: PositionState}
                self._positions = {
                    code: PositionState(**data)
                    for code, data in (raw or {}).items()
                }
                self._cooldowns = {}
        except (json.JSONDecodeError, TypeError, KeyError):
            self._positions = {}
            self._cooldowns = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "positions": {code: asdict(state) for code, state in self._positions.items()},
            "cooldowns": dict(self._cooldowns),
        }
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
        # positions 에 없더라도 cooldown 은 남겨둔다 (재진입 제한)

    def codes(self) -> set[str]:
        return set(self._positions.keys())

    def holding_minutes(self, code: str, now: datetime | None = None) -> float | None:
        state = self._positions.get(code)
        if state is None:
            return None
        try:
            entry = datetime.fromisoformat(state.entry_time)
        except ValueError:
            return None
        current = now or datetime.now()
        return (current - entry).total_seconds() / 60.0

    def mark_exit(self, code: str, now: datetime | None = None) -> None:
        """청산 시각 기록 (재진입 쿨다운용)."""
        current = now or datetime.now()
        self._cooldowns[code] = current.isoformat(timespec="seconds")
        self.save()

    def cooldown_minutes_since_exit(
        self, code: str, now: datetime | None = None
    ) -> float | None:
        ts = self._cooldowns.get(code)
        if not ts:
            return None
        try:
            exited = datetime.fromisoformat(ts)
        except ValueError:
            return None
        current = now or datetime.now()
        return (current - exited).total_seconds() / 60.0
