"""지난주(9/3) 구멍: 이중 루프, 재진입, 방어 중 신규, 추격, 세금 아래 청산."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from trading.chart_primary import filter_chart_primary_universe
from trading.chart_signals import ChartSignalResult
from trading.news_analyzer import MarketNewsContext
from trading.news_priority import news_score_gate
from trading.position_tracker import PositionTracker
from trading.scoring import CandidateView
from trading.strategy import AutoRunResult, AutoTradingStrategy, HoldingView
from trading.bot import TelegramTradingBot


def _cand(code: str, name: str, *, flu: float = 1.0) -> CandidateView:
    return CandidateView(
        code=code,
        name=name,
        rank=1,
        prev_rank=5,
        flu_rt=flu,
        current_price=50000,
        trade_value="1000000",
        raw={},
    )


def _holding(code: str, name: str, profit: float, qty: int = 10) -> HoldingView:
    return HoldingView(
        code=code,
        name=name,
        qty=qty,
        sellable_qty=qty,
        profit_pct=profit,
        current_price=100000,
        purchase_price=100000,
        order_code=code,
        raw={},
    )


def _state(qty: int = 10, peak: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(
        entry_qty=qty,
        tp_stage=0,
        peak_profit_pct=peak,
        be_scaled=False,
        partial_sold=False,
    )


def test_web_get_bot_passes_start_auto_false(monkeypatch: pytest.MonkeyPatch) -> None:
    import web.commands as cmds

    created: dict = {}

    class FakeBot:
        def __init__(self, *args, **kwargs) -> None:
            created.update(kwargs)

    monkeypatch.setattr(cmds, "TelegramTradingBot", FakeBot)
    cmds._bot = None
    try:
        cmds._get_bot()
        assert created.get("start_auto") is False
    finally:
        cmds._bot = None


def test_bot_start_auto_false_skips_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("trading.bot.get_shared_client", MagicMock())
    monkeypatch.setattr(
        "trading.bot.AutoTradingStrategy",
        lambda client: MagicMock(enabled=False),
    )
    restore = MagicMock(return_value=False)
    monkeypatch.setattr(
        TelegramTradingBot, "restore_auto_trading_from_settings", restore
    )
    bot = TelegramTradingBot(start_auto=False)
    restore.assert_not_called()
    assert bot._owns_auto_loop is False


def test_news_score_gate_blocks_defensive_even_if_allow_buy() -> None:
    ctx = MarketNewsContext(
        sentiment=-0.67,
        risk_score=0.43,
        allow_buy=True,
        defensive_mode=True,
        score_adjustment=-4.0,
    )
    hard_stop, _adjusted, note = news_score_gate(
        base_score=25.0, news=ctx, min_score=19.0
    )
    assert hard_stop is True
    assert "방어" in note


def test_universe_rejects_doosan_style_chase_flu() -> None:
    cands = [_cand("034020", "두산에너빌리티", flu=5.48)]
    kept, rejected = filter_chart_primary_universe(cands, set())
    assert kept == []
    assert any("등락" in r for r in rejected)


def test_chart_primary_skips_reentry_inside_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "trading.strategy.strategy_reentry_cooldown_minutes", 45
    )
    cand = _cand("006400", "삼성SDI", flu=2.97)
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.chart = MagicMock()
    strat.chart.prune_stale_cache = MagicMock()
    strat._cycle_ctx = None
    strat._heartbeat = lambda action, target="": action
    strat._in_morning_buy_window = lambda: False
    strat._execute_buy = MagicMock()
    strat._pick_chart_primary = MagicMock(
        return_value=(
            cand,
            20.0,
            ChartSignalResult(True, 10.0, mode="pullback", reasons=["5MA≥20MA"]),
            False,
        )
    )
    tracker = PositionTracker(path=tmp_path / "positions.json")
    tracker._cooldowns["006400"] = (
        datetime.now() - timedelta(minutes=20)
    ).isoformat(timespec="seconds")
    tracker.save()
    strat.positions = tracker
    result = AutoRunResult()
    strat._run_chart_primary_buy(
        result,
        [],
        MarketNewsContext(sentiment=-0.33, allow_buy=True),
        candidates=[cand],
        held_codes=set(),
        snap=None,
    )
    strat._execute_buy.assert_not_called()
    assert any("쿨다운" in msg for msg in result.report)


def test_blocked_buy_codes_include_tracked_open_lot(tmp_path) -> None:
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    tracker = PositionTracker(path=tmp_path / "positions.json")
    tracker.register("004310", "현대약품", 7850, entry_qty=100)
    strat.positions = tracker
    blocked = strat._blocked_buy_codes([])
    assert "004310" in blocked


def test_other_eod_skips_when_profit_below_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trading.strategy as strat_mod

    monkeypatch.setattr(strat_mod, "is_scalping_mode", lambda: False)
    s = AutoTradingStrategy.__new__(AutoTradingStrategy)
    s.client = MagicMock()
    s.positions = MagicMock()
    s.positions.holding_minutes.return_value = 90.0
    s.positions.is_overnight.return_value = False
    monkeypatch.setattr(s, "_is_eod_sell_all_time", lambda now=None: True)
    monkeypatch.setattr(s, "_is_eod_cut_loss_time", lambda now=None: False)
    monkeypatch.setattr(strat_mod, "round_trip_cost_pct", lambda: 0.23)
    reason, qty, _ = s._evaluate_sell(
        _holding("316140", "우리금융지주", 0.08, qty=56),
        _state(qty=56, peak=0.29),
    )
    assert reason is None
    assert qty == 0


def test_overnight_flatten_skips_tiny_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trading.strategy as strat_mod

    monkeypatch.setattr(strat_mod, "is_scalping_mode", lambda: False)
    s = AutoTradingStrategy.__new__(AutoTradingStrategy)
    s.client = MagicMock()
    s.positions = MagicMock()
    s.positions.holding_minutes.return_value = 90.0
    s.positions.is_overnight.return_value = True
    monkeypatch.setattr(s, "_is_eod_sell_all_time", lambda now=None: False)
    monkeypatch.setattr(s, "_is_eod_cut_loss_time", lambda now=None: False)
    monkeypatch.setattr(strat_mod, "round_trip_cost_pct", lambda: 0.23)
    reason, qty, _ = s._evaluate_sell(
        _holding("316140", "우리금융지주", 0.08, qty=56),
        _state(qty=56, peak=0.29),
    )
    assert reason is None
    assert qty == 0
