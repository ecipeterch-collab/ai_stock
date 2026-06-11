"""단기 스캘핑 매매: 소폭 익절·손절, 보유시간 제한, 모멘텀 급등 종목."""

from __future__ import annotations

from datetime import datetime

from config.config import (
    hard_stop_loss_pct,
    scalping_breakeven_activate_pct,
    scalping_breakeven_floor_pct,
    scalping_emergency_stop_loss_multiple,
    scalping_max_flu_rt,
    scalping_max_hold_minutes,
    scalping_min_bullish_count,
    scalping_min_flu_rt,
    scalping_min_hold_minutes_for_quick_exit,
    scalping_min_hold_seconds_for_stop_loss,
    scalping_min_rank_improve,
    scalping_min_score,
    scalping_momentum_stall_drop_pct,
    scalping_momentum_stall_min_peak_pct,
    scalping_optimal_flu_rt,
    scalping_scan_rank_top,
    scalping_trailing_activate_pct,
    scalping_trailing_drawdown_pct,
)
from trading.position_tracker import PositionState
from trading.scoring import CandidateView, parse_trade_value


def score_scalp_candidate(candidate: CandidateView) -> float:
    """거래대금·순위급등·적정 등락률 중심 점수."""
    if candidate.flu_rt < scalping_min_flu_rt or candidate.flu_rt > scalping_max_flu_rt:
        return 0.0
    rank_score = max(0, 12 - candidate.rank) * 4.0
    momentum_score = min(candidate.rank_improve, 20) * 3.0
    distance = abs(candidate.flu_rt - scalping_optimal_flu_rt)
    flu_score = max(0.0, 12.0 - distance * 4.0)
    liquidity_score = min(parse_trade_value(candidate.trade_value) / 500_000, 25)
    return rank_score + momentum_score + flu_score + liquidity_score * 0.15


def is_scalp_market_bullish(candidates: list[CandidateView]) -> tuple[bool, str]:
    top = candidates[:scalping_scan_rank_top]
    if not top:
        return False, "후보 없음"
    bullish = sum(1 for c in top if c.flu_rt > 0)
    if bullish < scalping_min_bullish_count:
        return False, f"약세 ({bullish}/{len(top)} 상승, 최소 {scalping_min_bullish_count})"
    return True, f"스캘프 적합 ({bullish}/{len(top)} 상승)"


def filter_scalp_candidates(
    candidates: list[CandidateView],
    held_codes: set[str],
) -> tuple[list[tuple[CandidateView, float]], list[str]]:
    eligible: list[tuple[CandidateView, float]] = []
    rejected: list[str] = []

    for cand in candidates:
        if cand.code in held_codes:
            rejected.append(f"{cand.name}: 보유 중")
            continue
        if cand.flu_rt < scalping_min_flu_rt:
            rejected.append(f"{cand.name}: 등락 {cand.flu_rt:.2f}% (약함)")
            continue
        if cand.flu_rt > scalping_max_flu_rt:
            rejected.append(f"{cand.name}: 등락 {cand.flu_rt:.2f}% (과열)")
            continue
        if cand.rank_improve < scalping_min_rank_improve:
            if cand.rank > 5:
                rejected.append(
                    f"{cand.name}: 순위급등 부족 ({cand.prev_rank}→{cand.rank})"
                )
                continue
        if cand.rank > scalping_scan_rank_top:
            rejected.append(f"{cand.name}: 순위 {cand.rank}위 (유동성 밖)")
            continue
        score = score_scalp_candidate(cand)
        if score < scalping_min_score:
            rejected.append(f"{cand.name}: 점수 {score:.1f} < {scalping_min_score}")
            continue
        eligible.append((cand, score))

    eligible.sort(key=lambda item: item[1], reverse=True)
    return eligible, rejected


def evaluate_scalp_sell(
    profit_pct: float,
    sellable_qty: int,
    state: PositionState | None,
    holding_minutes: float | None,
    *,
    is_eod_sell_all: bool,
    is_eod_cut_loss: bool,
) -> tuple[str | None, int]:
    """스캘핑 매도 신호: 짧은 보유·얇은 익절/손절."""
    if sellable_qty <= 0:
        return None, 0

    qty = sellable_qty
    peak = state.peak_profit_pct if state else profit_pct
    hold_min = holding_minutes if holding_minutes is not None else 0.0

    if is_eod_sell_all:
        return "스캘핑 장마감 전량 청산", qty

    if is_eod_cut_loss and profit_pct < 0:
        return "스캘핑 장마감 손실 정리", qty

    if hold_min >= scalping_max_hold_minutes:
        return f"보유시간 초과 ({hold_min:.0f}분 ≥ {scalping_max_hold_minutes}분)", qty

    # 고정 손절: 스캘핑 전용 얕은 손절 대신, -5% 손실 시 청산
    stop_loss = float(hard_stop_loss_pct)

    # 진입 직후 미세 노이즈로 손절이 나가지 않게 유예하되,
    # 손실이 과도하게 커지면(응급 손절) 즉시 청산
    min_hold_sec = max(0, int(scalping_min_hold_seconds_for_stop_loss))
    if min_hold_sec > 0 and hold_min * 60.0 < min_hold_sec:
        emergency = -stop_loss * float(scalping_emergency_stop_loss_multiple)
        if profit_pct <= emergency:
            return (f"응급 손절 ({profit_pct:.2f}% ≤ {emergency:.2f}%)", qty)
        if profit_pct <= -stop_loss:
            return None, 0

    if profit_pct <= -stop_loss:
        return f"고정 손절 ({profit_pct:.2f}% ≤ -{stop_loss:.2f}%)", qty

    # 수익실현(부분매도)은 strategy.py에서 공통 규칙(+10/+15/+20)에 따라 처리한다.

    if peak >= scalping_trailing_activate_pct:
        floor = peak - scalping_trailing_drawdown_pct
        if profit_pct < floor:
            return (
                f"스캘핑 트레일링 (고점 {peak:.2f}% → {profit_pct:.2f}%)",
                qty,
            )

    if peak >= scalping_breakeven_activate_pct:
        if profit_pct < scalping_breakeven_floor_pct:
            return (
                f"스캘핑 본전스탑 (고점 {peak:.2f}% → {profit_pct:.2f}%)",
                qty,
            )

    if (
        peak >= scalping_momentum_stall_min_peak_pct
        and profit_pct < peak - scalping_momentum_stall_drop_pct
        and hold_min >= scalping_min_hold_minutes_for_quick_exit
    ):
        return (
            f"모멘텀 둔화 (고점 {peak:.2f}% → {profit_pct:.2f}%)",
            qty,
        )

    return None, 0
