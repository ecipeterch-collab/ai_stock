# Notebook Basic Strategy Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** Wire notebook MA/candle/chart patterns into the existing chart buy filter as hard gates + score bonuses.

**Architecture:** Pure detectors in `trading/notebook_patterns.py`; `evaluate_chart_signals` applies gate then bonuses. Config toggles in `config.py` / `config.example.py`.

**Tech Stack:** Python 3.10+, pytest

## Global Constraints

- Do not change sell logic
- Do not remove VWAP/RSI/volume filters
- Duck-type OHLC (no import cycle with `chart_signals`)

---

### Task 1: Config knobs

**Files:**
- Modify: `config/config.example.py`
- Modify: `config/config.py`

- [x] Add `notebook_*` settings after chart block

### Task 2: Pattern module + unit tests

**Files:**
- Create: `trading/notebook_patterns.py`
- Create: `tests/test_notebook_patterns.py`

- [x] MA series/slope/golden-cross gate
- [x] Candle detectors + chart pattern heuristics
- [x] pytest green

### Task 3: Wire into chart_signals

**Files:**
- Modify: `trading/chart_signals.py`

- [x] Call notebook evaluate after daily MA checks; reject on gate/bearish block; add capped bonus

### Task 4: Integration test

**Files:**
- Create: `tests/test_chart_signals_notebook.py`

- [x] Gate reject / bonus apply with synthetic candles
