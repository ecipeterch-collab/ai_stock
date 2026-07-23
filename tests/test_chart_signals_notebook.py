"""차트 필터 + 노트 전략 통합 테스트."""

from __future__ import annotations

from trading.chart_signals import Candle, evaluate_chart_signals, evaluate_daily_trend_only


def _daily_uptrend(n: int = 40, start: int = 10000) -> list[Candle]:
    out: list[Candle] = []
    for i in range(n):
        px = start + i * 50
        out.append(
            Candle(
                ts=f"202601{i+1:02d}" if i < 28 else f"202602{i-27:02d}",
                open=px - 20,
                high=px + 30,
                low=px - 40,
                close=px,
                volume=10000,
            )
        )
    return out


def _daily_downtrend(n: int = 40, start: int = 20000) -> list[Candle]:
    out: list[Candle] = []
    for i in range(n):
        px = start - i * 50
        out.append(
            Candle(
                ts=f"202601{i+1:02d}" if i < 28 else f"202602{i-27:02d}",
                open=px + 20,
                high=px + 40,
                low=px - 30,
                close=px,
                volume=10000,
            )
        )
    return out


def _minute_flat(n: int = 30, base: int = 12000) -> list[Candle]:
    out: list[Candle] = []
    for i in range(n):
        px = base + (i % 3) * 10
        out.append(
            Candle(
                ts=f"2026072310{i:02d}00",
                open=px,
                high=px + 20,
                low=px - 20,
                close=px + 5,
                volume=5000 + i * 10,
            )
        )
    return out


def test_daily_trend_rejects_notebook_ma_down(monkeypatch):
    import trading.chart_signals as cs
    import trading.notebook_patterns as np

    monkeypatch.setattr(cs, "notebook_strategy_enabled", True)
    monkeypatch.setattr(np, "notebook_strategy_enabled", True)
    monkeypatch.setattr(np, "notebook_require_ma_uptrend", True)

    daily = _daily_downtrend()
    # close may still be above MA early; force enough decline
    result = evaluate_daily_trend_only(daily, current_price=daily[-1].close)
    # Either daily trend weak OR notebook gate
    assert result.passed is False


def test_daily_trend_accepts_uptrend_with_notebook(monkeypatch):
    import trading.chart_signals as cs
    import trading.notebook_patterns as np

    monkeypatch.setattr(cs, "notebook_strategy_enabled", True)
    monkeypatch.setattr(np, "notebook_strategy_enabled", True)
    monkeypatch.setattr(np, "notebook_require_ma_uptrend", True)

    daily = _daily_uptrend()
    result = evaluate_daily_trend_only(daily, current_price=daily[-1].close)
    assert result.passed is True
    assert any("장기MA" in r or "MA" in r or "골든" in r for r in result.reasons)


def test_evaluate_chart_signals_notebook_gate(monkeypatch):
    import trading.chart_signals as cs
    import trading.notebook_patterns as np

    monkeypatch.setattr(cs, "notebook_strategy_enabled", True)
    monkeypatch.setattr(np, "notebook_strategy_enabled", True)
    monkeypatch.setattr(np, "notebook_require_ma_uptrend", True)
    # Relax RSI/VWAP so gate is the focus — use disabled notebook candle path
    monkeypatch.setattr(cs, "chart_rsi_min", 0)
    monkeypatch.setattr(cs, "chart_rsi_max", 100)

    daily = _daily_downtrend()
    minute = _minute_flat(base=daily[-1].close)
    result = evaluate_chart_signals(
        daily_candles=daily,
        minute_candles=minute,
        current_price=daily[-1].close,
        mode="pullback",
    )
    assert result.passed is False
