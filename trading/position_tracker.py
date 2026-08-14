from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from kiwoom.client import KiwoomClient

POSITIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "positions.json"


@dataclass
class PositionState:
    code: str
    name: str
    entry_time: str
    entry_price: int
    entry_qty: int = 0
    peak_profit_pct: float = 0.0
    partial_sold: bool = False
    tp_stage: int = 0  # 0: none, 1: stage1 done, 2: stage2 done
    addon_buys: int = 0
    be_scaled: bool = False  # 본전스탑 50% 완료 → 잔량 트레일
    pending_exit_key: str = ""
    pending_exit_count: int = 0

    def update_peak(self, profit_pct: float) -> None:
        if profit_pct > self.peak_profit_pct:
            self.peak_profit_pct = profit_pct


def _position_state_from_dict(data: dict) -> PositionState:
    allowed = {f.name for f in fields(PositionState)}
    return PositionState(**{k: v for k, v in (data or {}).items() if k in allowed})


class PositionTracker:
    """종목별 진입가·최고 수익률 추적 (트레일링/본전 스탑용)."""

    def __init__(self, path: Path = POSITIONS_FILE) -> None:
        self.path = path
        self._positions: dict[str, PositionState] = {}
        self._cooldowns: dict[str, str] = {}
        self._pending_exits: dict[str, tuple[str, int]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._positions = {}
            self._cooldowns = {}
            self._pending_exits = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "positions" in raw:
                positions_raw = raw.get("positions") or {}
                cooldowns_raw = raw.get("cooldowns") or {}
                self._positions = {
                    code: _position_state_from_dict(data)
                    for code, data in positions_raw.items()
                }
                self._cooldowns = {
                    str(code): str(ts) for code, ts in cooldowns_raw.items()
                }
            else:
                # backward compatible: older format was {code: PositionState}
                self._positions = {
                    code: _position_state_from_dict(data)
                    for code, data in (raw or {}).items()
                }
                self._cooldowns = {}
        except (json.JSONDecodeError, TypeError, KeyError):
            self._positions = {}
            self._cooldowns = {}
        self._normalize_codes()

    def _normalize_codes(self) -> None:
        """저장된 A접두 종목코드를 주문용 6자리로 통일."""
        dirty = False
        positions: dict[str, PositionState] = {}
        for code, state in self._positions.items():
            ncode = KiwoomClient.normalize_stock_code(code)
            if ncode != code or state.code != ncode:
                dirty = True
            state.code = ncode
            positions[ncode] = state
        new_cooldowns = {
            KiwoomClient.normalize_stock_code(code): ts
            for code, ts in self._cooldowns.items()
        }
        if new_cooldowns != self._cooldowns:
            dirty = True
        self._positions = positions
        self._cooldowns = new_cooldowns
        if dirty:
            self.save()

    @staticmethod
    def _norm(code: str) -> str:
        return KiwoomClient.normalize_stock_code(code)

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
        return self._positions.get(self._norm(code))

    def register(
        self,
        code: str,
        name: str,
        entry_price: int,
        entry_qty: int = 0,
        profit_pct: float = 0.0,
    ) -> PositionState:
        code = self._norm(code)
        state = PositionState(
            code=code,
            name=name,
            entry_time=datetime.now().isoformat(timespec="seconds"),
            entry_price=entry_price,
            entry_qty=max(0, int(entry_qty)),
            peak_profit_pct=max(0.0, profit_pct),
        )
        self._positions[code] = state
        self.save()
        return state

    def add_to_position(
        self,
        code: str,
        add_qty: int,
        add_price: int,
        *,
        profit_pct: float = 0.0,
    ) -> PositionState | None:
        """추가매수 후 평균단가·수량 갱신."""
        code = self._norm(code)
        state = self._positions.get(code)
        if state is None or add_qty <= 0 or add_price <= 0:
            return None
        old_qty = max(state.entry_qty, 1)
        new_qty = old_qty + add_qty
        state.entry_price = int(
            round((state.entry_price * old_qty + add_price * add_qty) / new_qty)
        )
        state.entry_qty = new_qty
        state.addon_buys += 1
        state.update_peak(profit_pct)
        self.save()
        return state

    def sync_holding(
        self,
        code: str,
        name: str,
        purchase_price: int,
        profit_pct: float,
    ) -> PositionState:
        code = self._norm(code)
        state = self._positions.get(code)
        if state is None:
            state = self.register(code, name, purchase_price, entry_qty=0, profit_pct=profit_pct)
        state.update_peak(profit_pct)
        self.save()
        return state

    def mark_partial_sold(self, code: str) -> None:
        state = self._positions.get(self._norm(code))
        if state:
            state.partial_sold = True
            self.save()

    def mark_tp_stage(self, code: str, stage: int) -> None:
        state = self._positions.get(self._norm(code))
        if state:
            state.tp_stage = max(int(stage), state.tp_stage)
            self.save()

    def mark_be_scaled(self, code: str) -> None:
        state = self._positions.get(self._norm(code))
        if state:
            state.be_scaled = True
            self.save()

    def note_exit_signal(self, code: str, key: str) -> int:
        """같은 청산 신호가 연속으로 나온 횟수. 키가 바뀌면 1부터 다시."""
        code = self._norm(code)
        state = self._positions.get(code)
        if state is None:
            prev_key, prev_count = self._pending_exits.get(code, ("", 0))
            count = prev_count + 1 if prev_key == key else 1
            self._pending_exits[code] = (key, count)
            return count
        if state.pending_exit_key == key:
            state.pending_exit_count += 1
        else:
            state.pending_exit_key = key
            state.pending_exit_count = 1
        self.save()
        return state.pending_exit_count

    def clear_exit_signal(self, code: str) -> None:
        code = self._norm(code)
        self._pending_exits.pop(code, None)
        state = self._positions.get(code)
        if state and (state.pending_exit_key or state.pending_exit_count):
            state.pending_exit_key = ""
            state.pending_exit_count = 0
            self.save()

    def remove(self, code: str) -> None:
        code = self._norm(code)
        if code in self._positions:
            del self._positions[code]
            self.save()
        # positions 에 없더라도 cooldown 은 남겨둔다 (재진입 제한)

    def codes(self) -> set[str]:
        return set(self._positions.keys())

    def holding_minutes(self, code: str, now: datetime | None = None) -> float | None:
        state = self._positions.get(self._norm(code))
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
        self._cooldowns[self._norm(code)] = current.isoformat(timespec="seconds")
        self.save()

    def cooldown_minutes_since_exit(
        self, code: str, now: datetime | None = None
    ) -> float | None:
        ts = self._cooldowns.get(self._norm(code))
        if not ts:
            return None
        try:
            exited = datetime.fromisoformat(ts)
        except ValueError:
            return None
        current = now or datetime.now()
        return (current - exited).total_seconds() / 60.0
