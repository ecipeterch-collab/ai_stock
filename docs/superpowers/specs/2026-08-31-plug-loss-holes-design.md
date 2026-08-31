# Plug Loss Holes (Approach A)

Date: 2026-08-31  
Status: Approved

## Goal

Stop the three structural drains seen in the 84-trade journal: geopolitics-driven defensive dumps, breakeven exits that lose money after tax, and forced 1-share buys of names above the per-name budget. Trailing winners stay as they are.

## In scope

1. **Geopolitics RSS out of risk score.** `지정학` items are already excluded from sentiment. Also exclude them from `risk_hits`. Briefing headlines still include geopolitics. Korean/global economy headlines still feed risk (e.g. `전쟁` in `국내경제`).
2. **Defensive dump threshold −0.5% → −2.0%.** Same-day defensive sell only if profit ≤ −2.0%. Defensive trailing unchanged. Overnight skip unchanged.
3. **Breakeven stop respects round-trip cost.** Round-trip = `2 × commission + sell tax` (config/runtime, default 0.23%). Fire 본전스탑 only if `cost ≤ profit < floor`. Below cost, hold until stop-loss (−4%) or a later bounce above cost.
4. **Urgent exits use market orders.** Market: `손절`, `본전스탑` (not remainder trailing), `방어모드 매도`. Limit unchanged: take-profit, 수익보호 트레일, `본전스탑 잔량 트레일링`, `방어모드 트레일링`, EOD.
5. **Skip if one share exceeds target.** `_base_order_qty` returns 0 when `price > target`. Auto buy paths skip qty 0. Manual `/buy` unchanged.

## Out of scope

- Stop width (−4%), chart-primary +8% chase block, stagnation timer, auto interval, paper vs real, afternoon scan reduction (approach B).

## Tests

- Geopolitics-only RSS → `risk_score == 0`; domestic war headline can still raise risk.
- Peak +4.93% / now +0.09% → no 본전스탑; +0.40% → 본전스탑.
- Same-day defensive −1.5% → hold; −2.97% → dump.
- Price 1,652,000 vs target 1,000,000 → qty 0; auto buy does not place an order.
- `_exit_uses_market` true for 손절/본전스탑/방어모드 매도, false for 수익보호 트레일.
