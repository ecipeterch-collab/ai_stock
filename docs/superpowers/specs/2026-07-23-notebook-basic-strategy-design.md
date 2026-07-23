# 노트 매매법 → 기본 차트 전략 (필터 강화)

**Date:** 2026-07-23  
**Status:** Approved design (pending user spec review)  
**Approach:** A — 기존 차트 필터에 필수 조건 + 가점 추가

## Problem

손글씨 노트(이동평균 골든/데드크로스, 캔들 패턴, 차트 도형)의 매매 규칙을 자동매매 기본 전략으로 쓰고 싶다.  
현재 `chart_signals.py`는 VWAP·MA 정렬·RSI·거래량만 보고, 노트식 크로스·기울기·캔들·차트형은 없다.

## Goals

- 기존 스윙 매수 파이프라인(순위 → 점수 → 차트 필터 → 매수)을 유지한다.
- 노트 규칙을 **하드게이트(매수 금지)** 와 **가점**으로 차트 평가에 녹인다.
- on/off·가중치는 config로 조절 가능하게 한다.

## Non-goals (1차)

- 새 `basic` / `notebook` 전략 모드
- 패턴 기반 자동 매도 (손절·익절·트레일은 기존 로직 유지)
- 다이아몬드·쐐기·박스권 등 탐지 난이도·오탐 높은 도형
- 기존 VWAP/RSI/거래량 필터 제거

## Integration point

```
AutoTradingStrategy._pick_with_chart_filter
  → ChartSignalAnalyzer.evaluate_candidate
    → evaluate_chart_signals(daily, minute, ...)
         + notebook_patterns (NEW)
```

매도 경로(`_evaluate_sell`)는 변경하지 않는다.

## Architecture

### New module: `trading/notebook_patterns.py`

순수 함수만. API/주문 호출 없음. 입력은 `list[Candle]` (+ optional mode).

| Function | Role |
|----------|------|
| `ma_series(closes, period)` | SMA 시계열 |
| `ma_slope_up(ma_values, lookback)` | 장기선 상승 기울기 여부 |
| `detect_golden_cross(fast, slow)` | 직전 이하 → 현재 초과 크로스 |
| `evaluate_ma_gate(...)` | 하드게이트: 장기선 상승 + 단기≥장기 |
| `detect_candle_patterns(candles)` | 큰양선/도지/하라미·망치/포선/모닝스타 |
| `detect_chart_patterns(candles)` | 쌍바닥·역H&S·상승깃발·상승삼각 / 약세형 |
| `NotebookPatternResult` | `gate_ok`, `gate_reject`, `bonus`, `reasons`, `bearish_block` |

### Wire-in: `trading/chart_signals.py`

`evaluate_chart_signals` 흐름:

1. 기존 일봉 추세·MA 정렬·분봉 충분성 검사 (유지)
2. **`notebook_strategy_enabled`이면** `evaluate_ma_gate` — 실패 시 즉시 reject
3. 기존 RSI / VWAP / 거래량·반등 로직 (유지)
4. 캔들·차트형 탐지 → `bonus = min(sum, notebook_max_bonus)` 가산  
   - `notebook_pattern_block_bearish`이고 약세 차트형이면 reject
5. `passed = score >= chart_min_score` (기존과 동일)

일봉-only fallback(`evaluate_daily_trend_only`)에도 MA 하드게이트만 적용 (캔들/도형 가점은 분봉 있을 때).

### Config (`config.example.py` + local `config.py`)

```python
notebook_strategy_enabled = True
notebook_require_ma_uptrend = True
notebook_ma_slope_lookback = 3
notebook_candle_bonus_enabled = True
notebook_pattern_block_bearish = True
notebook_max_bonus = 5.0
# 선택 가중치 (기본값)
notebook_bonus_big_bull = 2.0
notebook_bonus_doji_reversal = 1.5
notebook_bonus_hammer_harami = 2.0
notebook_bonus_engulfing = 2.5
notebook_bonus_morning_star = 3.0
notebook_bonus_double_bottom = 2.5
notebook_bonus_inv_head_shoulders = 2.0
notebook_bonus_bull_flag = 2.0
notebook_bonus_asc_triangle = 2.0
```

로컬 `config.py`에 동일 키 추가. import는 `chart_signals` / `notebook_patterns`에서 읽는다.

## Rule details (from notebook)

### MA (필수)

- **매수 허용:** `MA_fast >= MA_slow` 이고 `MA_slow`가 lookback 구간에서 상승(현재 > lookback전).
- **매수 금지:** 골든크로스/정렬이어도 장기선이 하락 중이면 거절 (노트 “매수 금지”).
- 기간: 기존 `chart_ma_fast`(5), `chart_ma_slow`(20) 재사용. (노트 표의 100/200은 1차 미적용)

### 캔들 가점 (분봉 최근 봉 기준, 추세 맥락은 일·분봉 closes)

| Pattern | Detection sketch | Bonus |
|---------|------------------|-------|
| 큰 양선 | body >= 최근 N봉 평균 body × 1.5, close > open | +2 |
| 도지 (하락 후) | \|close-open\| / range 작음 + 직전 하락 추세 | +1.5 |
| 하라미/망치 | 작은 몸통 + 아랫꼬리 ≥ 몸통×2, 하락 후 | +2 |
| 상승 포선 | 전봉 음봉 몸통 ⊂ 당봉 양봉 몸통 | +2.5 |
| 모닝스타 | 긴음봉 → 작은몸통 → 긴양봉(전음봉 중위 돌파) | +3 |

몸통 색이 무관하다고 한 패턴(하라미류)은 색 조건 생략.

### 차트형

스윙 고저점(로컬 extrema) 기반으로 단순 휴리스틱:

**매수 가점**

- 쌍바닥: 두 저점 유사(±tol%) + 중간 고점 돌파
- 역머리어깨: 세 저점, 가운데가 가장 낮음 + 넥라인 돌파
- 상승깃발: 급등 폴 + 짧은 하락 채널 상단 돌파
- 상승삼각형: 수평 저항 + 높아지는 저점 + 저항 돌파

**매수 차단 (약세)**

- 쌍봉, 머리어깨, 하락깃발, 하락삼각형 (돌파/완성 시)

오탐을 줄이기 위해 윈도우·tolerance는 상수로 두고 config로만 조절. 확신 낮으면 가점만 주고 차단은 `notebook_pattern_block_bearish`로 off 가능.

## Scoring interaction

- 기존 max 점수 구조는 유지. 노트 가점은 `score`에 더하되 `notebook_max_bonus`로 캡.
- `chart_min_score`는 변경하지 않음 (필요 시 운영자가 config로 조정).
- `reasons`에 `골든크로스`, `장기MA상승`, `큰양선`, `쌍바닥` 등 한글 라벨 추가 → 텔레그램/저널에 그대로 노출.

## Testing

- `tests/test_notebook_patterns.py` (또는 기존 tests 구조에 맞춤): 합성 OHLC로 각 탐지기 true/false.
- MA gate: 상승/하락 기울기 fixture.
- `evaluate_chart_signals` 통합: enabled 시 gate 실패 → reject, 가점 반영.

## Rollout

1. `notebook_strategy_enabled=True` 기본, 차단·가점 모두 on.
2. 문제 시 config만으로 `False` 또는 `notebook_pattern_block_bearish=False`로 완화.
3. 2차(별도 스펙): 매도 신호, `basic` 모드, 100/200 MA, 고난도 도형.

## Self-review checklist

- [x] No unresolved placeholders
- [x] Consistent with Approach A (filter enhance, not replace)
- [x] Scope bounded; sell path untouched
- [x] Concrete files and config keys named
