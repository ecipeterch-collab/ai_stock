"""분봉·일봉 기반 매수 차트 필터 (VWAP, MA, RSI, 거래량)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby
from config.config import (
    chart_cache_daily_ttl_sec,
    chart_cache_minute_ttl_sec,
    chart_eval_max_candidates,
    chart_filter_enabled,
    chart_ma_fast,
    chart_ma_slow,
    chart_min_score,
    chart_minute_interval,
    chart_rsi_max,
    chart_rsi_min,
    chart_score_weight,
    chart_vwap_max_above_pct,
    chart_vwap_tolerance_pct,
    chart_volume_breakout_ratio,
    chart_volume_pullback_max_ratio,
)
from kiwoom.client import KiwoomClient
from trading.scoring import CandidateView, is_momentum_candidate


@dataclass
class Candle:
    ts: str
    open: int
    high: int
    low: int
    close: int
    volume: int


@dataclass
class ChartSignalResult:
    passed: bool
    score: float
    max_score: float = 15.0
    mode: str = "pullback"
    reasons: list[str] = field(default_factory=list)
    reject_reason: str = ""


def _parse_candle_daily(raw: dict) -> Candle | None:
    close = KiwoomClient.parse_price(str(raw.get("cur_prc", "0")))
    if close <= 0:
        return None
    return Candle(
        ts=str(raw.get("dt", "")),
        open=KiwoomClient.parse_price(str(raw.get("open_pric", "0"))),
        high=KiwoomClient.parse_price(str(raw.get("high_pric", "0"))),
        low=KiwoomClient.parse_price(str(raw.get("low_pric", "0"))),
        close=close,
        volume=KiwoomClient.parse_price(str(raw.get("trde_qty", "0"))),
    )


def _parse_candle_minute(raw: dict) -> Candle | None:
    close = KiwoomClient.parse_price(str(raw.get("cur_prc", "0")))
    if close <= 0:
        return None
    return Candle(
        ts=str(raw.get("cntr_tm", "")),
        open=KiwoomClient.parse_price(str(raw.get("open_pric", "0"))),
        high=KiwoomClient.parse_price(str(raw.get("high_pric", "0"))),
        low=KiwoomClient.parse_price(str(raw.get("low_pric", "0"))),
        close=close,
        volume=KiwoomClient.parse_price(str(raw.get("trde_qty", "0"))),
    )


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    window = values[-period:]
    return sum(window) / period


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def vwap(candles: list[Candle]) -> float | None:
    if not candles:
        return None
    num = 0.0
    den = 0.0
    for c in candles:
        typical = (c.high + c.low + c.close) / 3.0
        num += typical * c.volume
        den += c.volume
    if den <= 0:
        return None
    return num / den


def _filter_minute_as_of(minute_raw: list[dict], as_of: datetime | None) -> list[Candle]:
    candles: list[Candle] = []
    for raw in minute_raw:
        c = _parse_candle_minute(raw)
        if c is None or len(c.ts) < 8:
            continue
        if as_of is not None:
            try:
                bar_dt = datetime.strptime(c.ts[:14], "%Y%m%d%H%M%S")
            except ValueError:
                continue
            if bar_dt.date() != as_of.date() or bar_dt > as_of:
                continue
        candles.append(c)
    candles.sort(key=lambda x: x.ts)
    return candles


def _filter_daily_as_of(daily_raw: list[dict], as_of: datetime | None) -> list[Candle]:
    candles: list[Candle] = []
    cutoff = as_of.strftime("%Y%m%d") if as_of else "99999999"
    for raw in daily_raw:
        c = _parse_candle_daily(raw)
        if c is None or not c.ts:
            continue
        if as_of is not None and c.ts > cutoff:
            continue
        candles.append(c)
    candles.sort(key=lambda x: x.ts)
    return candles


def evaluate_daily_trend_only(
    daily_candles: list[Candle],
    current_price: int,
) -> ChartSignalResult:
    """분봉 없을 때 일봉 추세만 검사 (백테스트·장초반 fallback)."""
    reasons: list[str] = []
    score = 0.0
    daily_closes = [float(c.close) for c in daily_candles if c.close > 0]
    if len(daily_closes) < chart_ma_slow:
        return ChartSignalResult(
            False, 0, mode="pullback", reject_reason="일봉 데이터 부족"
        )
    ma_slow = sma(daily_closes, chart_ma_slow)
    ma_fast = sma(daily_closes, chart_ma_fast)
    last_close = daily_closes[-1]
    if ma_slow and last_close > ma_slow:
        score += 5
        reasons.append(f"일봉>{chart_ma_slow}MA")
    else:
        return ChartSignalResult(
            False, score, mode="pullback", reject_reason="일봉 추세 약함"
        )
    if ma_fast and ma_slow and ma_fast > ma_slow:
        score += 3
        reasons.append(f"{chart_ma_fast}MA>{chart_ma_slow}MA")
    min_daily = max(5.0, chart_min_score - 3)
    passed = score >= min_daily
    return ChartSignalResult(
        passed=passed,
        score=score,
        max_score=8.0,
        mode="pullback",
        reasons=reasons,
        reject_reason="" if passed else f"일봉점수 {score:.0f}<{min_daily:.0f}",
    )


def evaluate_chart_signals(
    *,
    daily_candles: list[Candle],
    minute_candles: list[Candle],
    current_price: int,
    mode: str = "pullback",
) -> ChartSignalResult:
    """차트 신호 평가. mode: pullback | momentum."""
    reasons: list[str] = []
    score = 0.0
    max_score = 15.0

    if current_price <= 0:
        return ChartSignalResult(False, 0, mode=mode, reject_reason="현재가 없음")

    daily_closes = [float(c.close) for c in daily_candles if c.close > 0]
    if len(daily_closes) < chart_ma_slow:
        return ChartSignalResult(
            False, 0, mode=mode, reject_reason=f"일봉 {len(daily_closes)}개 부족"
        )

    ma_slow = sma(daily_closes, chart_ma_slow)
    ma_fast = sma(daily_closes, chart_ma_fast)
    last_close = daily_closes[-1]

    if ma_slow and last_close > ma_slow:
        score += 3
        reasons.append(f"일봉>{chart_ma_slow}MA")
    else:
        return ChartSignalResult(
            False,
            score,
            mode=mode,
            reasons=reasons,
            reject_reason=f"일봉 추세 약함 (종가≤{chart_ma_slow}MA)",
        )

    if ma_fast and ma_slow and ma_fast > ma_slow:
        score += 2
        reasons.append(f"{chart_ma_fast}MA>{chart_ma_slow}MA")

    if len(minute_candles) < 10:
        return ChartSignalResult(
            False,
            score,
            mode=mode,
            reasons=reasons,
            reject_reason=f"분봉 {len(minute_candles)}개 부족",
        )

    min_closes = [float(c.close) for c in minute_candles]
    min_vwap = vwap(minute_candles)
    min_rsi = rsi(min_closes)

    if min_rsi is not None and chart_rsi_min <= min_rsi <= chart_rsi_max:
        score += 2
        reasons.append(f"RSI {min_rsi:.0f}")
    elif min_rsi is not None:
        return ChartSignalResult(
            False,
            score,
            mode=mode,
            reasons=reasons,
            reject_reason=f"RSI {min_rsi:.0f} 극단({chart_rsi_min}~{chart_rsi_max})",
        )

    vwap_near = False
    if min_vwap:
        diff_pct = (current_price - min_vwap) / min_vwap * 100.0
        tol = chart_vwap_tolerance_pct
        max_above = float(chart_vwap_max_above_pct)
        if mode == "momentum":
            if current_price >= min_vwap * (1 - tol / 100.0):
                score += 3
                reasons.append(f"VWAP {diff_pct:+.2f}%")
            else:
                return ChartSignalResult(
                    False,
                    score,
                    mode=mode,
                    reasons=reasons,
                    reject_reason=f"VWAP 하회 ({diff_pct:+.2f}%)",
                )
        else:
            if diff_pct > max_above:
                return ChartSignalResult(
                    False,
                    score,
                    mode=mode,
                    reasons=reasons,
                    reject_reason=(
                        f"VWAP 과열 ({diff_pct:+.2f}% > +{max_above:.1f}%)"
                    ),
                )
            if abs(diff_pct) <= tol * 2:
                score += 3
                vwap_near = True
                reasons.append(f"VWAP근접 {diff_pct:+.2f}%")
            elif current_price >= min_vwap * (1 - tol / 100.0):
                score += 1
                reasons.append(f"VWAP지지 {diff_pct:+.2f}%")
            else:
                return ChartSignalResult(
                    False,
                    score,
                    mode=mode,
                    reasons=reasons,
                    reject_reason=f"VWAP 이탈 ({diff_pct:+.2f}%)",
                )

    recent = minute_candles[-5:]
    vols = [c.volume for c in recent if c.volume > 0]
    cur_vol = minute_candles[-1].volume
    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1) if len(vols) > 1 else 0

    if mode == "momentum":
        if avg_vol > 0 and cur_vol >= avg_vol * chart_volume_breakout_ratio:
            score += 3
            reasons.append("거래량돌파")
        else:
            return ChartSignalResult(
                False,
                score,
                mode=mode,
                reasons=reasons,
                reject_reason="거래량 돌파 미달",
            )
        last3 = minute_candles[-3:]
        greens = sum(1 for c in last3 if c.close >= c.open)
        higher_high = last3[-1].high >= max(c.high for c in last3[:-1])
        if greens >= 2 or higher_high:
            score += 2
            reasons.append("단기상승")
        else:
            return ChartSignalResult(
                False,
                score,
                mode=mode,
                reasons=reasons,
                reject_reason="단기 모멘텀 미확인",
            )
    else:
        pullback_vols = [c.volume for c in minute_candles[-4:-1]]
        if pullback_vols and avg_vol > 0:
            if max(pullback_vols) <= avg_vol * chart_volume_pullback_max_ratio:
                score += 2
                reasons.append("눌림거래량감소")
        if vwap_near and minute_candles[-1].close >= minute_candles[-1].open:
            score += 2
            reasons.append("반등양봉")
        elif vwap_near and minute_candles[-1].close >= minute_candles[-2].close:
            score += 1
            reasons.append("반등시도")

    passed = score >= chart_min_score
    return ChartSignalResult(
        passed=passed,
        score=score,
        max_score=max_score,
        mode=mode,
        reasons=reasons,
        reject_reason="" if passed else f"차트점수 {score:.0f}<{chart_min_score:.0f}",
    )


def _daily_prefilter_reject(
    daily_candles: list[Candle],
    *,
    mode: str,
) -> ChartSignalResult | None:
    """일봉 추세 미달 시 분봉 API 없이 즉시 거절."""
    daily_closes = [float(c.close) for c in daily_candles if c.close > 0]
    if len(daily_closes) < chart_ma_slow:
        return ChartSignalResult(
            False,
            0,
            mode=mode,
            reject_reason=f"일봉 {len(daily_closes)}개 부족",
        )
    ma_slow = sma(daily_closes, chart_ma_slow)
    last_close = daily_closes[-1]
    if not ma_slow or last_close <= ma_slow:
        return ChartSignalResult(
            False,
            0,
            mode=mode,
            reject_reason=f"일봉 추세 약함 (종가≤{chart_ma_slow}MA)",
        )
    return None


class ChartSignalAnalyzer:
    """Kiwoom 차트 조회 + 매수 후보 필터 (TTL 캐시·일봉 선필터)."""

    def __init__(self, client: KiwoomClient) -> None:
        self.client = client
        self._daily_cache: dict[str, tuple[list[Candle], float]] = {}
        self._minute_cache: dict[str, tuple[list[Candle], float]] = {}

    @staticmethod
    def _daily_cache_key(code: str, as_of: datetime | None) -> str:
        day = as_of.strftime("%Y%m%d") if as_of else datetime.now().strftime("%Y%m%d")
        return f"{code}:d:{day}"

    @staticmethod
    def _minute_cache_key(code: str, as_of: datetime | None) -> str:
        if as_of is not None:
            bucket = as_of.strftime("%Y%m%d%H%M")
        else:
            now = datetime.now()
            interval = max(1, int(chart_minute_interval))
            bucket_min = (now.hour * 60 + now.minute) // interval * interval
            h, m = divmod(bucket_min, 60)
            bucket = f"{now.strftime('%Y%m%d')}{h:02d}{m:02d}"
        return f"{code}:m:{bucket}"

    @staticmethod
    def _cache_fresh(stored_at: float, ttl_sec: float) -> bool:
        return (time.monotonic() - stored_at) < ttl_sec

    def _get_cached(
        self,
        store: dict[str, tuple[list[Candle], float]],
        key: str,
        ttl_sec: float,
    ) -> list[Candle] | None:
        entry = store.get(key)
        if entry is None:
            return None
        candles, stored_at = entry
        if not self._cache_fresh(stored_at, ttl_sec):
            return None
        return candles

    def _set_cached(
        self,
        store: dict[str, tuple[list[Candle], float]],
        key: str,
        candles: list[Candle],
    ) -> None:
        store[key] = (candles, time.monotonic())

    def _load_daily(self, code: str, as_of: datetime | None = None) -> list[Candle]:
        key = self._daily_cache_key(code, as_of)
        cached = self._get_cached(self._daily_cache, key, chart_cache_daily_ttl_sec)
        if cached is not None:
            return cached
        raw = self.client.get_daily_chart(
            code,
            base_dt=as_of.strftime("%Y%m%d") if as_of else None,
        )
        candles = _filter_daily_as_of(raw, as_of)
        self._set_cached(self._daily_cache, key, candles)
        return candles

    def _load_minute(self, code: str, as_of: datetime | None = None) -> list[Candle]:
        key = self._minute_cache_key(code, as_of)
        cached = self._get_cached(self._minute_cache, key, chart_cache_minute_ttl_sec)
        if cached is not None:
            return cached
        raw = self.client.get_minute_chart(
            code,
            tic_scope=str(chart_minute_interval),
            base_dt=as_of.strftime("%Y%m%d") if as_of else None,
        )
        candles = _filter_minute_as_of(raw, as_of)
        self._set_cached(self._minute_cache, key, candles)
        return candles

    def prefetch_daily(
        self,
        codes: list[str],
        *,
        as_of: datetime | None = None,
    ) -> None:
        """후보 종목 일봉을 먼저 적재 (캐시 히트 시 API 생략)."""
        seen: set[str] = set()
        for code in codes:
            norm = KiwoomClient.normalize_stock_code(code)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            self._load_daily(norm, as_of)

    def evaluate(
        self,
        *,
        code: str,
        current_price: int,
        mode: str = "pullback",
        as_of: datetime | None = None,
    ) -> ChartSignalResult:
        if not chart_filter_enabled:
            return ChartSignalResult(True, chart_min_score, mode=mode, reasons=["차트필터OFF"])
        daily = self._load_daily(code, as_of)
        pre = _daily_prefilter_reject(daily, mode=mode)
        if pre is not None:
            return pre
        minute = self._load_minute(code, as_of)
        result = evaluate_chart_signals(
            daily_candles=daily,
            minute_candles=minute,
            current_price=current_price,
            mode=mode,
        )
        if (
            not result.passed
            and as_of is not None
            and "분봉" in result.reject_reason
        ):
            return evaluate_daily_trend_only(daily, current_price)
        return result

    def evaluate_candidate(
        self,
        candidate: CandidateView,
        *,
        momentum: bool = False,
        as_of: datetime | None = None,
    ) -> ChartSignalResult:
        mode = "momentum" if momentum else "pullback"
        if momentum or is_momentum_candidate(candidate):
            mode = "momentum"
        return self.evaluate(
            code=candidate.code,
            current_price=candidate.current_price,
            mode=mode,
            as_of=as_of,
        )

    def chart_score_bonus(self, result: ChartSignalResult) -> float:
        if not result.passed:
            return 0.0
        return min(result.score, result.max_score) * chart_score_weight

    def prune_stale_cache(self) -> None:
        """만료된 캐시 항목 제거."""
        now = time.monotonic()

        def _prune(
            store: dict[str, tuple[list[Candle], float]],
            ttl: float,
        ) -> None:
            stale = [k for k, (_, ts) in store.items() if (now - ts) >= ttl]
            for k in stale:
                del store[k]

        _prune(self._daily_cache, chart_cache_daily_ttl_sec)
        _prune(self._minute_cache, chart_cache_minute_ttl_sec)

    def cache_stats(self) -> dict[str, int]:
        return {
            "daily": len(self._daily_cache),
            "minute": len(self._minute_cache),
        }

    def prefetch_for_buy_events(
        self,
        events: list[tuple[str, datetime]],
    ) -> None:
        """거래일별 일봉 선적재 (백테스트·저널 재분석용)."""
        if not events:
            return
        sorted_events = sorted(events, key=lambda item: item[1])
        for _, group in groupby(sorted_events, key=lambda item: item[1].strftime("%Y%m%d")):
            batch = list(group)
            self.prefetch_daily(
                [code for code, _ in batch],
                as_of=batch[0][1],
            )

    def clear_cache(self) -> None:
        """전체 캐시 삭제 (백테스트·수동 리셋용)."""
        self._daily_cache.clear()
        self._minute_cache.clear()
