# Advise Sells / Notify Buys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swing auto-buys stay automatic (candidate Telegram every cycle). Discretionary sells become user-approved proposals; only `profit_pct <= -5%` auto-sells.

**Architecture:** New `trading/trade_proposals.py` persists pending/held/ignored sells. `_run_sell_phase` branches after existing confirm/volume checks. Buy phase always emits `【매수 후보】` (or appends `이번 후보` onto `【자동매수】`). Telegram `reply_markup` + callback_query (and `/sellok` `/buyok` text) complete the loop.

**Tech Stack:** Python 3.12, pytest, existing FastAPI web command runner, Telegram Bot API sendMessage/answerCallbackQuery.

## Global Constraints

- Swing only; scalping auto buy/sell unchanged.
- Disaster auto sell at `strategy_disaster_stop_pct = 5.0`.
- No tap on a proposal → no sell order (overnight allowed).
- Buys are not gated; notify every buy-phase cycle including no-order cycles.
- Manual `/buy` over `position_max_qty` or `qty * price > 3 * position_target_krw` requires `/buyok`.
- Do not commit unless the user asks.
- Config keys also try/except fallback so gitignored `config/config.py` still runs.

---

### Task 1: Proposal store and copy

**Files:**
- Create: `trading/trade_proposals.py`
- Test: `tests/test_trade_proposals.py`

**Interfaces:**
- Produces: `TradeProposal`, `TradeProposalStore`, `sell_proposal_category`, `sell_proposal_markup`, `format_sell_proposal_text`, `format_buy_watchlist`

### Task 2: Sell gate

**Files:**
- Modify: `trading/strategy.py` (`AutoRunResult.button_events`, `_run_sell_phase`, `__init__` store, `_reset_daily_counter`)
- Test: `tests/test_advise_sells.py`

### Task 3: Buy watchlist events

**Files:**
- Modify: `trading/strategy.py` `_run_buy_phase` / `_execute_buy` / chart-primary
- Test: `tests/test_buy_watchlist.py`

### Task 4: Telegram + commands

**Files:**
- Modify: `telegram/tel_send.py`, `trading/bot.py`, `web/commands.py`
- Test: `tests/test_manual_orders.py`, `tests/test_advise_callbacks.py`

### Task 5: Config

**Files:**
- Modify: `config/config.example.py`, `config/config.py` (local, not committed)
