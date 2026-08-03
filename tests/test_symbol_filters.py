"""ETF/종목 필터: 스윙 매수에서 일반 ETF까지 차단."""

from __future__ import annotations

from trading.symbol_filters import is_etf, is_leveraged_etf


def test_is_etf_blocks_cash_and_index_etfs() -> None:
    assert is_etf("KODEX CD금리액티브(합성)", "459580")
    assert is_etf("KODEX 미국S&P500", "379800")
    assert is_etf("TIGER 미국S&P500", "360750")


def test_is_etf_blocks_leveraged_etfs() -> None:
    assert is_etf("KODEX 코스닥150레버리지", "233740")
    assert is_leveraged_etf("KODEX 코스닥150레버리지", "233740")


def test_is_etf_allows_common_stocks() -> None:
    assert not is_etf("SK하이닉스", "000660")
    assert not is_etf("삼성전자", "005930")
    assert not is_etf("한미반도체", "042700")
    assert not is_leveraged_etf("SK하이닉스", "000660")


def test_filter_and_rank_rejects_plain_etf_when_block_etf(monkeypatch) -> None:
    import trading.scoring as scoring

    monkeypatch.setattr(scoring, "strategy_block_etf", True)
    monkeypatch.setattr(scoring, "strategy_block_leveraged_etf", True)

    cand = scoring.CandidateView(
        code="459580",
        name="KODEX CD금리액티브(합성)",
        rank=1,
        prev_rank=2,
        flu_rt=0.1,
        current_price=1_075_000,
        trade_value="1",
        raw={},
    )
    eligible, rejected = scoring.filter_and_rank_candidates([cand], held_codes=set())
    assert eligible == []
    assert any("ETF" in msg for msg in rejected)
