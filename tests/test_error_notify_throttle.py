"""반복되는 체결/잔고 조회 실패 알림 스로틀."""

from __future__ import annotations

from unittest.mock import MagicMock

from kiwoom.client import KiwoomAPIError
from trading.strategy import (
    AutoRunResult,
    AutoTradingStrategy,
    clear_error_event_bucket,
    throttle_error_event,
)


def test_throttle_emits_first_error_then_suppresses_same_key() -> None:
    state: dict = {}
    first = throttle_error_event(
        state, "fills", "체결 조회 실패: 8001", now=100.0, cooldown_sec=60.0
    )
    second = throttle_error_event(
        state, "fills", "체결 조회 실패: 8001", now=110.0, cooldown_sec=60.0
    )
    assert first == "체결 조회 실패: 8001"
    assert second is None


def test_throttle_reemits_after_cooldown_with_suppressed_count() -> None:
    state: dict = {}
    throttle_error_event(state, "fills", "체결 조회 실패: 8001", now=0.0, cooldown_sec=60.0)
    throttle_error_event(state, "fills", "체결 조회 실패: 8001", now=10.0, cooldown_sec=60.0)
    throttle_error_event(state, "fills", "체결 조회 실패: 8001", now=20.0, cooldown_sec=60.0)
    again = throttle_error_event(
        state, "fills", "체결 조회 실패: 8001", now=70.0, cooldown_sec=60.0
    )
    assert again is not None
    assert "체결 조회 실패: 8001" in again
    assert "2회 생략" in again


def test_throttle_reset_allows_immediate_notify() -> None:
    state: dict = {}
    throttle_error_event(state, "fills", "체결 조회 실패: 8001", now=0.0, cooldown_sec=60.0)
    clear_error_event_bucket(state, "fills")
    again = throttle_error_event(
        state, "fills", "체결 조회 실패: 8001", now=1.0, cooldown_sec=60.0
    )
    assert again == "체결 조회 실패: 8001"


def _strategy_for_fills() -> AutoTradingStrategy:
    strat = AutoTradingStrategy.__new__(AutoTradingStrategy)
    strat.client = MagicMock()
    strat._error_notify_state = {}
    return strat


def test_collect_new_fills_notifies_once_for_repeated_query_errors(
    monkeypatch,
) -> None:
    monkeypatch.setattr("trading.strategy.api_error_notify_cooldown_sec", 60.0)
    monkeypatch.setattr("trading.strategy.time.monotonic", lambda: 100.0)
    strat = _strategy_for_fills()
    strat.client.get_executions.side_effect = KiwoomAPIError("조회 실패: 4007")

    first = AutoRunResult()
    strat._collect_new_fills(first)
    second = AutoRunResult()
    strat._collect_new_fills(second)

    assert any("체결 조회 실패" in e for e in first.events)
    assert second.events == []


def test_collect_new_fills_does_not_telegram_invalid_token_errors() -> None:
    strat = _strategy_for_fills()
    strat.client.get_executions.side_effect = KiwoomAPIError(
        "ka10076 오류: 인증에 실패했습니다[8005:Token이 유효하지 않습니다] "
        '({"return_msg": "인증에 실패했습니다[8005:Token이 유효하지 않습니다]", '
        '"return_code": 3})'
    )
    result = AutoRunResult()
    strat._collect_new_fills(result)
    assert result.events == []
