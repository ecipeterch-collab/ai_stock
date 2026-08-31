"""급한 청산은 시장가, 익절·트레일은 지정가."""

from trading.strategy import AutoTradingStrategy


def test_exit_uses_market_for_stop_breakeven_and_defensive_dump() -> None:
    assert AutoTradingStrategy._exit_uses_market(
        "손절 (-4.09% <= -4.0%)"
    )
    assert AutoTradingStrategy._exit_uses_market(
        "본전스탑 (고점 4.93% → 현재 0.40%)"
    )
    assert AutoTradingStrategy._exit_uses_market(
        "본전스탑 50% 매도 (고점 3.30% → 현재 0.47%)"
    )
    assert AutoTradingStrategy._exit_uses_market(
        "방어모드 매도 (뉴스 악화, 수익 -2.97%)"
    )
    assert AutoTradingStrategy._exit_uses_market("오버나잇 금지 청산")
    assert AutoTradingStrategy._exit_uses_market("장마감 전량 청산 (15:20)")


def test_exit_keeps_limit_for_trailing_and_take_profit() -> None:
    assert not AutoTradingStrategy._exit_uses_market(
        "수익보호 트레일링 (고점 5.15% → 현재 3.32%)"
    )
    assert not AutoTradingStrategy._exit_uses_market(
        "본전스탑 잔량 트레일링 (고점 3.30% → 현재 0.66%)"
    )
    assert not AutoTradingStrategy._exit_uses_market(
        "방어모드 트레일링 (리스크 0.78)"
    )
    assert not AutoTradingStrategy._exit_uses_market(
        "수익실현 +4% 50% 매도"
    )
