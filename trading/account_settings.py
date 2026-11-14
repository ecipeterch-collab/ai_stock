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


def _parse_pct(raw: object, default: float) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(100.0, value)


def _require_pct(raw: object) -> float:
    try:
        value = float(str(raw).strip().rstrip("%"))
    except (TypeError, ValueError) as exc:
        raise ValueError("비율은 0보다 크고 100 이하인 숫자입니다. 예: 10") from exc
    if value <= 0 or value > 100:
        raise ValueError("비율은 0보다 크고 100 이하입니다. 예: 10")
    return value


def get_daily_trade_pct() -> float:
    """하루 매수 금액 한도. 보유자금 대비 %. 기본 10."""
    saved = _load_settings().get("daily_trade_pct")
    if saved is not None:
        return _parse_pct(saved, 10.0)
    return _parse_pct(_config_float("daily_trade_pct", 10.0), 10.0)


def set_daily_trade_pct(pct: float) -> float:
    value = _require_pct(pct)
    data = _load_settings()
    data["daily_trade_pct"] = value
    _save_settings(data)
    return value


def get_order_size_pct() -> float:
    """1회 매수 금액. 보유자금 대비 %. 기본 10."""
    saved = _load_settings().get("order_size_pct")
    if saved is not None:
        return _parse_pct(saved, 10.0)
    return _parse_pct(_config_float("order_size_pct", 10.0), 10.0)


def set_order_size_pct(pct: float) -> float:
    value = _require_pct(pct)
    data = _load_settings()
    data["order_size_pct"] = value
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


def round_trip_cost_pct() -> float:
    """매수·매도 수수료 + 매도세 (%). 본전스탑 비용 바닥."""
    return get_commission_rate_pct() * 2.0 + get_sell_tax_rate_pct()


def fee_settings_snapshot() -> dict:
    return {
        "initial_capital_krw": get_initial_capital(),
        "commission_rate_pct": get_commission_rate_pct(),
        "sell_tax_rate_pct": get_sell_tax_rate_pct(),
        "settings_file": str(SETTINGS_FILE),
    }
