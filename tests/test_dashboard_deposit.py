"""대시보드 예수금 D+0/D+1/D+2 및 원금 대비 총자산."""

from __future__ import annotations

from kiwoom.client import KiwoomClient
from trading.dashboard_data import _deposit_numbers, apply_live_account_totals


class _Client:
    parse_price = staticmethod(KiwoomClient.parse_price)
    format_amount = staticmethod(KiwoomClient.format_amount)


def test_deposit_numbers_exposes_d1_d2_and_settled_cash() -> None:
    deposit = {
        "entr": "000000471171143",
        "d1_entra": "000000498290277",
        "d2_entra": "000000498290277",
        "ord_alow_amt": "000000498290277",
        "pymn_alow_amt": "000000471171143",
        "d1_buy_exct_amt": "000000000905400",
        "d1_sel_exct_amt": "000000028024534",
    }

    row = _deposit_numbers(_Client(), deposit)

    assert row["cash"] == 471_171_143
    assert row["d1_cash"] == 498_290_277
    assert row["d2_cash"] == 498_290_277
    assert row["settled_cash"] == 498_290_277
    assert row["d1_buy_exct"] == 905_400
    assert row["d1_sel_exct"] == 28_024_534
    assert row["d2_cash_fmt"] == "498,290,277"


def test_settled_cash_falls_back_to_d1_then_d0() -> None:
    deposit = {
        "entr": "1000",
        "d1_entra": "2000",
        "d2_entra": "0",
        "ord_alow_amt": "0",
        "pymn_alow_amt": "1000",
    }
    assert _deposit_numbers(_Client(), deposit)["settled_cash"] == 2000

    deposit["d1_entra"] = "0"
    assert _deposit_numbers(_Client(), deposit)["settled_cash"] == 1000


def test_live_totals_use_d2_cash_plus_holdings_not_d0() -> None:
    acct = {
        "initial_capital_krw": 500_000_000,
        "account_summary": {},
        "trading_summary": {"net_pnl_krw": -264_671},
    }
    out = apply_live_account_totals(
        acct,
        settled_cash=498_290_277,
        holdings_eval=912_000,
    )
    summary = out["account_summary"]
    live = out["live_totals"]

    assert live["cash_krw"] == 498_290_277
    assert live["holdings_eval_krw"] == 912_000
    assert live["total_assets_krw"] == 499_202_277
    assert summary["total_assets_krw"] == 499_202_277
    assert summary["balance_delta_krw"] == -797_723
    assert summary["return_on_capital_pct"] == -0.1595
