"""뉴스 필터 차순위·차트우선 적용 — 기술/차트 우선, 뉴스는 점수·알림."""

from __future__ import annotations

from config.config import (
    news_block_buy_sentiment_hard,
    news_filter_secondary,
    news_override_allow_buy_sentiment_floor,
    news_override_disable_buy_block,
    news_override_disable_defensive_mode,
    news_override_when_market_bullish,
    news_secondary_extra_penalty,
)

try:
    from config.config import chart_primary_mode
except ImportError:  # pragma: no cover
    chart_primary_mode = False

from trading.news_analyzer import MarketNewsContext


def apply_bullish_news_override(
    news_ctx: MarketNewsContext,
    *,
    strong_market: bool,
) -> tuple[bool, list[str]]:
    """강세장이면 키워드 리스크 점수와 무관하게 뉴스 매수 차단·방어모드를 완화."""
    if not (news_override_when_market_bullish and strong_market):
        return False, []

    changed = False
    notes: list[str] = []
    sentiment_floor = (
        news_block_buy_sentiment_hard
        if (news_filter_secondary or chart_primary_mode)
        else news_override_allow_buy_sentiment_floor
    )
    if (
        news_override_disable_buy_block
        and not news_ctx.allow_buy
        and news_ctx.sentiment >= sentiment_floor
    ):
        news_ctx.allow_buy = True
        changed = True
        notes.append("신규매수 중단 OFF")
    if news_override_disable_defensive_mode and news_ctx.defensive_mode:
        news_ctx.defensive_mode = False
        changed = True
        notes.append("방어모드 OFF")
    return changed, notes


def news_score_gate(
    *,
    base_score: float,
    news: MarketNewsContext | None,
    min_score: float = 0.0,
) -> tuple[bool, float, str]:
    """뉴스 게이트. 차트 우선·차순위에서는 하드 스톱 없음."""
    del min_score
    if news is None:
        return False, base_score, ""

    adjusted = base_score + float(news.score_adjustment)
    note_parts: list[str] = []

    if chart_primary_mode:
        if news.score_adjustment:
            note_parts.append(
                f"뉴스참고 {news.score_adjustment:+.1f}"
                f" (심리 {news.sentiment:+.2f}, 리스크 {news.risk_score:.2f})"
            )
        elif not news.allow_buy:
            note_parts.append(
                f"뉴스참고 주의 (심리 {news.sentiment:+.2f}, "
                f"리스크 {news.risk_score:.2f})"
            )
        return False, adjusted, " · ".join(note_parts)

    if news.sentiment < news_block_buy_sentiment_hard:
        return (
            True,
            adjusted,
            f"뉴스 극단 부정 중단 (심리 {news.sentiment:+.2f})",
        )

    if news_filter_secondary:
        if not news.allow_buy:
            adjusted = base_score + float(news_secondary_extra_penalty)
            note_parts.append(
                f"뉴스 차순위 페널티 {news_secondary_extra_penalty:+.1f}"
                f" (심리 {news.sentiment:+.2f}, 리스크 {news.risk_score:.2f})"
            )
        elif news.score_adjustment:
            note_parts.append(
                f"뉴스점수 {news.score_adjustment:+.1f}"
                f" (심리 {news.sentiment:+.2f})"
            )
        return False, adjusted, " · ".join(note_parts)

    if not news.allow_buy:
        return (
            True,
            adjusted,
            f"뉴스 필터 중단 (심리 {news.sentiment:+.2f}, "
            f"리스크 {news.risk_score:.2f})",
        )
    if news.score_adjustment:
        note_parts.append(f"뉴스점수 {news.score_adjustment:+.1f}")
    return False, adjusted, " · ".join(note_parts)
