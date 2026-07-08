"""시장 국면 감지 및 채널별 매수 허용."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.config import (
    regime_bear_channels,
    regime_bear_max_bullish_ratio,
    regime_bull_channels,
    regime_bull_min_bullish_ratio,
    regime_enabled,
    regime_high_vol_channels,
    regime_high_vol_min_avg_abs_flu_rt,
    regime_high_vol_min_news_risk,
    regime_scan_top,
    regime_sideways_channels,
)
from trading.scoring import CandidateView, market_bullish_stats


class MarketRegime(str, Enum):
    BULL = "bull"
    SIDEWAYS = "sideways"
    BEAR = "bear"
    HIGH_VOL = "high_vol"


REGIME_LABELS: dict[str, str] = {
    MarketRegime.BULL.value: "강세",
    MarketRegime.SIDEWAYS.value: "횡보",
    MarketRegime.BEAR.value: "약세",
    MarketRegime.HIGH_VOL.value: "고변동",
}

CHANNEL_LABELS: dict[str, str] = {
    "momentum": "모멘텀",
    "pullback": "눌림",
    "crash": "급락",
    "trend": "트렌드",
    "addon": "추가매수",
}

_REGIME_CHANNELS: dict[MarketRegime, tuple[str, ...]] = {
    MarketRegime.BULL: regime_bull_channels,
    MarketRegime.SIDEWAYS: regime_sideways_channels,
    MarketRegime.BEAR: regime_bear_channels,
    MarketRegime.HIGH_VOL: regime_high_vol_channels,
}


@dataclass
class RegimeSnapshot:
    regime: MarketRegime
    label: str
    bullish_count: int
    bullish_total: int
    bullish_ratio: float
    avg_abs_flu_rt: float
    avg_flu_rt: float
    message: str


@dataclass
class MarketContext:
    regime: RegimeSnapshot | None = None
    drawdown: object | None = None  # DrawdownState | None
    candidates: list[CandidateView] | None = None


def detect_regime(
    candidates: list[CandidateView],
    *,
    news_risk_score: float | None = None,
) -> RegimeSnapshot:
    """거래대금 상위 종목 분포로 시장 국면 추정."""
    bullish, total, ratio, bull_msg = market_bullish_stats(
        candidates, top_n=regime_scan_top
    )
    top = candidates[:regime_scan_top]
    if top:
        avg_abs = sum(abs(c.flu_rt) for c in top) / len(top)
        avg_flu = sum(c.flu_rt for c in top) / len(top)
    else:
        avg_abs = 0.0
        avg_flu = 0.0

    high_vol_signal = avg_abs >= regime_high_vol_min_avg_abs_flu_rt
    if news_risk_score is not None and news_risk_score >= regime_high_vol_min_news_risk:
        high_vol_signal = True

    if total > 0 and ratio >= regime_bull_min_bullish_ratio and not high_vol_signal:
        regime = MarketRegime.BULL
        msg = f"강세 ({bull_msg}, 평균등락 {avg_flu:+.2f}%)"
    elif total > 0 and ratio <= regime_bear_max_bullish_ratio:
        regime = MarketRegime.BEAR
        msg = f"약세 ({bull_msg}, 평균등락 {avg_flu:+.2f}%)"
    elif high_vol_signal:
        regime = MarketRegime.HIGH_VOL
        msg = f"고변동 ({bull_msg}, |등락|평균 {avg_abs:.2f}%)"
    else:
        regime = MarketRegime.SIDEWAYS
        msg = f"횡보 ({bull_msg}, 평균등락 {avg_flu:+.2f}%)"

    return RegimeSnapshot(
        regime=regime,
        label=REGIME_LABELS[regime.value],
        bullish_count=bullish,
        bullish_total=total,
        bullish_ratio=ratio,
        avg_abs_flu_rt=avg_abs,
        avg_flu_rt=avg_flu,
        message=msg,
    )


def is_channel_allowed(snapshot: RegimeSnapshot | None, channel: str) -> bool:
    """국면이 없거나 비활성이면 모든 채널 허용."""
    if not regime_enabled or snapshot is None:
        return True
    allowed = _REGIME_CHANNELS.get(snapshot.regime, ())
    return channel in allowed


def format_buy_meta(
    snapshot: RegimeSnapshot | None,
    *,
    scale_mult: float = 1.0,
) -> str:
    """저널 reason 접두사 (국면·스케일)."""
    parts: list[str] = []
    if regime_enabled and snapshot is not None:
        parts.append(f"국면:{snapshot.label}")
    if scale_mult > 1.0:
        parts.append(f"스케일:{scale_mult:.2f}x")
    return " · ".join(parts)


def parse_regime_from_reason(reason: str) -> str:
    """저널 reason에서 국면 키 추출 (bull/bear/...)."""
    if not reason:
        return "unknown"
    for key, label in REGIME_LABELS.items():
        if f"국면:{label}" in reason:
            return key
    return "unknown"


def parse_scale_from_reason(reason: str) -> float:
    if not reason or "스케일:" not in reason:
        return 1.0
    for part in reason.split(" · "):
        part = part.strip()
        if part.startswith("스케일:") and part.endswith("x"):
            try:
                return float(part[4:-1])
            except ValueError:
                return 1.0
    return 1.0
