"""차트 우선 매수 — 유니버스 필터와 참고용 메모."""

from __future__ import annotations

from trading.scoring import CandidateView, is_market_bullish, score_candidate
from trading.symbol_filters import is_etf, is_leveraged_etf


def filter_chart_primary_universe(
    candidates: list[CandidateView],
    held_codes: set[str],
    *,
    block_etf: bool = True,
    block_leveraged_etf: bool = True,
) -> tuple[list[CandidateView], list[str]]:
    """보유·ETF만 제외. 등락/점수/국면은 제외하지 않는다."""
    kept: list[CandidateView] = []
    rejected: list[str] = []
    for cand in candidates:
        if cand.code in held_codes:
            rejected.append(f"{cand.name}: 보유 중")
            continue
        if block_etf and is_etf(cand.name, cand.code):
            rejected.append(f"{cand.name}: ETF 제외")
            continue
        if (
            not block_etf
            and block_leveraged_etf
            and is_leveraged_etf(cand.name, cand.code)
        ):
            rejected.append(f"{cand.name}: 레버리지/인버스 ETF 제외")
            continue
        kept.append(cand)
    return kept, rejected


def build_buy_advisory_notes(
    *,
    candidate: CandidateView | None,
    market_msg: str,
    regime_msg: str,
    news_msg: str,
    strategy_score: float | None,
    strategy_min_score: float,
) -> str:
    """매수 사유에 붙일 참고 메모 (매수 중단 사유가 아님)."""
    parts: list[str] = []
    if market_msg:
        parts.append(f"시장참고 {market_msg}")
    if regime_msg:
        parts.append(f"국면참고 {regime_msg}")
    if candidate is not None:
        parts.append(f"등락 {candidate.flu_rt:+.2f}%")
    if strategy_score is not None:
        flag = "충족" if strategy_score >= strategy_min_score else "미달(참고)"
        parts.append(f"전략점수 {strategy_score:.1f}/{strategy_min_score:.1f} {flag}")
    if news_msg:
        parts.append(f"뉴스참고 {news_msg}")
    return " · ".join(parts)


def advisory_market_note(candidates: list[CandidateView]) -> str:
    bullish, msg = is_market_bullish(candidates)
    return f"{'강세' if bullish else '약세'} · {msg}"


def advisory_strategy_score(candidate: CandidateView, *, momentum: bool) -> float:
    return score_candidate(candidate, momentum=momentum)
