from __future__ import annotations

from dataclasses import dataclass

from config.config import (
    strategy_block_leveraged_etf,
    strategy_max_flu_rt,
    strategy_min_bullish_count,
    strategy_min_flu_rt,
    strategy_min_rank_improve,
    strategy_momentum_max_flu_rt,
    strategy_momentum_min_flu_rt,
    strategy_momentum_min_rank_improve,
    strategy_momentum_optimal_flu_rt,
    strategy_optimal_flu_rt,
    strategy_scan_rank_top,
)
from trading.symbol_filters import is_leveraged_etf


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


def flu_rt_score(
    flu_rt: float,
    optimal: float = strategy_optimal_flu_rt,
    lo: float | None = None,
    hi: float | None = None,
) -> float:
    """등락률이 적정 구간에 가까울수록 높은 점수."""
    lo = strategy_min_flu_rt if lo is None else lo
    hi = strategy_max_flu_rt if hi is None else hi
    if flu_rt < lo or flu_rt > hi:
        return 0.0
    distance = abs(flu_rt - optimal)
    return max(0.0, 10.0 - distance * 2.5)


def is_momentum_candidate(candidate: CandidateView) -> bool:
    """아침 모멘텀 채널: 상승 중 + 거래대금 순위 급등 (러너 프로필)."""
    return (
        strategy_momentum_min_flu_rt <= candidate.flu_rt <= strategy_momentum_max_flu_rt
        and candidate.rank_improve >= strategy_momentum_min_rank_improve
    )


def score_candidate(candidate: CandidateView, *, momentum: bool = False) -> float:
    rank_score = max(0, 11 - candidate.rank) * 3.0
    momentum_score = min(candidate.rank_improve, 15) * 2.5
    if momentum:
        flu_score = flu_rt_score(
            candidate.flu_rt,
            optimal=strategy_momentum_optimal_flu_rt,
            lo=strategy_momentum_min_flu_rt,
            hi=strategy_momentum_max_flu_rt,
        )
    else:
        flu_score = flu_rt_score(candidate.flu_rt)
    liquidity_score = min(parse_trade_value(candidate.trade_value) / 1_000_000, 20)
    return rank_score + momentum_score + flu_score + liquidity_score * 0.1


def market_bullish_stats(
    candidates: list[CandidateView],
    top_n: int | None = None,
) -> tuple[int, int, float, str]:
    """상위 종목 양봉 수·비율 (뉴스 override·약세 판정용)."""
    limit = top_n if top_n is not None else strategy_scan_rank_top
    top = candidates[:limit]
    if not top:
        return 0, 0, 0.0, "후보 없음"
    bullish = sum(1 for c in top if c.flu_rt > 0)
    ratio = bullish / len(top)
    msg = f"{bullish}/{len(top)}종목 상승"
    return bullish, len(top), ratio, msg


def is_market_bullish(candidates: list[CandidateView]) -> tuple[bool, str]:
    """상위 종목 중 양봉 비율로 시장 분위기 판단."""
    bullish, total, _, msg = market_bullish_stats(candidates)
    if total == 0:
        return False, "후보 없음"
    if bullish < strategy_min_bullish_count:
        return False, f"약세장 ({msg})"
    return True, f"양호 ({msg})"


def qualifies_for_position_addon(
    *,
    candidate: CandidateView,
    holding_profit_pct: float,
    peak_profit_pct: float,
    min_drop_pct: float,
    quality_max_rank: int,
    momentum_min_peak_pct: float,
) -> tuple[bool, str]:
    """보유 중 추가매수: 진입가 하락 + (우량주 또는 모멘텀 이력/프로필)."""
    if holding_profit_pct > -min_drop_pct:
        return (
            False,
            f"하락 부족 ({holding_profit_pct:+.2f}% > -{min_drop_pct:.1f}%)",
        )
    quality = candidate.rank <= quality_max_rank
    momentum = (
        is_momentum_candidate(candidate)
        or peak_profit_pct >= momentum_min_peak_pct
    )
    if not quality and not momentum:
        return False, "우량·모멘텀 조건 미충족"
    if quality and momentum:
        return True, "우량+모멘텀"
    return True, "우량" if quality else "모멘텀"


def filter_and_rank_candidates(
    candidates: list[CandidateView],
    held_codes: set[str],
    *,
    allow_momentum: bool = False,
) -> tuple[list[tuple[CandidateView, float]], list[str]]:
    eligible: list[tuple[CandidateView, float]] = []
    rejected: list[str] = []

    for cand in candidates:
        if cand.code in held_codes:
            rejected.append(f"{cand.name}: 보유 중")
            continue
        if strategy_block_leveraged_etf and is_leveraged_etf(cand.name, cand.code):
            rejected.append(f"{cand.name}: 레버리지/인버스 ETF 제외")
            continue

        # 아침 모멘텀 채널: 눌림목 구간 밖이라도 러너 프로필이면 허용
        momentum = allow_momentum and is_momentum_candidate(cand)

        if not momentum:
            if cand.flu_rt < strategy_min_flu_rt:
                rejected.append(f"{cand.name}: 등락률 {cand.flu_rt:.2f}% 낮음")
                continue
            if cand.flu_rt > strategy_max_flu_rt:
                rejected.append(f"{cand.name}: 등락률 {cand.flu_rt:.2f}% 과열")
                continue
            if cand.rank_improve < strategy_min_rank_improve and cand.rank > 5:
                rejected.append(
                    f"{cand.name}: 순위개선 부족 ({cand.prev_rank}→{cand.rank})"
                )
                continue
        score = score_candidate(cand, momentum=momentum)
        if score <= 0:
            rejected.append(f"{cand.name}: 점수 부족")
            continue
        eligible.append((cand, score))

    eligible.sort(key=lambda item: item[1], reverse=True)
    return eligible, rejected
