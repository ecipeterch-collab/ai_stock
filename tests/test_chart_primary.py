"""차트 우선 매수 유니버스·채널 플래그·참고 메모."""

from __future__ import annotations

from trading.chart_primary import (
    advisory_market_note,
    build_buy_advisory_notes,
    chart_modes_for_candidate,
    chart_primary_channel_flags,
    filter_chart_primary_universe,
)
from trading.market_regime import MarketRegime, RegimeSnapshot
from trading.scoring import CandidateView


def _cand(
    code: str,
    name: str,
    *,
    flu: float = 1.0,
    rank: int = 1,
    prev: int = 5,
) -> CandidateView:
    return CandidateView(
        code=code,
        name=name,
        rank=rank,
        prev_rank=prev,
        flu_rt=flu,
        current_price=50000,
        trade_value="1000000",
        raw={},
    )


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


def test_universe_keeps_moderate_flu_non_etf() -> None:
    cands = [
        _cand("005930", "삼성전자", flu=2.5),
        _cand("069500", "KODEX 200", flu=0.1),
    ]
    kept, rejected = filter_chart_primary_universe(cands, set())
    assert [c.code for c in kept] == ["005930"]
    assert any("ETF" in r for r in rejected)


def test_universe_rejects_chase_flu_above_cap() -> None:
    cands = [
        _cand("001820", "삼화콘덴서", flu=23.3),
        _cand("002990", "금호건설", flu=3.22),
    ]
    kept, rejected = filter_chart_primary_universe(cands, set())
    assert [c.code for c in kept] == ["002990"]
    assert any("등락" in r and "삼화" in r for r in rejected)


def test_universe_keeps_flu_at_cap() -> None:
    cands = [_cand("005930", "삼성전자", flu=8.0)]
    kept, _rejected = filter_chart_primary_universe(cands, set())
    assert [c.code for c in kept] == ["005930"]


def test_universe_excludes_held() -> None:
    cands = [_cand("005930", "삼성전자")]
    kept, rejected = filter_chart_primary_universe(cands, {"005930"})
    assert kept == []
    assert any("보유" in r for r in rejected)


def test_advisory_notes_do_not_imply_hard_block() -> None:
    note = build_buy_advisory_notes(
        candidate=_cand("005930", "삼성전자", flu=3.0),
        market_msg="약세 · 2/15종목 상승",
        regime_msg="횡보 - 일반매수 OFF",
        news_msg="심리 -0.50",
        strategy_score=12.0,
        strategy_min_score=19.0,
    )
    assert "참고" in note
    assert "미달(참고)" in note
    assert "중단" not in note


def test_advisory_market_note_includes_breadth() -> None:
    cands = [
        _cand(f"{i:06d}", f"종목{i}", flu=1.0 if i < 10 else -1.0) for i in range(15)
    ]
    note = advisory_market_note(cands)
    assert "종목" in note


def test_high_vol_afternoon_disables_chart_primary_channels(monkeypatch) -> None:
    import trading.chart_primary as cp
    import trading.market_regime as mr

    monkeypatch.setattr(cp, "regime_enabled", True)
    monkeypatch.setattr(mr, "regime_enabled", True)
    allow_m, allow_p = chart_primary_channel_flags(
        _snap(MarketRegime.HIGH_VOL),
        in_morning=False,
    )
    assert allow_m is False
    assert allow_p is False


def test_high_vol_morning_allows_momentum_only(monkeypatch) -> None:
    import trading.chart_primary as cp
    import trading.market_regime as mr

    monkeypatch.setattr(cp, "regime_enabled", True)
    monkeypatch.setattr(mr, "regime_enabled", True)
    allow_m, allow_p = chart_primary_channel_flags(
        _snap(MarketRegime.HIGH_VOL),
        in_morning=True,
    )
    assert allow_m is True
    assert allow_p is False


def test_bull_afternoon_allows_pullback_not_momentum(monkeypatch) -> None:
    import trading.chart_primary as cp
    import trading.market_regime as mr

    monkeypatch.setattr(cp, "regime_enabled", True)
    monkeypatch.setattr(mr, "regime_enabled", True)
    monkeypatch.setitem(
        mr._REGIME_CHANNELS,
        MarketRegime.BULL,
        ("momentum", "pullback", "addon"),
    )
    allow_m, allow_p = chart_primary_channel_flags(
        _snap(MarketRegime.BULL),
        in_morning=False,
    )
    assert allow_m is False
    assert allow_p is True


def test_high_vol_morning_skips_momentum_chart_when_flu_not_in_band() -> None:
    """고변동 아침이어도 등락 +0.22%면 모멘텀 차트를 쓰지 않는다 (8/18 현대차)."""
    cand = _cand("005380", "현대차", flu=0.22, rank=1, prev=20)
    modes = chart_modes_for_candidate(
        cand, allow_momentum=True, allow_pullback=False
    )
    assert modes == []


def test_high_vol_morning_uses_momentum_chart_in_flu_band() -> None:
    cand = _cand("005930", "삼성전자", flu=3.0, rank=1, prev=20)
    modes = chart_modes_for_candidate(
        cand, allow_momentum=True, allow_pullback=False
    )
    assert modes == [True]


def test_pullback_mode_still_used_when_flu_outside_momentum_band() -> None:
    cand = _cand("006400", "삼성SDI", flu=-1.36, rank=2, prev=20)
    modes = chart_modes_for_candidate(
        cand, allow_momentum=True, allow_pullback=True
    )
    assert modes == [False]


def test_chart_primary_buy_skips_when_news_sentiment_blocked() -> None:
    from unittest.mock import MagicMock

    from trading.chart_signals import ChartSignalResult
    from trading.news_analyzer import MarketNewsContext
    from trading.strategy import AutoRunResult, AutoTradingStrategy

    cand = _cand("005930", "삼성전자", flu=3.0, rank=1, prev=20)
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.chart = MagicMock()
    strat.chart.prune_stale_cache = MagicMock()
    strat._cycle_ctx = None
    strat._heartbeat = lambda action, target="": action
    strat._in_morning_buy_window = lambda: True
    strat._execute_buy = MagicMock()
    strat._pick_chart_primary = MagicMock(
        return_value=(
            cand,
            25.0,
            ChartSignalResult(
                True, 15.0, mode="momentum", reasons=["거래량돌파"]
            ),
            True,
        )
    )
    news = MarketNewsContext(
        sentiment=-0.88,
        risk_score=0.52,
        allow_buy=True,
        score_adjustment=-4.0,
    )
    result = AutoRunResult()
    strat._run_chart_primary_buy(
        result,
        [],
        news,
        candidates=[cand],
        held_codes=set(),
        snap=None,
    )
    strat._execute_buy.assert_not_called()
    assert any("중단" in msg or "심리" in msg for msg in result.report)
