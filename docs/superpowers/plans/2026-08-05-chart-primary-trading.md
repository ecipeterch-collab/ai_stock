# Chart-Primary Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Chart pass/fail drives buys; regime/score/flu/news are advisory.

**Files:**
- Create `trading/chart_primary.py` — universe filter + advisory notes
- Modify `trading/strategy.py` — `_run_buy_phase` chart-primary branch
- Modify `trading/news_priority.py` — no hard stop when chart-primary
- Modify `config/config.py` + `config.example.py`
- Create `tests/test_chart_primary.py`

## Task 1: Tests for universe + advisory

Write failing tests for `filter_chart_primary_universe` (held/ETF only) and advisory note builders.

## Task 2: Implement chart_primary helpers

## Task 3: Wire strategy buy path + config + /strategy text

## Task 4: Run full test suite
