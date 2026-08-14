"""ChartSignalAnalyzer.prefetch_daily 회귀 테스트."""

from __future__ import annotations

from trading.chart_signals import ChartSignalAnalyzer


class _FakeClient:
    def __init__(self) -> None:
        self.daily_calls: list[str] = []
        self.minute_calls: list[str] = []

    @staticmethod
    def normalize_stock_code(code: str) -> str:
        return str(code).zfill(6)

    def get_daily_chart(self, code: str, base_dt: str | None = None):
        self.daily_calls.append(code)
        return [
            {
                "dt": "20260811",
                "open_pric": "100",
                "high_pric": "110",
                "low_pric": "90",
                "cur_prc": "105",
                "trde_qty": "1000",
            }
        ]

    def get_minute_chart(self, code: str, tic_scope: str = "5", base_dt: str | None = None):
        self.minute_calls.append(code)
        return [
            {
                "cntr_tm": "20260811093000",
                "open_pric": "100",
                "high_pric": "101",
                "low_pric": "99",
                "cur_prc": "100",
                "trde_qty": "10",
            }
        ]


def test_prefetch_daily_exists_and_loads_unique_codes() -> None:
    client = _FakeClient()
    chart = ChartSignalAnalyzer(client)  # type: ignore[arg-type]

    assert hasattr(chart, "prefetch_daily")
    chart.prefetch_daily(["005930", "005930", "035420"])

    assert client.daily_calls == ["005930", "035420"]
    assert chart.cache_stats()["daily"] == 2


def test_load_minute_candles_still_works() -> None:
    client = _FakeClient()
    chart = ChartSignalAnalyzer(client)  # type: ignore[arg-type]
    bars = chart.load_minute_candles("005930")
    assert len(bars) == 1
    assert bars[0].close == 100
    assert client.minute_calls == ["005930"]
