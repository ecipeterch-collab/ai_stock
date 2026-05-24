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
    news_block_buy_risk_score,
    news_block_buy_sentiment,
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
]


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

        lines = [
            "【시장·뉴스 브리핑】",
            f"분위기: {mood} ({self.sentiment:+.2f}) · 리스크: {risk} ({self.risk_score:.2f})",
            f"신규매수: {'가능' if self.allow_buy else '중단'} · "
            f"방어모드: {'ON' if self.defensive_mode else 'OFF'}",
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

        if self._cache_valid():
            return self._cache  # type: ignore[return-value]

        ctx = MarketNewsContext(
            fetched_at=datetime.now().isoformat(timespec="seconds"),
        )

        try:
            items = headlines if headlines is not None else self.fetch_headlines()
        except requests.RequestException as exc:
            ctx.error = f"뉴스 수집 실패 ({exc})"
            ctx.allow_buy = True  # 뉴스 실패 시 기술적 매매만 진행
            self._cache = ctx
            self._cache_ts = time.time()
            return ctx

        if not items:
            ctx.error = "수집된 헤드라인 없음"
            self._cache = ctx
            self._cache_ts = time.time()
            return ctx

        pos_hits: list[str] = []
        neg_hits: list[str] = []
        risk_hits: list[str] = []

        for item in items:
            text = f"{item.title} {item.category}"
            pos_hits.extend(self._count_keyword_hits(text, POSITIVE_KEYWORDS))
            neg_hits.extend(self._count_keyword_hits(text, NEGATIVE_KEYWORDS))
            risk_hits.extend(self._count_keyword_hits(text, RISK_KEYWORDS))

        ctx.positive_hits = len(pos_hits)
        ctx.negative_hits = len(neg_hits)
        ctx.risk_hits = len(risk_hits)

        total_signal = max(ctx.positive_hits + ctx.negative_hits + ctx.risk_hits, 1)
        ctx.sentiment = (ctx.positive_hits - ctx.negative_hits) / total_signal
        ctx.sentiment = max(-1.0, min(1.0, ctx.sentiment))
        ctx.risk_score = min(1.0, ctx.risk_hits / max(len(items), 1) * 2.5)

        theme_counter: dict[str, int] = {}
        for kw in neg_hits + risk_hits + pos_hits:
            theme_counter[kw] = theme_counter.get(kw, 0) + 1
        ctx.themes = [
            k for k, _ in sorted(theme_counter.items(), key=lambda x: -x[1])[:8]
        ]

        ctx.headlines = [f"[{i.category}] {i.title}" for i in items[:news_max_headlines]]

        ctx.allow_buy = (
            ctx.sentiment >= news_block_buy_sentiment
            and ctx.risk_score < news_block_buy_risk_score
        )
        ctx.defensive_mode = (
            ctx.sentiment <= news_defensive_sell_sentiment
            or ctx.risk_score >= news_force_reduce_risk_score
        )

        if ctx.sentiment >= 0.2:
            ctx.score_adjustment = news_score_boost_positive
        elif ctx.sentiment <= -0.2:
            ctx.score_adjustment = news_score_penalty_negative

        self._cache = ctx
        self._cache_ts = time.time()
        return ctx

    def get_context(self) -> MarketNewsContext:
        return self.analyze()
