"""시장·뉴스 브리핑 분석 로직."""

from __future__ import annotations

from trading.news_analyzer import (
    MarketNewsAnalyzer,
    NewsItem,
    _compute_allow_buy,
    _compute_risk_score,
    _select_briefing_headlines,
)
from trading.news_priority import apply_bullish_news_override, news_score_gate


def test_analyze_does_not_count_category_name_as_keyword() -> None:
    """카테고리명 '지정학'이 제목에 없어도 부정 히트가 되면 안 된다."""
    analyzer = MarketNewsAnalyzer()
    items = [
        NewsItem(category="지정학", title="Central bank reviews financial stability outlook"),
        NewsItem(category="국내경제", title="반도체 실적 호조로 증시 반등"),
    ]
    ctx = analyzer.analyze(items)
    assert ctx.negative_hits == 0
    assert "지정학" not in ctx.themes


def test_risk_score_caps_soft_english_keyword_spam() -> None:
    """war/iran/sanction 반복은 고유 테마·저가중으로 리스크가 천장에 붙지 않는다."""
    hits = ["war", "iran", "sanction", "war", "iran", "sanction", "war"] * 3
    score = _compute_risk_score(hits, n_items=24)
    assert score < 0.70
    assert score > 0.0


def test_risk_score_strong_korean_themes_can_be_high() -> None:
    hits = ["전쟁", "침공", "봉쇄", "비상"]
    score = _compute_risk_score(hits, n_items=10)
    assert score >= 0.70


def test_geopolitics_english_rss_excluded_from_sentiment() -> None:
    """지정학 영문 RSS의 war/sanction은 심리 점수에 넣지 않는다."""
    analyzer = MarketNewsAnalyzer()
    items = [
        NewsItem(
            category="지정학",
            title="War sanctions Iran Hormuz geopolitical crisis missile",
        ),
        NewsItem(
            category="지정학",
            title="Israel invasion nuclear escalation",
        ),
        NewsItem(category="국내경제", title="반도체 실적 호조로 증시 반등 강세 성장"),
        NewsItem(category="글로벌경제", title="Markets rally on recovery and rate cut hopes"),
    ]
    ctx = analyzer.analyze(items)
    assert ctx.sentiment > 0
    assert ctx.negative_hits == 0
    assert any("[지정학]" in h for h in ctx.headlines)
    assert ctx.risk_score > 0


def test_geopolitics_only_headlines_leave_sentiment_neutral() -> None:
    """지정학 피드만 있으면 심리는 0, 리스크는 남긴다."""
    analyzer = MarketNewsAnalyzer()
    items = [
        NewsItem(
            category="지정학",
            title="War sanctions Iran Hormuz geopolitical crisis",
        ),
        NewsItem(
            category="지정학",
            title="Missile nuclear invasion escalation",
        ),
    ]
    ctx = analyzer.analyze(items)
    assert ctx.sentiment == 0.0
    assert ctx.negative_hits == 0
    assert ctx.positive_hits == 0
    assert ctx.risk_score > 0


def test_geopolitics_rss_noise_does_not_hard_block_buys() -> None:
    """지정학 RSS 노이즈만으로는 allow_buy가 False가 되지 않는다."""
    analyzer = MarketNewsAnalyzer()
    items = [
        NewsItem(
            category="지정학",
            title="US Lets Russian Oil Waiver Linked To Iran War Expire, Reimposing Sanctions",
        ),
        NewsItem(
            category="지정학",
            title="Hormuz geopolitical tensions and Israel missile concerns",
        ),
        NewsItem(category="국내경제", title="반도체 실적 호조로 증시 반등 강세"),
        NewsItem(category="글로벌경제", title="Markets rally on recovery and rate cut hopes"),
        NewsItem(category="국내경제", title="수출증가 서프라이즈에 성장 기대"),
        NewsItem(category="글로벌경제", title="Stimulus package supports easing outlook"),
    ]
    ctx = analyzer.analyze(items)
    assert ctx.risk_score < 0.70
    assert ctx.allow_buy is True


def test_defensive_mode_does_not_block_new_buys() -> None:
    """방어모드는 매도/축소용이며 신규매수 allow_buy와 분리된다."""
    from trading.news_analyzer import MarketNewsContext

    # 방어 ON + soft 부정(극단 아님) + 리스크 낮음 → allow_buy는 True여야 함
    ctx = MarketNewsContext(
        sentiment=-0.50,
        risk_score=0.10,
        defensive_mode=True,
        allow_buy=_compute_allow_buy(-0.50, 0.10),
    )
    assert ctx.defensive_mode is True
    assert ctx.allow_buy is True

    analyzer = MarketNewsAnalyzer()
    items = [
        NewsItem(category="국내경제", title="폭락 급락 약세 침체 위기"),
        NewsItem(category="국내경제", title="폭락 급락 약세"),
        NewsItem(category="글로벌경제", title="rally recovery beat estimates"),
    ]
    live = analyzer.analyze(items)
    # 방어가 켜져도 allow_buy는 defensive와 AND 되지 않음
    assert live.allow_buy == _compute_allow_buy(live.sentiment, live.risk_score)
    if live.defensive_mode:
        assert live.allow_buy is True or live.sentiment < -0.90


def test_compute_allow_buy_soft_block_requires_risk() -> None:
    """심리 soft 임계만으로는 차단하지 않고, 리스크가 동반돼야 한다."""
    assert _compute_allow_buy(-0.83, 0.0) is True
    assert _compute_allow_buy(-0.83, 0.25) is False


def test_compute_allow_buy_hard_sentiment_blocks() -> None:
    assert _compute_allow_buy(-0.95, 0.0) is False


def test_select_briefing_headlines_balances_categories() -> None:
    items = [
        NewsItem(category="국내경제", title=f"국내 {i}") for i in range(5)
    ] + [
        NewsItem(category="글로벌경제", title="Fed rate cut outlook"),
        NewsItem(category="지정학", title="Iran War sanctions update"),
    ]
    selected = _select_briefing_headlines(items, limit=5)
    cats = {line.split("]")[0].lstrip("[") for line in selected}
    assert "국내경제" in cats
    assert "지정학" in cats or "글로벌경제" in cats
    assert len(selected) == 5


def test_bullish_override_ignores_inflated_risk_score() -> None:
    """강세장이면 키워드 리스크 점수와 무관하게 매수 차단을 해제한다."""
    from trading.news_analyzer import MarketNewsContext

    ctx = MarketNewsContext(
        sentiment=-0.40,
        risk_score=1.0,
        allow_buy=False,
        defensive_mode=True,
    )
    changed, notes = apply_bullish_news_override(ctx, strong_market=True)
    assert changed is True
    assert ctx.allow_buy is True
    assert ctx.defensive_mode is False
    assert any("신규매수" in n for n in notes)


def test_bullish_override_clears_soft_block_when_secondary() -> None:
    """차순위+강세장: soft 부정(-0.78)도 주의 플래그를 해제한다."""
    from trading.news_analyzer import MarketNewsContext

    ctx = MarketNewsContext(
        sentiment=-0.78,
        risk_score=0.55,
        allow_buy=False,
        defensive_mode=True,
    )
    changed, notes = apply_bullish_news_override(ctx, strong_market=True)
    assert changed is True
    assert ctx.allow_buy is True
    assert ctx.defensive_mode is False


def test_news_score_gate_is_secondary_penalty_not_hard_stop() -> None:
    """차순위 뉴스: 기술 점수에 페널티만 주고 즉시 중단하지 않는다."""
    from trading.news_analyzer import MarketNewsContext

    ctx = MarketNewsContext(
        sentiment=-0.40,
        risk_score=0.55,
        allow_buy=False,
        score_adjustment=-4.0,
    )
    hard_stop, adjusted, note = news_score_gate(
        base_score=22.0,
        news=ctx,
        min_score=19.0,
    )
    assert hard_stop is False
    assert adjusted < 22.0
    assert "뉴스" in note


def test_news_score_gate_chart_primary_blocks_sentiment_at_soft_threshold() -> None:
    """차트우선이어도 심리 -0.70 이하면 신규매수를 막는다 (8/18 -0.88)."""
    from trading.news_analyzer import MarketNewsContext

    ctx = MarketNewsContext(
        sentiment=-0.88,
        risk_score=0.52,
        allow_buy=True,
        score_adjustment=-4.0,
    )
    hard_stop, _adjusted, note = news_score_gate(
        base_score=25.0,
        news=ctx,
        min_score=19.0,
    )
    assert hard_stop is True
    assert "중단" in note


def test_news_score_gate_chart_primary_advisory_above_block_threshold() -> None:
    from trading.news_analyzer import MarketNewsContext

    ctx = MarketNewsContext(
        sentiment=-0.40,
        risk_score=0.30,
        allow_buy=True,
        score_adjustment=-4.0,
    )
    hard_stop, adjusted, note = news_score_gate(
        base_score=25.0,
        news=ctx,
        min_score=19.0,
    )
    assert hard_stop is False
    assert adjusted < 25.0
    assert "참고" in note


def test_news_score_gate_hard_stop_only_on_extreme(monkeypatch) -> None:
    from trading.news_analyzer import MarketNewsContext
    import trading.news_priority as np

    monkeypatch.setattr(np, "chart_primary_mode", False)
    monkeypatch.setattr(np, "news_filter_secondary", False)

    ctx = MarketNewsContext(
        sentiment=-0.95,
        risk_score=0.85,
        allow_buy=False,
        score_adjustment=-4.0,
    )
    hard_stop, adjusted, note = news_score_gate(
        base_score=25.0,
        news=ctx,
        min_score=19.0,
    )
    assert hard_stop is True
    assert "극단" in note or "중단" in note
