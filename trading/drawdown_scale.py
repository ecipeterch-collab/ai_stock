"""벤치마크 MDD 기반 매수 금액 배수 (NexusTrade식 드로다운 스케일)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from config.config import (
    drawdown_benchmark_code,
    drawdown_lookback_days,
    drawdown_mdd_tier1_pct,
    drawdown_mdd_tier2_pct,
    drawdown_mdd_tier3_pct,
    drawdown_scale_channel_boost,
    drawdown_scale_enabled,
    drawdown_scale_max_mult,
    drawdown_scale_momentum_mult_cap,
    drawdown_scale_tier1_mult,
    drawdown_scale_tier2_mult,
    drawdown_scale_tier3_mult,
    drawdown_scale_tier4_mult,
)
from kiwoom.client import KiwoomAPIError, KiwoomClient


@dataclass
class DrawdownState:
    mdd_pct: float
    peak_price: int
    current_price: int
    multiplier: float
    tier: int
    benchmark_code: str
    message: str


def current_drawdown_pct(closes: list[float]) -> tuple[float, float, float]:
    """고점 대비 현재 낙폭(%). (mdd_pct, peak, current)"""
    if not closes:
        return 0.0, 0.0, 0.0
    peak = max(closes)
    current = closes[-1]
    if peak <= 0:
        return 0.0, peak, current
    mdd = max(0.0, (peak - current) / peak * 100.0)
    return mdd, peak, current


def multiplier_from_mdd(mdd_pct: float) -> tuple[float, int]:
    """낙폭 구간별 배수."""
    if mdd_pct < drawdown_mdd_tier1_pct:
        mult, tier = drawdown_scale_tier1_mult, 1
    elif mdd_pct < drawdown_mdd_tier2_pct:
        mult, tier = drawdown_scale_tier2_mult, 2
    elif mdd_pct < drawdown_mdd_tier3_pct:
        mult, tier = drawdown_scale_tier3_mult, 3
    else:
        mult, tier = drawdown_scale_tier4_mult, 4
    mult = min(float(drawdown_scale_max_mult), mult)
    return mult, tier


def scale_multiplier_for_channel(state: DrawdownState | None, channel: str) -> float:
    if not drawdown_scale_enabled or state is None:
        return 1.0
    mult = state.multiplier
    if channel == "momentum":
        return min(mult, float(drawdown_scale_momentum_mult_cap))
    if channel in drawdown_scale_channel_boost:
        return mult
    if channel == "addon":
        return min(mult, 1.5)
    return 1.0


class DrawdownScaleCalculator:
    """벤치마크 일봉으로 MDD·배수 계산 (일 1회 캐시)."""

    def __init__(self, client: KiwoomClient) -> None:
        self._client = client
        self._cache_date: date | None = None
        self._cache: DrawdownState | None = None

    def compute(self, *, force_refresh: bool = False) -> DrawdownState | None:
        if not drawdown_scale_enabled:
            return None

        today = date.today()
        if (
            not force_refresh
            and self._cache_date == today
            and self._cache is not None
        ):
            return self._cache

        code = drawdown_benchmark_code.strip()
        if not code:
            return None

        try:
            raw = self._client.get_daily_chart(code)
        except (KiwoomAPIError, OSError, ValueError) as exc:
            fallback = DrawdownState(
                mdd_pct=0.0,
                peak_price=0,
                current_price=0,
                multiplier=1.0,
                tier=1,
                benchmark_code=code,
                message=f"벤치마크 조회 실패 ({exc})",
            )
            self._cache_date = today
            self._cache = fallback
            return fallback

        closes: list[float] = []
        for row in reversed(raw):
            px = KiwoomClient.parse_price(str(row.get("cur_prc", "0")))
            if px > 0:
                closes.append(float(px))

        if len(closes) > drawdown_lookback_days:
            closes = closes[-drawdown_lookback_days :]

        mdd_pct, peak, current = current_drawdown_pct(closes)
        mult, tier = multiplier_from_mdd(mdd_pct)
        state = DrawdownState(
            mdd_pct=round(mdd_pct, 2),
            peak_price=int(peak),
            current_price=int(current),
            multiplier=mult,
            tier=tier,
            benchmark_code=code,
            message=(
                f"벤치 {code} MDD {mdd_pct:.1f}% "
                f"(T{tier} {mult:.2f}x)"
            ),
        )
        self._cache_date = today
        self._cache = state
        return state

    def compute_as_of(
        self,
        code: str,
        as_of: datetime,
        *,
        client: KiwoomClient | None = None,
    ) -> DrawdownState | None:
        """백테스트용: 특정 시점까지의 MDD 추정."""
        api = client or self._client
        try:
            raw = api.get_daily_chart(code)
        except (KiwoomAPIError, OSError, ValueError):
            return None

        closes: list[float] = []
        as_of_day = as_of.date()
        for row in reversed(raw):
            dt_str = str(row.get("dt", ""))
            if len(dt_str) >= 8:
                try:
                    bar_day = date(
                        int(dt_str[:4]),
                        int(dt_str[4:6]),
                        int(dt_str[6:8]),
                    )
                except ValueError:
                    bar_day = None
                if bar_day and bar_day > as_of_day:
                    continue
            px = KiwoomClient.parse_price(str(row.get("cur_prc", "0")))
            if px > 0:
                closes.append(float(px))

        lookback = drawdown_lookback_days
        if len(closes) > lookback:
            closes = closes[-lookback:]

        mdd_pct, peak, current = current_drawdown_pct(closes)
        mult, tier = multiplier_from_mdd(mdd_pct)
        return DrawdownState(
            mdd_pct=round(mdd_pct, 2),
            peak_price=int(peak),
            current_price=int(current),
            multiplier=mult,
            tier=tier,
            benchmark_code=code,
            message=f"MDD {mdd_pct:.1f}% T{tier}",
        )
