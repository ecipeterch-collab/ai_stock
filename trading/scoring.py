from __future__ import annotations

from dataclasses import dataclass

from config.config import (
    strategy_max_flu_rt,
    strategy_min_bullish_count,
    strategy_min_flu_rt,
    strategy_min_rank_improve,
    strategy_optimal_flu_rt,
    strategy_scan_rank_top,
)


@dataclass
class CandidateView:
    code: str
    name: str
    rank: int
    prev_rank: int
    flu_rt: float
    current_price: int
    trade_value: str
    raw: dict

    @property
    def rank_improve(self) -> int:
        return max(0, self.prev_rank - self.rank)


def parse_trade_value(value: str) -> int:
    cleaned = value.strip().lstrip("0") or "0"
    try:
        return int(cleaned)
    except ValueError:
        return 0


def flu_rt_score(flu_rt: float, optimal: float = strategy_optimal_flu_rt) -> float:
    """등락률이 적정 구간(약 3%)에 가까울수록 높은 점수."""
    if flu_rt < strategy_min_flu_rt or flu_rt > strategy_max_flu_rt:
        return 0.0
    distance = abs(flu_rt - optimal)
    return max(0.0, 10.0 - distance * 2.5)


def score_candidate(candidate: CandidateView) -> float:
    rank_score = max(0, 11 - candidate.rank) * 3.0
    momentum_score = min(candidate.rank_improve, 15) * 2.5
    flu_score = flu_rt_score(candidate.flu_rt)
    liquidity_score = min(parse_trade_value(candidate.trade_value) / 1_000_000, 20)
    return rank_score + momentum_score + flu_score + liquidity_score * 0.1


def is_market_bullish(candidates: list[CandidateView]) -> tuple[bool, str]:
    """상위 종목 중 양봉 비율로 시장 분위기 판단."""
    top = candidates[:strategy_scan_rank_top]
    if not top:
        return False, "후보 없음"
    bullish = sum(1 for c in top if c.flu_rt > 0)
    if bullish < strategy_min_bullish_count:
        return False, f"약세장 ({bullish}/{len(top)}종목만 상승)"
    return True, f"양호 ({bullish}/{len(top)}종목 상승)"


def filter_and_rank_candidates(
    candidates: list[CandidateView],
    held_codes: set[str],
) -> tuple[list[tuple[CandidateView, float]], list[str]]:
    eligible: list[tuple[CandidateView, float]] = []
    rejected: list[str] = []

    for cand in candidates:
        if cand.code in held_codes:
            rejected.append(f"{cand.name}: 보유 중")
            continue
        if cand.flu_rt < strategy_min_flu_rt:
            rejected.append(f"{cand.name}: 등락률 {cand.flu_rt:.2f}% 낮음")
            continue
        if cand.flu_rt > strategy_max_flu_rt:
            rejected.append(f"{cand.name}: 등락률 {cand.flu_rt:.2f}% 과열")
            continue
        if cand.rank_improve < strategy_min_rank_improve:
            rejected.append(
                f"{cand.name}: 순위개선 부족 ({cand.prev_rank}→{cand.rank})"
            )
            continue
        score = score_candidate(cand)
        if score <= 0:
            rejected.append(f"{cand.name}: 점수 부족")
            continue
        eligible.append((cand, score))

    eligible.sort(key=lambda item: item[1], reverse=True)
    return eligible, rejected
