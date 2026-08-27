"""뉴스 심리 오전/오후 세션 로그."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from trading.news_analyzer import MarketNewsAnalyzer, MarketNewsContext, NewsItem
from trading.news_sentiment_log import (
    append_snapshot,
    build_session_summary,
    format_session_summary_text,
    session_for_time,
)


def test_session_for_time_splits_morning_afternoon() -> None:
    assert session_for_time(datetime(2026, 8, 20, 9, 10)) == "morning"
    assert session_for_time(datetime(2026, 8, 20, 11, 59)) == "morning"
    assert session_for_time(datetime(2026, 8, 20, 12, 0)) == "afternoon"
    assert session_for_time(datetime(2026, 8, 20, 14, 0)) == "afternoon"
    assert session_for_time(datetime(2026, 8, 20, 15, 29)) == "afternoon"
    assert session_for_time(datetime(2026, 8, 20, 8, 59)) == "other"
    assert session_for_time(datetime(2026, 8, 20, 15, 30)) == "other"


def test_session_summary_averages_morning_and_afternoon(tmp_path: Path) -> None:
    path = tmp_path / "news_sentiment.jsonl"
    append_snapshot(
        MarketNewsContext(sentiment=-0.40, risk_score=0.20),
        path=path,
        now=datetime(2026, 8, 20, 9, 30),
    )
    append_snapshot(
        MarketNewsContext(sentiment=-0.80, risk_score=0.40),
        path=path,
        now=datetime(2026, 8, 20, 10, 30),
    )
    append_snapshot(
        MarketNewsContext(sentiment=-0.90, risk_score=0.50),
        path=path,
        now=datetime(2026, 8, 20, 13, 0),
    )
    summary = build_session_summary(
        target_date=datetime(2026, 8, 20).date(),
        path=path,
    )
    morning = summary["sessions"]["morning"]
    afternoon = summary["sessions"]["afternoon"]
    assert morning["count"] == 2
    assert morning["avg_sentiment"] == -0.60
    assert morning["min_sentiment"] == -0.80
    assert morning["max_sentiment"] == -0.40
    assert afternoon["count"] == 1
    assert afternoon["avg_sentiment"] == -0.90
    assert afternoon["block_ratio"] == 1.0
    text = format_session_summary_text(summary)
    assert "오전" in text
    assert "오후" in text
    assert "-0.60" in text or "-0.6" in text


def test_live_analyze_records_snapshot(tmp_path: Path, monkeypatch) -> None:
    import trading.news_sentiment_log as nslog

    monkeypatch.setattr(nslog, "SENTIMENT_LOG_FILE", tmp_path / "news_sentiment.jsonl")
    analyzer = MarketNewsAnalyzer()
    monkeypatch.setattr(
        analyzer,
        "fetch_headlines",
        lambda: [
            NewsItem(category="국내경제", title="금리인상 폭락 약세"),
            NewsItem(category="글로벌경제", title="markets crash selloff"),
        ],
    )
    ctx = analyzer.analyze()
    summary = build_session_summary(path=tmp_path / "news_sentiment.jsonl")
    total = sum(s["count"] for s in summary["sessions"].values())
    assert total == 1
    assert ctx.sentiment < 0


def test_injected_headlines_do_not_record(tmp_path: Path, monkeypatch) -> None:
    import trading.news_sentiment_log as nslog

    monkeypatch.setattr(nslog, "SENTIMENT_LOG_FILE", tmp_path / "news_sentiment.jsonl")
    analyzer = MarketNewsAnalyzer()
    analyzer.analyze(
        [
            NewsItem(category="국내경제", title="금리인상 폭락"),
        ]
    )
    summary = build_session_summary(path=tmp_path / "news_sentiment.jsonl")
    total = sum(s["count"] for s in summary["sessions"].values())
    assert total == 0
