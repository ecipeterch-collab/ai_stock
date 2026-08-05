"""차트 우선 매수 유니버스·참고 메모."""

from __future__ import annotations

from trading.chart_primary import (
    advisory_market_note,
    build_buy_advisory_notes,
    filter_chart_primary_universe,
)
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


def test_universe_keeps_overheated_non_etf() -> None:
    """등락 과열이어도 차트 우선 유니버스에서는 제외하지 않는다."""
    cands = [
        _cand("005930", "삼성전자", flu=2.5),
        _cand("069500", "KODEX 200", flu=0.1),
    ]
    kept, rejected = filter_chart_primary_universe(cands, set())
    assert [c.code for c in kept] == ["005930"]
    assert any("ETF" in r for r in rejected)


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
    cands = [_cand(f"{i:06d}", f"종목{i}", flu=1.0 if i < 10 else -1.0) for i in range(15)]
    note = advisory_market_note(cands)
    assert "종목" in note
