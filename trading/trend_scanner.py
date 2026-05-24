from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import quote

import requests

from config.config import (
    trend_dip_max_flu_rt,
    trend_dip_min_flu_rt,
    trend_fallback_theme_count,
    trend_min_pick_score,
    trend_min_theme_hits,
    trend_news_cache_minutes,
    trend_use_fallback_themes,
)
from config.trend_themes import TREND_THEMES, TrendTheme
from kiwoom.client import KiwoomClient
from trading.scoring import CandidateView

TREND_RSS_URL = (
    "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
)
TREND_NEWS_QUERY = (
    "AI semiconductor EV battery biotech defense nuclear robot "
    "global trend hot stock market 2025"
)


@dataclass
class TrendPick:
    theme_name: str
    theme_id: str
    code: str
    name: str
    flu_rt: float
    current_price: int
    trade_rank: int | None
    score: float
    reason: str
    in_rank: bool


@dataclass
class ActiveTrend:
    theme: TrendTheme
    hits: int
    sample_headline: str = ""


@dataclass
class TrendScanResult:
    active_trends: list[ActiveTrend] = field(default_factory=list)
    picks: list[TrendPick] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)
    error: str = ""
    used_fallback: bool = False

    def format_intro(self) -> str:
        lines = ["【글로벌 트렌드 스캔】"]
        if self.error:
            lines.append(f"참고: {self.error}")
        if self.used_fallback:
            lines.append("(뉴스 수집 제한 → 기본 핫테마 + 시장 데이터로 후보 산출)")

        if not self.active_trends:
            lines.append("현재 감지된 핫 트렌드가 없습니다.")
            return "\n".join(lines)

        lines.append("■ 핫 트렌드")
        for t in self.active_trends[:5]:
            hit_txt = f"언급 {t.hits}회" if t.hits else "기본 테마"
            lines.append(f"  · {t.theme.name} ({hit_txt})")
            if t.sample_headline:
                lines.append(f"    └ {t.sample_headline[:70]}")

        if not self.picks:
            lines.append("\n■ 저가 매수 후보: 조건 충족 종목 없음")
            lines.append(
                f"  (등락률 {trend_dip_min_flu_rt}% ~ {trend_dip_max_flu_rt}% 구간)"
            )
            return "\n".join(lines)

        lines.append("\n■ 트렌드 연관 · 저가 매수 후보 (눌림목)")
        for i, p in enumerate(self.picks[:8], 1):
            rank_txt = f"거래대금 {p.trade_rank}위" if p.trade_rank else "관심종목"
            lines.append(
                f"  {i}. [{p.theme_name}] {p.name}({p.code})\n"
                f"     {p.flu_rt:+.2f}% · {p.current_price:,}원 · {rank_txt}\n"
                f"     점수 {p.score:.1f} · {p.reason}"
            )
        return "\n".join(lines)


class TrendScanner:
    """뉴스 트렌드 + 테마 종목 + 거래대금 데이터로 저가 매수 후보 선별."""

    @staticmethod
    def _safe_int(value: object, default: int) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return default

    def __init__(self, client: KiwoomClient) -> None:
        self.client = client
        self._cache: TrendScanResult | None = None
        self._cache_ts: float = 0.0

    def _cache_valid(self) -> bool:
        if self._cache is None:
            return False
        return (time.time() - self._cache_ts) < trend_news_cache_minutes * 60

    @staticmethod
    def _clean(text: str) -> str:
        text = unescape(text or "")
        return re.sub(r"\s+", " ", text).strip()

    def _fetch_rss_titles(self, query: str, limit: int) -> list[str]:
        url = TREND_RSS_URL.format(q=quote(query))
        response = requests.get(
            url,
            timeout=12,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        titles: list[str] = []
        for item in root.iter("item"):
            el = item.find("title")
            if el is not None and el.text:
                titles.append(self._clean(el.text))
            if len(titles) >= limit:
                break
        return titles

    def _fetch_trend_headlines(self, limit: int = 40) -> list[str]:
        titles: list[str] = []
        queries = [
            TREND_NEWS_QUERY,
            "AI 반도체 HBM 엔비디아",
            "전기차 2차전지 배터리",
            "바이오 신약 헬스케어",
            "방산 우주 드론",
        ]
        for q in queries:
            try:
                titles.extend(self._fetch_rss_titles(q, limit=10))
            except requests.RequestException:
                continue

        try:
            from trading.news_analyzer import MarketNewsAnalyzer

            for item in MarketNewsAnalyzer().fetch_headlines():
                titles.append(item.title)
        except requests.RequestException:
            pass

        unique: list[str] = []
        seen: set[str] = set()
        for t in titles:
            if t not in seen:
                seen.add(t)
                unique.append(t)
            if len(unique) >= limit:
                break
        return unique

    def _detect_active_trends(self, headlines: list[str]) -> list[ActiveTrend]:
        corpus = " ".join(headlines).lower()
        active: list[ActiveTrend] = []

        for theme in TREND_THEMES:
            hits = 0
            sample = ""
            for kw in theme.keywords:
                if kw.lower() in corpus:
                    hits += corpus.count(kw.lower())
            if hits < trend_min_theme_hits:
                continue
            for headline in headlines:
                for kw in theme.keywords:
                    if kw.lower() in headline.lower():
                        sample = headline
                        break
                if sample:
                    break
            active.append(ActiveTrend(theme=theme, hits=hits, sample_headline=sample))

        active.sort(key=lambda x: x.hits, reverse=True)
        return active

    def _dip_score(self, flu_rt: float) -> float:
        """눌림목: 소폭 하락~보합일수록 고점 (단, 급락 제외)."""
        if flu_rt < trend_dip_min_flu_rt or flu_rt > trend_dip_max_flu_rt:
            return 0.0
        if -2.0 <= flu_rt <= 0.5:
            return 10.0
        if flu_rt < 0:
            return 8.0 - abs(flu_rt + 1.0)
        return 6.0 - abs(flu_rt - 0.5) * 2

    def _build_market_map(
        self,
        rank_items: list[dict],
    ) -> dict[str, CandidateView]:
        market: dict[str, CandidateView] = {}
        for item in rank_items:
            code = self.client.normalize_stock_code(item.get("stk_cd", ""))
            if not code:
                continue
            try:
                rank = int(item.get("now_rank", "999"))
            except ValueError:
                rank = 999
            market[code] = CandidateView(
                code=code,
                name=item.get("stk_nm", code),
                rank=rank,
                prev_rank=self._safe_int(item.get("pred_rank"), 999),
                flu_rt=self.client.parse_percent(item.get("flu_rt", "0")),
                current_price=self.client.parse_price(item.get("cur_prc", "0")),
                trade_value=item.get("trde_prica", ""),
                raw=item,
            )
        return market

    def _score_pick(
        self,
        theme: TrendTheme,
        theme_hits: int,
        code: str,
        name: str,
        flu_rt: float,
        price: int,
        trade_rank: int | None,
        in_rank: bool,
    ) -> tuple[float, str]:
        dip = self._dip_score(flu_rt)
        if dip <= 0:
            return 0.0, "등락률 구간 외"

        theme_score = min(theme_hits, 20) * 1.5
        liquidity = max(0, 11 - trade_rank) * 2 if trade_rank else 3
        rank_bonus = 5 if in_rank else 0
        total = theme_score + dip + liquidity + rank_bonus

        reason = f"트렌드 '{theme.name}' 연관, 눌림 {flu_rt:+.2f}%"
        if in_rank:
            reason += f", 거래대금 {trade_rank}위"
        return total, reason

    def scan(self, *, force_refresh: bool = False) -> TrendScanResult:
        if not force_refresh and self._cache_valid():
            return self._cache  # type: ignore[return-value]

        result = TrendScanResult()
        try:
            result.headlines = self._fetch_trend_headlines()
            result.active_trends = self._detect_active_trends(result.headlines)

            if not result.active_trends and trend_use_fallback_themes:
                result.used_fallback = True
                result.active_trends = [
                    ActiveTrend(
                        theme=theme,
                        hits=0,
                        sample_headline="기본 핫테마 (AI·반도체·2차전지 등)",
                    )
                    for theme in TREND_THEMES[:trend_fallback_theme_count]
                ]

            if not result.active_trends:
                self._cache = result
                self._cache_ts = time.time()
                return result

            rank_items = self.client.get_trade_value_rank(top_n=30)
            market = self._build_market_map(rank_items)
            picks: list[TrendPick] = []

            for active in result.active_trends:
                theme = active.theme
                for code, name in theme.stocks:
                    code = self.client.normalize_stock_code(code)
                    if code in market:
                        c = market[code]
                        flu_rt = c.flu_rt
                        price = c.current_price
                        rank = c.rank
                        in_rank = True
                        pick_name = c.name
                    else:
                        flu_rt = 0.0
                        price = 0
                        rank = None
                        in_rank = False
                        pick_name = name
                        for item in rank_items:
                            if self.client.normalize_stock_code(
                                item.get("stk_cd", "")
                            ) == code:
                                flu_rt = self.client.parse_percent(
                                    item.get("flu_rt", "0")
                                )
                                price = self.client.parse_price(
                                    item.get("cur_prc", "0")
                                )
                                try:
                                    rank = int(item.get("now_rank", "999"))
                                except ValueError:
                                    rank = None
                                in_rank = True
                                pick_name = item.get("stk_nm", name)
                                break

                    if not in_rank and price == 0:
                        continue

                    score, reason = self._score_pick(
                        theme,
                        active.hits,
                        code,
                        pick_name,
                        flu_rt,
                        price,
                        rank,
                        in_rank,
                    )
                    if score < trend_min_pick_score:
                        continue
                    picks.append(
                        TrendPick(
                            theme_name=theme.name,
                            theme_id=theme.theme_id,
                            code=code,
                            name=pick_name,
                            flu_rt=flu_rt,
                            current_price=price,
                            trade_rank=rank,
                            score=score,
                            reason=reason,
                            in_rank=in_rank,
                        )
                    )

            picks.sort(key=lambda p: p.score, reverse=True)
            seen: set[str] = set()
            unique: list[TrendPick] = []
            for p in picks:
                if p.code in seen:
                    continue
                seen.add(p.code)
                unique.append(p)
            result.picks = unique

        except requests.RequestException as exc:
            result.error = str(exc)

        self._cache = result
        self._cache_ts = time.time()
        return result
