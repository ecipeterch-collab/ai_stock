# Advise sells, notify-and-auto buys

Date: 2026-09-20  
Status: Draft (user locked: 재해 −5%만 자동 매도, 나머지 매도는 허용 시에만, 매수는 알림과 동시 자동)

## Goal

Stop rule-only sells from cutting swing names that later recover (삼화콘덴서 9/8 −2.5% 손절 후 9/11 +19%). Keep auto-buys. Every buy-phase cycle, tell the user the current candidate set — including cycles that do not place an order. Keep a hard floor so an unattended crash still exits.

## Decisions already locked

1. **Disaster auto sell:** `profit_pct <= -5.0` → market sell, no approval.
2. **All other sell signals** (중소형 −2.5% 손절, 대형 −4% 손절, 본전스탑, 트레일, 장마감, 오버나잇, 방어, 정체) → Telegram proposal. No tap → **no order** (expires). Overnight hold is allowed.
3. **Buys stay automatic.** Notify candidates **every buy-phase cycle**, whether or not an order is placed. If this cycle buys, the same message includes the order. Not a 90s wait, not an approve-to-buy gate.
4. Swing mode only. Scalping keep today’s auto buy and auto sell.

## In scope

1. **Sell gate in `_run_sell_phase`.** After `_evaluate_sell` + existing confirm/volume checks, branch:
   - `holding.profit_pct <= strategy_disaster_stop_pct` (−5.0) → `_execute_sell` as today (시장가 손절).
   - else if swing and `advise_sells_enabled` → create/update a proposal, **do not** call `_execute_sell`.
   - Scalping or flag off → `_execute_sell` as today.
2. **Proposal store** `data/trade_proposals.json`. One pending sell per `code`. Fields: `id`, `code`, `name`, `qty`, `reason`, `category` (`_exit_confirm_key` / 손절 / 장마감 / …), `profit_pct`, `price`, `ts`, `status` (`pending` | `held` | `done` | `ignored`). Day-scoped `held`: same code+category is not re-proposed until next session (`_reset_daily_counter`).
3. **Telegram sell message** with inline buttons `[매도] [보류] [무시]`. `send_message` gains optional `reply_markup`. Bot `getUpdates` handles `callback_query` (today it ignores non-message updates). Callback answers must be ≤64 bytes: `sell:ok:{id}`, `sell:hold:{id}`, `sell:no:{id}`.
   - **매도:** market/limit using the same `_execute_sell` / `_exit_uses_market` rules as auto, current sellable qty capped at proposed qty.
   - **보류:** status `held` for that code+category today. No further proposals of that category. Disaster still sells.
   - **무시:** status `ignored`. Same category may re-propose after `advise_sell_ignore_cooldown_min` (20).
   - Dedup: if a `pending` proposal exists for the same code+category, do not send another Telegram; refresh price/qty/reason in the file only.
4. **Text fallback** (웹 대시보드 명령과 동일): `/sellok 종목코드`, `/sellhold 종목코드`. No new web UI this round.
5. **Buy-candidate notify every cycle.** After the swing buy scan (same ranking/filters as today), always emit a candidate event:
   - If this cycle places an order: keep `【자동매수】` (or crash/trend tag) and append `이번 후보` (bought name marked, plus up to 2 other eligible names).
   - If this cycle does **not** buy: emit `【매수 후보】` with up to 3 eligible names (code, score) and a one-line skip reason (매수한도, 슬롯 가득, 점수 미달, 차단, 후보 없음, …).
   - Eligible empty → still send `【매수 후보】 없음` plus the skip/block reason so a quiet tape is visible.
   - Do not require a buy to send this. Do not collapse identical lists across cycles (user wants each cycle). Scalping: no extra candidate pings.
6. **Manual size guard.** `/buy` (텔레그램·웹) if `qty > position_max_qty` **or** `qty * last_price > position_target_krw * 3` → reject with “확인: `/buyok 코드 수량`”. `/buyok` places the order. Auto path unchanged (already uses target/max qty).
7. **Config** (example + server `config.py` when deploying): `advise_sells_enabled = True`, `strategy_disaster_stop_pct = 5.0`, `advise_sell_ignore_cooldown_min = 20`. Existing `strategy_other_stop_loss_pct = 2.5` and `strategy_stop_loss_pct = 4.0` stay as **signal** thresholds that now open a proposal, not an order.

## Out of scope

- Waiting one auto interval before buying.
- Approve-to-buy buttons.
- Changing chart-primary buy scoring, mega-cap list, or position_target_krw.
- Web dashboard proposal cards (text commands are enough).
- Paper vs real. OCI deploy unless asked after tests pass.
- Scalping advise mode.

## Data flow

```
run_cycle (swing, auto on)
  sell phase
    evaluate + confirm
    profit <= -5%  → execute market sell + 【자동매도】
    other signal   → upsert proposal + 【매도 제안】 (buttons)
    보류 today     → skip
  buy phase
    same ranking / filters as today
    always         → 【매수 후보】 1~3 (또는 없음 + 사유)
    on order       → same cycle 【자동매수】 + 이번 후보 + buy_market
                     (do not send a second candidate-only message)
```

Telegram callback / `/sellok` loads the pending proposal, re-reads holdings, executes `_execute_sell`, marks `done`. If sellable qty is 0, reply 매도 불가 and keep pending.

## Tests

- Swing, profit −2.57%, other stop −2.5% → no `sell_market`; proposal event; store pending.
- Swing, profit −5.01% → `sell_market` even if a pending proposal exists; no approval.
- `held` same-day −2.6% 손절 → no new proposal; −5.01% still sells.
- Duplicate cycle, same code+category pending → second cycle does not add another Telegram event.
- Ignore then 10 min later → no re-proposal; 21 min later → proposal allowed.
- `_execute_buy` event text contains `이번 후보` and still calls `buy_market`.
- Cycle with zero buys and 2 eligible names → `【매수 후보】` event (no `buy_market`); skip reason present.
- Cycle with zero eligible names → `【매수 후보】 없음` event; no `buy_market`.
- `/buy 001820 1000` rejected; `/buyok 001820 1000` would pass the guard (order itself may still fail at Kiwoom).
- Scalping −2.6% still auto-sells with `advise_sells_enabled` True.
- Callback `sell:ok:{id}` invokes execute path; missing id → 만료 안내.

## Telegram copy (sell)

```
【매도 제안】 삼화콘덴서(001820)
수익률 −2.57% · 112,064원 · 1,000주
사유: 손절 (−2.57% <= −2.5%)
재해 손절(−5%) 전엔 자동 매도하지 않습니다.
[매도] [보류] [무시]
```

Buy copy when an order fires keeps `【자동매수】` and appends:

```
이번 후보
1. 삼성SDI(006400) 16점 ← 매수
2. KB금융(105560) 18점
3. LG에너지솔루션(373220) 10점
```

When no order this cycle:

```
【매수 후보】
1. KB금융(105560) 18점
2. LG에너지솔루션(373220) 10점
매수 없음: 일일 매수한도 도달
```
