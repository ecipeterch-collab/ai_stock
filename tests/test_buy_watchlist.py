"""Buy-candidate Telegram events: first ping, then throttle."""

from __future__ import annotations

from unittest.mock import MagicMock

from trading.news_analyzer import MarketNewsContext
from trading.strategy import AutoRunResult, AutoTradingStrategy


def _flush_strategy() -> AutoTradingStrategy:
    s = AutoTradingStrategy.__new__(AutoTradingStrategy)
    s._buy_watchlist = []
    s._buy_skip_reason = "후보 없음"
    return s


def test_flush_without_buy_sends_candidate_event() -> None:
    strat = _flush_strategy()
    strat._buy_watchlist = [("KB금융", "105560", 18.0), ("LG에너지솔루션", "373220", 10.0)]
    strat._buy_skip_reason = "일일 매수 한도 (10회)"
    result = AutoRunResult()
    strat._flush_buy_watchlist(result, 0, now=1.0)
    assert len(result.events) == 1
    assert result.events[0].startswith("【매수 후보】")
    assert "매수 없음" in result.events[0]
    assert "KB금융" in result.events[0]


def test_flush_empty_watchlist_still_notifies() -> None:
    strat = _flush_strategy()
    result = AutoRunResult()
    strat._flush_buy_watchlist(result, 0, now=1.0)
    assert result.events[0].startswith("【매수 후보】 없음")


def test_flush_same_watchlist_is_silent_even_after_interval() -> None:
    strat = _flush_strategy()
    strat._buy_watchlist = [("KB금융", "105560", 18.0)]
    strat._buy_skip_reason = "일일 매수 한도 (10회)"
    first = AutoRunResult()
    strat._flush_buy_watchlist(first, 0, now=1.0)
    second = AutoRunResult()
    strat._flush_buy_watchlist(second, 0, now=1.0 + 20 * 60)
    assert len(first.events) == 1
    assert second.events == []


def test_flush_new_list_waits_for_interval_then_sends() -> None:
    strat = _flush_strategy()
    strat._buy_watchlist = [("KB금융", "105560", 18.0)]
    first = AutoRunResult()
    strat._flush_buy_watchlist(first, 0, now=1.0)
    strat._buy_watchlist = [("삼성SDI", "006400", 16.0)]
    early = AutoRunResult()
    strat._flush_buy_watchlist(early, 0, now=1.0 + 60)
    later = AutoRunResult()
    strat._flush_buy_watchlist(later, 0, now=1.0 + 15 * 60)
    assert early.events == []
    assert len(later.events) == 1
    assert "삼성SDI" in later.events[0]


def test_flush_after_buy_appends_and_does_not_duplicate() -> None:
    strat = _flush_strategy()
    strat._buy_watchlist = [("삼성SDI", "006400", 16.0), ("KB금융", "105560", 18.0)]
    result = AutoRunResult()
    result.add_event("【자동매수】\n종목: 삼성SDI(006400)\n점수: 16.0점 · 차트\n")
    strat._flush_buy_watchlist(result, 0, now=1.0)
    assert len(result.events) == 1
    assert "이번 후보" in result.events[0]
    assert "← 매수" in result.events[0]
    assert not any(e.startswith("【매수 후보】") for e in result.events)


def test_flush_after_buy_appends_even_inside_interval() -> None:
    strat = _flush_strategy()
    strat._buy_watchlist = [("삼성SDI", "006400", 16.0)]
    quiet = AutoRunResult()
    strat._flush_buy_watchlist(quiet, 0, now=1.0)
    result = AutoRunResult()
    result.add_event("【자동매수】\n종목: 삼성SDI(006400)\n점수: 16.0점 · 차트\n")
    strat._flush_buy_watchlist(result, 0, now=1.0 + 10)
    assert "이번 후보" in result.events[0]
    assert "← 매수" in result.events[0]


def test_defensive_buy_phase_records_skip_reason(monkeypatch) -> None:
    import trading.strategy as strat_mod

    monkeypatch.setattr(strat_mod, "is_scalping_mode", lambda: False)
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat._cycle_ctx = None
    strat.positions = MagicMock()
    strat.positions.load = MagicMock()
    strat.positions.codes.return_value = set()
    strat._buy_watchlist = [("x", "000000", 0.0)]
    strat._buy_skip_reason = "후보 없음"
    strat._buy_count_date = __import__("datetime").date.today()
    strat._trend_buy_count_date = strat._buy_count_date
    strat._crash_buy_count_date = strat._buy_count_date
    strat._circuit_reset_date = strat._buy_count_date
    strat._buy_count = 0
    strat._trend_buy_count = 0
    strat._crash_buy_count = 0
    strat.proposals = MagicMock()
    news = MarketNewsContext(defensive_mode=True, sentiment=-1.0)
    result = AutoRunResult()
    strat._run_buy_phase(result, holdings=[], news=news)
    assert "방어모드" in strat._buy_skip_reason
