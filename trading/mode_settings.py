"""실행 중 전략 모드(swing/scalping) 저장·조회."""

from __future__ import annotations

import json
from pathlib import Path

from config.config import strategy_mode as config_default_mode

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "data" / "runtime_settings.json"
VALID_MODES = frozenset({"swing", "scalping"})


def _normalize_mode(mode: str) -> str:
    key = str(mode).lower().strip()
    aliases = {
        "swing": "swing",
        "스윙": "swing",
        "scalping": "scalping",
        "scalp": "scalping",
        "스캘핑": "scalping",
        "단타": "scalping",
    }
    normalized = aliases.get(key)
    if normalized not in VALID_MODES:
        raise ValueError(
            f"지원하지 않는 모드: {mode!r} (swing | scalping)"
        )
    return normalized


def _load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_strategy_mode() -> str:
    saved = _load_settings().get("strategy_mode")
    if saved:
        try:
            return _normalize_mode(saved)
        except ValueError:
            pass
    try:
        return _normalize_mode(config_default_mode)
    except ValueError:
        return "swing"


def set_strategy_mode(mode: str) -> str:
    normalized = _normalize_mode(mode)
    data = _load_settings()
    data["strategy_mode"] = normalized
    _save_settings(data)
    return normalized


def mode_label(mode: str | None = None) -> str:
    current = mode or get_strategy_mode()
    return "스캘핑" if current == "scalping" else "스윙"


def get_auto_trading_enabled() -> bool | None:
    """runtime_settings 의 auto_trading_enabled. 없으면 None."""
    val = _load_settings().get("auto_trading_enabled")
    if val is None:
        return None
    return bool(val)


def set_auto_trading_enabled(enabled: bool) -> None:
    data = _load_settings()
    data["auto_trading_enabled"] = bool(enabled)
    _save_settings(data)


def normalize_ask_code(raw: str) -> str:
    code = str(raw).split("_")[0].strip().upper()
    if len(code) == 7 and code.startswith("A") and code[1:].isdigit():
        code = code[1:]
    if code.isdigit() and 1 <= len(code) <= 6:
        code = code.zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"종목코드 6자리가 아닙니다: {raw}")
    return code


def get_sell_ask_codes() -> list[str]:
    """매도 전에 사용자 확인을 받는 종목. 비어 있으면 전부 자동 매도."""
    raw = _load_settings().get("sell_ask_codes") or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        try:
            code = normalize_ask_code(str(item))
        except ValueError:
            continue
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def is_sell_ask_code(code: str) -> bool:
    try:
        norm = normalize_ask_code(code)
    except ValueError:
        return False
    return norm in set(get_sell_ask_codes())


def add_sell_ask_code(code: str) -> list[str]:
    norm = normalize_ask_code(code)
    codes = get_sell_ask_codes()
    if norm not in codes:
        codes.append(norm)
    data = _load_settings()
    data["sell_ask_codes"] = codes
    _save_settings(data)
    return codes


def remove_sell_ask_code(code: str) -> list[str]:
    norm = normalize_ask_code(code)
    codes = [c for c in get_sell_ask_codes() if c != norm]
    data = _load_settings()
    data["sell_ask_codes"] = codes
    _save_settings(data)
    return codes
