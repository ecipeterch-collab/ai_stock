# Plug Thursday Loss Holes

Date: 2026-09-06  
Status: Approved (user: 모두해줘)

## Goal

Stop last week's structural drains: dual auto-trade loops doubling size, chart-primary skipping reentry cooldown, new buys while defensive, +5% chase, and EOD/overnight sells that lose money after tax.

## In scope

1. **Web does not own the auto loop.** `TelegramTradingBot(start_auto=False)` from `web.commands._get_bot`. Web `/auto on|off` writes `runtime_settings` and dashboard status only. The systemd bot loop re-reads `get_auto_trading_enabled()` each tick.
2. **Chart-primary respects reentry cooldown** (`strategy_reentry_cooldown_minutes`, default 45).
3. **Blocked buy codes = Kiwoom holdings ∪ `positions.json` open lots** (reload from disk each buy phase) so an in-flight register blocks a second process/cycle before fill.
4. **Defensive mode blocks new buys** (buy / crash / trend), even when `allow_buy` is still true. Sells unchanged.
5. **Chart-primary max same-day 등락 8% → 4%.**
6. **Do not EOD-flatten or overnight-flatten a non-mega name when `0 < profit < round_trip_cost_pct()`.** Stops and trailing still apply.

## Out of scope

Stop width, paper vs real, deploying to OCI in this change (code only unless asked).

## Tests

- Web `_get_bot()` constructs `TelegramTradingBot(start_auto=False)`.
- `start_auto=False` does not call `restore_auto_trading_from_settings`.
- Chart-primary skips a name exited 20 minutes ago when cooldown is 45.
- `news_score_gate` hard-stops when `defensive_mode=True` and sentiment is −0.67.
- Universe rejects flu 5.48%, keeps 4.0%.
- Other EOD at +0.08% does not flatten; +0.80% still does.
- Overnight flatten skipped at +0.08%; still fires at −1.0%.
