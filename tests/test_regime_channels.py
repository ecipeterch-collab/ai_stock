"""국면별 매수 채널: 모멘텀 집중, 횡보 눌림/트렌드 공회전 차단."""

from __future__ import annotations

from trading.market_regime import MarketRegime, RegimeSnapshot, is_channel_allowed


def _snap(regime: MarketRegime) -> RegimeSnapshot:
    return RegimeSnapshot(
        regime=regime,
        label=regime.value,
        bullish_count=0,
        bullish_total=0,
        bullish_ratio=0.0,
        avg_abs_flu_rt=0.0,
        avg_flu_rt=0.0,
        message="",
    )


def test_bull_allows_momentum_not_pullback_or_trend(monkeypatch) -> None:
    import trading.market_regime as mr

    monkeypatch.setattr(mr, "regime_enabled", True)
    monkeypatch.setitem(
        mr._REGIME_CHANNELS,
        MarketRegime.BULL,
        ("momentum", "addon"),
    )
    snap = _snap(MarketRegime.BULL)
    assert is_channel_allowed(snap, "momentum")
    assert is_channel_allowed(snap, "addon")
    assert not is_channel_allowed(snap, "pullback")
    assert not is_channel_allowed(snap, "trend")


def test_sideways_blocks_new_entries_allows_addon(monkeypatch) -> None:
    import trading.market_regime as mr

    monkeypatch.setattr(mr, "regime_enabled", True)
    monkeypatch.setitem(mr._REGIME_CHANNELS, MarketRegime.SIDEWAYS, ("addon",))
    snap = _snap(MarketRegime.SIDEWAYS)
    assert not is_channel_allowed(snap, "pullback")
    assert not is_channel_allowed(snap, "trend")
    assert not is_channel_allowed(snap, "momentum")
    assert is_channel_allowed(snap, "addon")


def test_high_vol_allows_momentum_and_crash_not_pullback(monkeypatch) -> None:
    import trading.market_regime as mr

    monkeypatch.setattr(mr, "regime_enabled", True)
    monkeypatch.setitem(
        mr._REGIME_CHANNELS,
        MarketRegime.HIGH_VOL,
        ("momentum", "crash", "addon"),
    )
    snap = _snap(MarketRegime.HIGH_VOL)
    assert is_channel_allowed(snap, "momentum")
    assert is_channel_allowed(snap, "crash")
    assert not is_channel_allowed(snap, "pullback")
    assert not is_channel_allowed(snap, "trend")


def test_live_config_matches_momentum_focus_policy() -> None:
    """실제 config가 모멘텀 집중 정책과 일치하는지 확인."""
    from config import config as cfg

    assert "momentum" in cfg.regime_bull_channels
    assert "pullback" not in cfg.regime_bull_channels
    assert "trend" not in cfg.regime_bull_channels
    assert "pullback" not in cfg.regime_sideways_channels
    assert "trend" not in cfg.regime_sideways_channels
    assert "pullback" not in cfg.regime_high_vol_channels
    assert "trend" not in cfg.regime_high_vol_channels
    assert "momentum" in cfg.regime_high_vol_channels
    assert cfg.trend_auto_buy_enabled is False
    assert cfg.strategy_momentum_buy_enabled is True
    assert cfg.chart_filter_enabled is True
