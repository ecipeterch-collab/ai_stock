"""하락장 우량주 급락 매수: 거래대금 상위 개별주의 과매도 구간 진입."""

from __future__ import annotations

from config.config import (
    strategy_crash_max_bullish_count,
    strategy_crash_max_flu_rt,
    strategy_crash_max_rank,
    strategy_crash_min_flu_rt,
    strategy_crash_min_score,
    strategy_crash_optimal_flu_rt,
    strategy_crash_scan_rank_top,
)
from trading.scoring import CandidateView, market_bullish_stats, parse_trade_value
from trading.symbol_filters import is_etf


def is_bear_market(candidates: list[CandidateView]) -> tuple[bool, str]:
    """상위 종목 양봉 수가 적을 때 하락장으로 판정."""
    bullish, total, _, msg = market_bullish_stats(
        candidates, top_n=strategy_crash_scan_rank_top
    )
    if total == 0:
        return False, "후보 없음"
    if bullish <= strategy_crash_max_bullish_count:
        return True, f"하락장 ({msg})"
    return False, f"양호 ({msg})"


def score_crash_candidate(candidate: CandidateView) -> float:
    """거래대금 순위·유동성·급락 깊이로 점수 산정."""
    if candidate.rank > strategy_crash_max_rank:
        return 0.0
    if not strategy_crash_min_flu_rt <= candidate.flu_rt <= strategy_crash_max_flu_rt:
        return 0.0

    rank_score = max(0, strategy_crash_max_rank + 1 - candidate.rank) * 3.0
    distance = abs(candidate.flu_rt - strategy_crash_optimal_flu_rt)
    flu_score = max(0.0, 15.0 - distance * 2.0)
    liquidity_score = min(parse_trade_value(candidate.trade_value) / 1_000_000, 20) * 0.15
    return rank_score + flu_score + liquidity_score


def filter_crash_candidates(
    candidates: list[CandidateView],
    held_codes: set[str],
) -> tuple[list[tuple[CandidateView, float]], list[str]]:
    eligible: list[tuple[CandidateView, float]] = []
    rejected: list[str] = []

    for cand in candidates:
        if cand.code in held_codes:
            rejected.append(f"{cand.name}: 보유 중")
            continue
        if is_etf(cand.name, cand.code):
            rejected.append(f"{cand.name}: ETF 제외")
            continue
        if cand.rank > strategy_crash_max_rank:
            rejected.append(
                f"{cand.name}: 순위 {cand.rank}위 (상위 {strategy_crash_max_rank}위 밖)"
            )
            continue
        if cand.flu_rt > strategy_crash_max_flu_rt:
            rejected.append(f"{cand.name}: 급락 부족 {cand.flu_rt:.2f}%")
            continue
        if cand.flu_rt < strategy_crash_min_flu_rt:
            rejected.append(f"{cand.name}: 과급락 {cand.flu_rt:.2f}%")
            continue
        score = score_crash_candidate(cand)
        if score < strategy_crash_min_score:
            rejected.append(f"{cand.name}: 점수 {score:.1f} < {strategy_crash_min_score}")
            continue
        eligible.append((cand, score))

    eligible.sort(key=lambda item: item[1], reverse=True)
    return eligible, rejected
