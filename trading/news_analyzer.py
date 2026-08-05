from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from urllib.parse import quote

import requests

from config.config import (
    news_block_buy_risk_floor,
    news_block_buy_risk_score,
    news_block_buy_sentiment,
    news_block_buy_sentiment_hard,
    news_cache_minutes,
    news_defensive_sell_sentiment,
    news_enabled,
    news_force_reduce_risk_score,
    news_max_headlines,
    news_score_boost_positive,
    news_score_penalty_negative,
)

# Google News RSS (키워드 검색, API 키 불필요)
NEWS_FEEDS: list[tuple[str, str]] = [
    ("국내경제", "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"),
    ("글로벌경제", "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"),
    ("지정학", "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"),
]

NEWS_QUERIES: dict[str, str] = {
    "국내경제": "한국 증시 경제 금리 실적",
    "글로벌경제": "global economy markets fed inflation",
    "지정학": "geopolitical conflict war sanctions oil",
}

POSITIVE_KEYWORDS = [
    "금리인하",
    "인하",
    "협상타결",
    "휴전",
    "성장",
    "호조",
    "서프라이즈",
    "반등",
    "강세",
    "수출증가",
    "stimulus",
    "rate cut",
    "peace",
    "deal",
    "rally",
    "surge",
    "recovery",
    "beat estimates",
    "easing",
]

NEGATIVE_KEYWORDS = [
    "전쟁",
    "공습",
    "제재",
    "붕괴",
    "폭락",
    "급락",
    "약세",
    "침체",
    "불황",
    "실적쇼크",
    "파산",
    "디폴트",
    "금리인상",
    "인상",
    "관세",
    "지정학",
    "긴장",
    "충돌",
    "war",
    "invasion",
    "sanction",
    "recession",
    "crash",
    "plunge",
    "selloff",
    "crisis",
    "default",
    "tariff",
    "escalation",
    "missile",
    "nuclear",
]

RISK_KEYWORDS = [
    "비상",
    "전시",
    "침공",
    "공격",
    "봉쇄",
    "제재",
    "전쟁",
    "공습",
    "이란",
    "호르무즈",
    "bank run",
    "black swan",
    "emergency",
    "invasion",
    "nuclear",
    "middle east",
    "중동",
    "북한",
    "대만",
    "taiwan",
    "ukraine",
    "이스라엘",
    "gaza",
    "war",
    "sanction",
    "iran",
    "hormuz",
    "geopolitical",
    "missile",
    "israel",
]

# RSS에 상시 등장하는 영문 단일어 — 고유 테마당 저가중
_SOFT_RISK_KEYWORDS = {
    "war",
    "sanction",
    "iran",
    "hormuz",
    "geopolitical",
    "missile",
    "israel",
    "gaza",
    "ukraine",
    "taiwan",
    "nuclear",
    "invasion",
}


@dataclass
class NewsItem:
    category: str
    title: str
    published: str = ""


@dataclass
class MarketNewsContext:
    sentiment: float = 0.0  # -1.0 ~ +1.0
    risk_score: float = 0.0  # 0.0 ~ 1.0
    positive_hits: int = 0
    negative_hits: int = 0
    risk_hits: int = 0
    allow_buy: bool = True
    defensive_mode: bool = False
    score_adjustment: float = 0.0
    themes: list[str] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)
    fetched_at: str = ""
    error: str = ""

    def summary_message(self) -> str:
        mood = "중립"
        if self.sentiment >= 0.25:
            mood = "긍정"
        elif self.sentiment <= -0.25:
            mood = "부정"

        risk = "낮음"
        if self.risk_score >= 0.65:
            risk = "높음"
        elif self.risk_score >= 0.35:
            risk = "보통"

        buy_label = "가능" if self.allow_buy else "주의(차순위 페널티)"
        lines = [
            "【시장·뉴스 브리핑】",
            f"분위기: {mood} ({self.sentiment:+.2f}) · 리스크: {risk} ({self.risk_score:.2f})",
            f"신규매수: {buy_label} · "
            f"방어모드: {'ON' if self.defensive_mode else 'OFF'} (매도 보조)",
        ]
        if self.themes:
            lines.append("핵심 키워드: " + ", ".join(self.themes[:6]))
        if self.headlines:
            lines.append("주요 헤드라인:")
            for title in self.headlines[:5]:
                lines.append(f"  · {title[:80]}")
        if self.error:
            lines.append(f"(참고: {self.error})")
        return "\n".join(lines)


def _select_briefing_headlines(
    items: list[NewsItem],
    limit: int = 5,
    *,
    priority_titles: set[str] | None = None,
) -> list[str]:
    """카테고리 균등 + 키워드 히트 우선으로 브리핑 헤드라인 선택."""
    if not items or limit <= 0:
        return []

    priority = priority_titles or set()
    by_cat: dict[str, list[NewsItem]] = {}
    for item in items:
        by_cat.setdefault(item.category, []).append(item)

    for cat in by_cat:
        by_cat[cat].sort(
            key=lambda it: (0 if it.title in priority else 1, it.title)
        )

    selected: list[NewsItem] = []
    seen: set[tuple[str, str]] = set()
    cats = list(by_cat.keys())
    while len(selected) < limit and cats:
        progressed = False
        next_cats: list[str] = []
        for cat in cats:
            bucket = by_cat[cat]
            if not bucket:
                continue
            item = bucket.pop(0)
            key = (item.category, item.title)
            if key not in seen:
                selected.append(item)
                seen.add(key)
                progressed = True
            if bucket:
                next_cats.append(cat)
            if len(selected) >= limit:
                break
        cats = next_cats
        if not progressed:
            break

    return [f"[{i.category}] {i.title}" for i in selected]


def _risk_keyword_weight(keyword: str) -> float:
    """영문 단일어 리스크 키워드는 저가중, 그 외(한글·복합)는 정상 가중."""
    return 0.35 if keyword.lower() in _SOFT_RISK_KEYWORDS else 1.0


def _compute_risk_score(risk_hits: list[str], n_items: int) -> float:
    """고유 테마·가중치 기반 리스크. 동일 키워드 반복·영문 스팸에 둔감."""
    if n_items <= 0:
        return 0.0
    unique_weights: dict[str, float] = {}
    for kw in risk_hits:
        key = kw.lower()
        unique_weights[key] = _risk_keyword_weight(kw)
    if not unique_weights:
        return 0.0
    weighted = sum(unique_weights.values())
    # 풀웨이트 ~4테마에서 고위험권
    score = min(1.0, weighted / 4.0)
    # 영문 soft 키워드만이면 하드 차단 임계(0.70) 미만으로 캡
    if all(k in _SOFT_RISK_KEYWORDS for k in unique_weights):
        score = min(score, 0.65)
    return score


def _compute_allow_buy(sentiment: float, risk_score: float) -> bool:
    """복합 뉴스 필터: 고위험·극단부정·(부정 soft + 리스크) 동반 시에만 주의 플래그.

    방어모드와 독립. 차순위 모드에서는 이 값이 False여도 즉시 매수 중단하지 않고
    점수 페널티로만 반영된다.
    """
    if risk_score >= news_block_buy_risk_score:
        return False
    if sentiment < news_block_buy_sentiment_hard:
        return False
    if sentiment < news_block_buy_sentiment and risk_score >= news_block_buy_risk_floor:
        return False
    return True


class MarketNewsAnalyzer:
    """경제·지정학 뉴스 RSS 기반 시장 심리 분석."""

    def __init__(self) -> None:
        self._cache: MarketNewsContext | None = None
        self._cache_ts: float = 0.0

    def _cache_valid(self) -> bool:
        if self._cache is None:
            return False
        return (time.time() - self._cache_ts) < news_cache_minutes * 60

    @staticmethod
    def _clean_text(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"<[^>]+>", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def _fetch_rss(self, url: str, category: str, limit: int) -> list[NewsItem]:
        response = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (compatible; KiwoomBot/1.0)"},
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items: list[NewsItem] = []

        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is None or not title_el.text:
                continue
            pub = ""
            pub_el = item.find("pubDate")
            if pub_el is not None and pub_el.text:
                pub = pub_el.text.strip()
            items.append(
                NewsItem(
                    category=category,
                    title=self._clean_text(title_el.text),
                    published=pub,
                )
            )
            if len(items) >= limit:
                break
        return items

    def fetch_headlines(self) -> list[NewsItem]:
        per_feed = max(3, news_max_headlines // len(NEWS_FEEDS))
        headlines: list[NewsItem] = []
        errors: list[str] = []

        for category, template in NEWS_FEEDS:
            query = NEWS_QUERIES.get(category, category)
            url = template.format(q=quote(query))
            try:
                headlines.extend(self._fetch_rss(url, category, per_feed))
            except requests.RequestException as exc:
                errors.append(f"{category}:{exc}")

        if not headlines and errors:
            raise requests.RequestException("; ".join(errors))
        return headlines

    def _count_keyword_hits(self, text: str, keywords: list[str]) -> list[str]:
        lowered = text.lower()
        hits = []
        for kw in keywords:
            if kw.lower() in lowered:
                hits.append(kw)
        return hits

    def analyze(self, headlines: list[NewsItem] | None = None) -> MarketNewsContext:
        if not news_enabled:
            return MarketNewsContext(
                allow_buy=True,
                fetched_at=datetime.now().isoformat(timespec="seconds"),
                error="뉴스 분석 비활성",
            )

        # 호출자가 헤드라인을 직접 넘기면 캐시를 쓰지 않는다(테스트·수동 분석용).
        if headlines is None and self._cache_valid():
            return self._cache  # type: ignore[return-value]

        ctx = MarketNewsContext(
            fetched_at=datetime.now().isoformat(timespec="seconds"),
        )

        try:
            items = headlines if headlines is not None else self.fetch_headlines()
        except requests.RequestException as exc:
            ctx.error = f"뉴스 수집 실패 ({exc})"
            ctx.allow_buy = True  # 뉴스 실패 시 기술적 매매만 진행
            if headlines is None:
                self._cache = ctx
                self._cache_ts = time.time()
            return ctx

        if not items:
            ctx.error = "수집된 헤드라인 없음"
            if headlines is None:
                self._cache = ctx
                self._cache_ts = time.time()
            return ctx

        pos_hits: list[str] = []
        neg_hits: list[str] = []
        risk_hits: list[str] = []
        priority_titles: set[str] = set()

        for item in items:
            # 카테고리명은 피드 라벨이므로 키워드 점수에 넣지 않는다.
            text = item.title
            item_pos = self._count_keyword_hits(text, POSITIVE_KEYWORDS)
            item_neg = self._count_keyword_hits(text, NEGATIVE_KEYWORDS)
            item_risk = self._count_keyword_hits(text, RISK_KEYWORDS)
            pos_hits.extend(item_pos)
            neg_hits.extend(item_neg)
            risk_hits.extend(item_risk)
            if item_pos or item_neg or item_risk:
                priority_titles.add(item.title)

        ctx.positive_hits = len(pos_hits)
        ctx.negative_hits = len(neg_hits)
        ctx.risk_hits = len(risk_hits)

        # 심리는 긍정/부정만으로 계산 (리스크는 별도 축 — 분모 희석 방지)
        sent_total = max(ctx.positive_hits + ctx.negative_hits, 1)
        ctx.sentiment = (ctx.positive_hits - ctx.negative_hits) / sent_total
        ctx.sentiment = max(-1.0, min(1.0, ctx.sentiment))
        ctx.risk_score = _compute_risk_score(risk_hits, len(items))

        theme_counter: dict[str, int] = {}
        for kw in neg_hits + risk_hits + pos_hits:
            theme_counter[kw] = theme_counter.get(kw, 0) + 1
        ctx.themes = [
            k for k, _ in sorted(theme_counter.items(), key=lambda x: -x[1])[:8]
        ]

        briefing = _select_briefing_headlines(
            items,
            limit=min(5, news_max_headlines),
            priority_titles=priority_titles,
        )
        # 전체 목록은 유지하되, 브리핑용 균등 선택을 앞에 둔다.
        rest = [
            f"[{i.category}] {i.title}"
            for i in items
            if f"[{i.category}] {i.title}" not in briefing
        ]
        ctx.headlines = (briefing + rest)[:news_max_headlines]

        ctx.defensive_mode = (
            ctx.sentiment <= news_defensive_sell_sentiment
            or ctx.risk_score >= news_force_reduce_risk_score
        )
        # 방어모드는 매도 보조만 — 신규매수 allow_buy와 분리
        ctx.allow_buy = _compute_allow_buy(ctx.sentiment, ctx.risk_score)

        if ctx.sentiment >= 0.2:
            ctx.score_adjustment = news_score_boost_positive
        elif ctx.sentiment <= -0.2:
            ctx.score_adjustment = news_score_penalty_negative

        if headlines is None:
            self._cache = ctx
            self._cache_ts = time.time()
        return ctx

    def get_context(self) -> MarketNewsContext:
        return self.analyze()
