"""원금·수수료 설정 (config + runtime_settings 오버라이드)."""

from __future__ import annotations

from trading.mode_settings import SETTINGS_FILE, _load_settings, _save_settings


def _config_int(name: str, default: int = 0) -> int:
    try:
        import config.config as cfg

        val = getattr(cfg, name, default)
        return int(val) if val is not None else default
    except (ImportError, AttributeError, TypeError, ValueError):
        return default


def _config_float(name: str, default: float = 0.0) -> float:
    try:
        import config.config as cfg

        val = getattr(cfg, name, default)
        return float(val) if val is not None else default
    except (ImportError, AttributeError, TypeError, ValueError):
        return default


def get_initial_capital() -> int:
    """시작 원금(원). runtime_settings > config.initial_capital_krw."""
    saved = _load_settings().get("initial_capital_krw")
    if saved is not None:
        try:
            return max(0, int(saved))
        except (TypeError, ValueError):
            pass
    return max(0, _config_int("initial_capital_krw", 500_000_000))


def set_initial_capital(krw: int) -> int:
    value = max(0, int(krw))
    data = _load_settings()
    data["initial_capital_krw"] = value
    _save_settings(data)
    return value


def get_commission_rate_pct() -> float:
    saved = _load_settings().get("trade_commission_rate_pct")
    if saved is not None:
        try:
            return max(0.0, float(saved))
        except (TypeError, ValueError):
            pass
    return max(0.0, _config_float("trade_commission_rate_pct", 0.015))


def get_sell_tax_rate_pct() -> float:
    saved = _load_settings().get("trade_sell_tax_rate_pct")
    if saved is not None:
        try:
            return max(0.0, float(saved))
        except (TypeError, ValueError):
            pass
    return max(0.0, _config_float("trade_sell_tax_rate_pct", 0.20))


def fee_settings_snapshot() -> dict:
    return {
        "initial_capital_krw": get_initial_capital(),
        "commission_rate_pct": get_commission_rate_pct(),
        "sell_tax_rate_pct": get_sell_tax_rate_pct(),
        "settings_file": str(SETTINGS_FILE),
    }
