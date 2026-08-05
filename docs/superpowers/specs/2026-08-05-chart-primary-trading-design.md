# Chart-Primary Trading Mode Design

Date: 2026-08-05  
Status: Approved

## Goal

Make **chart signals the primary buy decision**. Regime, market breadth, flu-rate windows, strategy score, and news become **advisory / notification only**.

## Hard gates (unchanged)

- Market open
- Buy time windows
- Daily loss stop
- Loss circuit breaker
- Daily buy count limit
- Max positions
- Portfolio heat (risk)
- Sell rules (TP / SL / trailing / EOD / stagnation)

Practical exclusions (not “strategy filters”): already held, ETF/ETN block.

## Chart decides buys

1. Scan trade-value rank universe.
2. Exclude held + ETF only.
3. Evaluate chart (pullback and/or momentum profile).
4. Buy if `chart.passed` (`>= chart_min_score`).
5. Tie-break with advisory score; do **not** reject on `strategy_min_score`.

## Advisory only (heartbeat / buy reason text)

- Regime channel on/off
- Market bullish / weak-market combo
- Flu-rate and rank-improve windows
- Strategy composite score vs `strategy_min_score`
- News sentiment / risk / secondary penalty (no hard stop, including extreme)

## Config

- `chart_primary_mode = True`
- Existing `chart_*` knobs remain the real quality bar

## Out of scope

- Sell rule rewrite
- Scalping mode redesign
- Full removal of crash/trend phases (news demoted; crash still niche)
