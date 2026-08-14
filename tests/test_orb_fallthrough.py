"""ORB 미통과 시 매수 전체 중단 대신 fall-through."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from trading.scoring import CandidateView
from trading.strategy import AutoRunResult, AutoTradingStrategy


def _cand(code: str = "005930", name: str = "삼성전자", *, flu: float = 0.2) -> CandidateView:
    return CandidateView(
        code=code,
        name=name,
        rank=1,
        prev_rank=1,
        flu_rt=flu,
        current_price=100000,
        trade_value="1000000000",
        raw={},
    )


def _strategy() -> AutoTradingStrategy:
    return AutoTradingStrategy(client=MagicMock())


def test_orb_no_momentum_falls_through_to_eligible(monkeypatch) -> None:
    """ORB 창에 모멘텀 후보가 없어도 매수를 끊지 않고 eligible을 반환한다."""
    import trading.strategy as st

    monkeypatch.setattr(st, "orb_enabled", True)
    monkeypatch.setattr(st, "orb_morning_momentum_only", True)
    monkeypatch.setattr(st, "is_scalping_mode", lambda: False)
    monkeypatch.setattr(
        st,
        "is_orb_range_forming",
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        st,
        "is_orb_trade_window",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(st, "datetime", MagicMock(now=lambda: datetime(2026, 8, 10, 9, 30)))

    strat = _strategy()
    eligible = [(_cand(), 40.0)]
    result = AutoRunResult()
    out = strat._apply_orb_morning_filter(eligible, result)
    assert out is not None
    assert out == eligible
    assert any("fall" in m.lower() or "계속" in m or "미통과" in m for m in result.report)


def test_orb_breakout_miss_falls_through(monkeypatch) -> None:
    """ORB 돌파 실패 시 None(중단)이 아니라 원본 eligible로 이어간다."""
    import trading.strategy as st
    from trading.orb import OrbCheckResult

    monkeypatch.setattr(st, "orb_enabled", True)
    monkeypatch.setattr(st, "orb_morning_momentum_only", False)
    monkeypatch.setattr(st, "is_scalping_mode", lambda: False)
    monkeypatch.setattr(st, "is_orb_range_forming", lambda *a, **k: False)
    monkeypatch.setattr(st, "is_orb_trade_window", lambda *a, **k: True)
    monkeypatch.setattr(st, "datetime", MagicMock(now=lambda: datetime(2026, 8, 10, 9, 30)))
    monkeypatch.setattr(st, "chart_eval_max_candidates", 5)
    monkeypatch.setattr(
        st,
        "evaluate_orb_breakout",
        lambda *a, **k: OrbCheckResult(passed=False, reason="ORB 고가 미돌파", bonus=0.0),
    )

    strat = _strategy()
    strat.chart.load_minute_candles = MagicMock(return_value=[])  # type: ignore[method-assign]
    eligible = [(_cand(), 40.0)]
    result = AutoRunResult()
    out = strat._apply_orb_morning_filter(eligible, result)
    assert out is not None
    assert out == eligible
    assert any("ORB" in m for m in result.report)
