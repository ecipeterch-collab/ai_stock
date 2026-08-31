# Plug Loss Holes Implementation Plan

> Inline execution in this session. TDD per task.

**Goal:** Close geopolitics-defensive, tax-losing breakeven, limit-exit delay, and oversized 1-share holes without changing trailing or −4% stops.

**Architecture:** Config + existing `news_analyzer` / `strategy` sell-buy helpers. No new modules except a `round_trip_cost_pct` helper next to fee settings.

**Tech Stack:** Python, pytest, existing Kiwoom client `sell_market` / `sell_limit`.

## Files

- Modify `trading/news_analyzer.py` — skip risk hits on `지정학`
- Modify `trading/account_settings.py` — `round_trip_cost_pct()`
- Modify `trading/strategy.py` — BE cost floor, market vs limit, qty 0 skip
- Modify `config/config.py` + `config/config.example.py` — `news_defensive_loss_pct = -2.0`
- Modify `tests/test_news_analyzer.py`, `tests/test_breakeven_scale.py`, `tests/test_defensive_overnight.py`
- Create `tests/test_position_qty.py`, `tests/test_exit_order_type.py`

## Tasks

1. News risk exclusion + defensive −2.0 (tests then code)
2. Breakeven cost floor (tests then code)
3. Market vs limit on urgent exits (tests then code)
4. Qty 0 when 1 share > target (tests then code)
5. Full related pytest
