"""실행 시 적용되는 전략 모드·주기."""

from config.config import (
    auto_interval_sec,
    auto_max_buys_per_day,
    scalping_auto_interval_sec,
    scalping_buy_afternoon_end,
    scalping_buy_afternoon_start,
    scalping_buy_morning_end,
    scalping_buy_morning_start,
    scalping_eod_cut_loss_time,
    scalping_eod_sell_time,
    scalping_max_buys_per_day,
    scalping_max_positions,
    scalping_portfolio_heat_limit,
    scalping_portfolio_heat_pct,
    strategy_buy_afternoon_end,
    strategy_buy_afternoon_start,
    strategy_buy_morning_end,
    strategy_buy_morning_start,
    strategy_eod_cut_loss_time,
    strategy_eod_sell_time,
    strategy_max_positions,
    strategy_portfolio_heat_limit,
    strategy_portfolio_heat_pct,
)
from trading.mode_settings import get_strategy_mode, mode_label, set_strategy_mode

__all__ = [
    "effective_auto_interval_sec",
    "effective_buy_windows",
    "effective_eod_times",
    "effective_max_buys_per_day",
    "effective_max_positions",
    "effective_portfolio_heat",
    "get_strategy_mode",
    "is_scalping_mode",
    "mode_label",
    "set_strategy_mode",
]


def is_scalping_mode() -> bool:
    return get_strategy_mode() == "scalping"


def effective_auto_interval_sec() -> int:
    if is_scalping_mode():
        return scalping_auto_interval_sec
    return auto_interval_sec


def effective_max_buys_per_day() -> int:
    if is_scalping_mode():
        return scalping_max_buys_per_day
    return auto_max_buys_per_day


def effective_max_positions() -> int:
    if is_scalping_mode():
        return scalping_max_positions
    return strategy_max_positions


def effective_buy_windows() -> tuple[str, str, str, str]:
    if is_scalping_mode():
        return (
            scalping_buy_morning_start,
            scalping_buy_morning_end,
            scalping_buy_afternoon_start,
            scalping_buy_afternoon_end,
        )
    return (
        strategy_buy_morning_start,
        strategy_buy_morning_end,
        strategy_buy_afternoon_start,
        strategy_buy_afternoon_end,
    )


def effective_eod_times() -> tuple[str, str]:
    if is_scalping_mode():
        return scalping_eod_cut_loss_time, scalping_eod_sell_time
    return strategy_eod_cut_loss_time, strategy_eod_sell_time


def effective_portfolio_heat() -> tuple[int, float]:
    if is_scalping_mode():
        return scalping_portfolio_heat_limit, scalping_portfolio_heat_pct
    return strategy_portfolio_heat_limit, strategy_portfolio_heat_pct
