from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import requests

from config.config import (
    default_order_qty,
    position_sizing_enabled,
    position_target_krw,
    position_min_qty,
    position_max_qty,
    strategy_swing_breakeven_activate_pct,
    strategy_swing_breakeven_floor_pct,
    strategy_swing_protect_trailing_activate_pct,
    strategy_swing_protect_trailing_drawdown_pct,
    dmst_stex_tp,
    use_paper,
    fill_poll_interval_sec,
    fill_poll_wait_sec,
    daily_loss_stop_pct,
    hard_stop_loss_pct,
    top_volume_rank_n,
    news_defensive_loss_pct,
    news_enabled,
    news_override_allow_buy_sentiment_floor,
    news_override_min_bullish_ratio,
    news_override_when_market_bullish,
    news_override_disable_buy_block,
    news_override_disable_defensive_mode,
    news_override_max_risk_score,
    strategy_block_leveraged_etf,
    strategy_defensive_min_hold_minutes,
    strategy_defensive_trailing_min_peak_pct,
    strategy_weak_market_min_bullish_count,
    strategy_weak_market_sentiment,
    scalping_disable_trend_buy,
    scalping_circuit_consecutive_losses,
    scalping_circuit_cooldown_minutes,
    scalping_circuit_max_losses,
    scalping_circuit_recent_sells,
    scalping_circuit_stop_for_day_consecutive_losses,
    scalping_exit_limit_price_ticks,
    scalping_exit_use_limit_orders,
    scalping_max_flu_rt,
    scalping_max_hold_minutes,
    scalping_min_flu_rt,
    scalping_min_rank_improve,
    scalping_min_score,
    scalping_quick_profit_pct,
    scalping_reentry_cooldown_minutes,
    scalping_scan_rank_top,
    scalping_take_profit_pct,
    scalping_trend_max_buys_per_day,
    strategy_circuit_consecutive_losses,
    strategy_circuit_cooldown_minutes,
    strategy_circuit_max_losses,
    strategy_circuit_recent_sells,
    strategy_circuit_stop_for_day_consecutive_losses,
    strategy_crash_buy_enabled,
    strategy_crash_max_buys_per_day,
    strategy_crash_max_flu_rt,
    strategy_crash_max_news_risk,
    strategy_crash_max_rank,
    strategy_crash_min_flu_rt,
    strategy_crash_min_score,
    strategy_crash_reentry_cooldown_minutes,
    strategy_crash_scan_rank_top,
    strategy_exit_limit_price_ticks,
    strategy_exit_use_limit_orders,
    strategy_reentry_cooldown_minutes,
    strategy_swing_eod_sell_all,
    strategy_swing_eod_sell_if_below_pct,
    strategy_swing_take_profit_pct,
    strategy_swing_top_volume_tp1_pct,
    strategy_swing_top_volume_tp2_pct,
    strategy_swing_trailing_activate_pct,
    strategy_swing_trailing_drawdown_pct,
    strategy_trend_max_buys_per_day,
    strategy_breakeven_activate_pct,
    strategy_breakeven_floor_pct,
    strategy_eod_sell_enabled,
    strategy_min_flu_rt,
    strategy_max_flu_rt,
    strategy_min_score,
    strategy_partial_sell_ratio,
    strategy_position_sync_grace_minutes,
    strategy_scan_rank_top,
    strategy_stop_loss_pct,
    strategy_take_profit_partial_pct,
    strategy_take_profit_pct,
    strategy_trailing_activate_pct,
    strategy_trailing_drawdown_pct,
    trend_auto_buy_enabled,
)
from kiwoom.client import KiwoomAPIError, KiwoomClient
from trading.market_utils import (
    is_buy_window,
    is_market_open,
    market_status_text,
    parse_hhmm,
)
from trading.position_tracker import PositionState, PositionTracker
from trading.news_analyzer import MarketNewsAnalyzer, MarketNewsContext
from trading.scoring import (
    CandidateView,
    filter_and_rank_candidates,
    is_market_bullish,
    market_bullish_stats,
)
from trading.symbol_filters import is_leveraged_etf
from trading.runtime_config import (
    effective_auto_interval_sec,
    effective_buy_windows,
    effective_eod_times,
    effective_max_buys_per_day,
    effective_max_positions,
    effective_portfolio_heat,
    is_scalping_mode,
    mode_label,
)
from trading.crash_buy import (
    filter_crash_candidates,
    is_bear_market,
)
from trading.scalping import (
    evaluate_scalp_sell,
    filter_scalp_candidates,
    is_scalp_market_bullish,
)
from trading.trade_journal import TradeJournal
from trading.trend_scanner import TrendPick, TrendScanner

# 텔레그램 자동 알림 대상 (이벤트만)
EVENT_PREFIXES = (
    "【체결",
    "【자동매수",
    "【스캘핑 매수",
    "【트렌드 매수",
    "【급락 매수",
    "【자동매도",
    "【매수 실패",
    "【매도 실패",
    "【매도 불가",
    "【주문 접수",
    "【주문 실패",
)


def is_event_message(message: str) -> bool:
    return message.startswith(EVENT_PREFIXES)


@dataclass
class AutoRunResult:
    events: list[str] = field(default_factory=list)
    report: list[str] = field(default_factory=list)

    def add_event(self, message: str) -> None:
        if message:
            self.events.append(message)

    def add_report(self, message: str) -> None:
        if message:
            self.report.append(message)

    @property
    def messages(self) -> list[str]:
        return self.events + self.report


@dataclass
class HoldingView:
    code: str
    name: str
    qty: int
    sellable_qty: int
    profit_pct: float
    current_price: int
    purchase_price: int
    order_code: str
    raw: dict


class AutoTradingStrategy:
    """다중 점수 매수 + 분할익절/트레일링/본전스탑 + 뉴스·지정학 필터 (v3)."""

    def __init__(self, client: KiwoomClient) -> None:
        self.client = client
        self.enabled = False
        self._buy_count_date: date | None = None
        self._buy_count = 0
        self._trend_buy_count_date: date | None = None
        self._trend_buy_count = 0
        self._crash_buy_count_date: date | None = None
        self._crash_buy_count = 0
        self._seen_fill_keys: set[str] = set()
        self._buy_block_until: datetime | None = None
        self._stop_buy_for_day: bool = False
        self._circuit_reset_date: date | None = None
        self._breaker_alert_date: date | None = None
        self.positions = PositionTracker()
        self.news = MarketNewsAnalyzer()
        self.trends = TrendScanner(client)
        self.journal = TradeJournal()

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def reset_daily_buy_limits(self) -> None:
        """일일 매수 제한 카운터 수동 리셋 (텔레그램 명령용)."""
        today = date.today()
        self._buy_count_date = today
        self._buy_count = 0
        self._trend_buy_count_date = today
        self._trend_buy_count = 0
        self._crash_buy_count_date = today
        self._crash_buy_count = 0
        # 브레이커 상태도 수동 해제
        self._buy_block_until = None
        self._stop_buy_for_day = False
        self._circuit_reset_date = today
        self._breaker_alert_date = None

    def _reset_circuit_for_new_day(self) -> None:
        """새 거래일이면 연속손실 브레이커·당일 중지 플래그를 자동 해제."""
        today = date.today()
        if self._circuit_reset_date == today:
            return
        self._circuit_reset_date = today
        self._buy_block_until = None
        self._stop_buy_for_day = False
        self._breaker_alert_date = None

    def _alert_buy_block(self, result: AutoRunResult, message: str) -> None:
        """브레이커·일일손실 등 매수 중지 시 하루 1회 텔레그램 알림."""
        today = date.today()
        if self._breaker_alert_date == today:
            return
        self._breaker_alert_date = today
        result.add_event(f"【매수 중지】\n{message}")

    def _today_journal_events(self) -> list:
        """오늘 날짜의 저널 이벤트만 반환."""
        today = date.today().isoformat()
        return [e for e in self.journal.tail(2000) if e.ts.startswith(today)]

    def _today_sell_events(self) -> list:
        return [
            e
            for e in self._today_journal_events()
            if e.event == "sell_order" and e.profit_pct is not None
        ]

    def peek_buy_block_reasons(self) -> list[str]:
        """매수 차단 사유를 조회(상태 변경 없음). /report 진단용."""
        reasons: list[str] = []
        if self._stop_buy_for_day:
            reasons.append("당일 신규매수 중지 플래그 ON (/resetbuys 로 해제)")
        if self._buy_block_until and datetime.now() < self._buy_block_until:
            mins = int((self._buy_block_until - datetime.now()).total_seconds() / 60) + 1
            reasons.append(f"연속손실 브레이커 대기 중 ({mins}분 남음)")

        pnl_pct = self._compute_today_pnl_pct()
        if pnl_pct is not None and pnl_pct <= -float(daily_loss_stop_pct):
            reasons.append(
                f"일일 손실 상한 ({pnl_pct:.2f}% ≤ -{daily_loss_stop_pct:.1f}%)"
            )

        sells = self._today_sell_events()
        if sells:
            circuit = self._circuit_thresholds()
            recent_n = max(1, int(circuit["recent_n"]))
            recent = sells[-recent_n:]
            losses = [e for e in recent if (e.profit_pct or 0.0) < 0]
            consec = self._consecutive_loss_count(sells)
            stop_for_day_n = max(1, int(circuit["stop_for_day_n"]))
            max_losses = max(1, int(circuit["max_losses"]))
            consec_th = max(1, int(circuit["consec_th"]))
            if consec >= stop_for_day_n:
                reasons.append(
                    f"오늘 연속 손실 {consec}회 (당일 중지 기준 {stop_for_day_n}회)"
                )
            elif len(losses) >= max_losses:
                reasons.append(
                    f"오늘 최근 {len(recent)}매도 중 손실 {len(losses)}회 (기준 {max_losses}회)"
                )
            elif consec >= consec_th:
                reasons.append(
                    f"오늘 연속 손실 {consec}회 (기준 {consec_th}회 → {circuit['cooldown']}분 중지)"
                )

        if not self._can_buy_today():
            reasons.append(
                f"일반 매수 횟수 한도 ({self._buy_count}/{effective_max_buys_per_day()}회)"
            )
        if not is_scalping_mode() and not self._can_trend_buy_today():
            reasons.append(
                f"트렌드 매수 횟수 한도 "
                f"({self._trend_buy_count}/{strategy_trend_max_buys_per_day}회)"
            )

        return reasons

    def _format_buy_status(self) -> str:
        """매수 가능 여부 요약."""
        self._reset_daily_counter()
        reasons = self.peek_buy_block_reasons()
        pnl_pct = self._compute_today_pnl_pct()
        lines = ["【매수 상태】"]
        if pnl_pct is not None:
            lines.append(f"오늘 누적 손익률(근사): {pnl_pct:+.2f}%")
        else:
            lines.append("오늘 누적 손익률(근사): 거래 없음")
        if reasons:
            lines.append("신규매수: 중지")
            for r in reasons:
                lines.append(f"  · {r}")
        else:
            lines.append("신규매수: 가능")
        if is_scalping_mode() and scalping_disable_trend_buy:
            lines.append("참고: 트렌드 자동매수 OFF (/trendbuy 로 수동 가능)")
        elif trend_auto_buy_enabled:
            max_trend = (
                scalping_trend_max_buys_per_day
                if is_scalping_mode()
                else strategy_trend_max_buys_per_day
            )
            lines.append(f"참고: 트렌드 자동매수 ON (일 {max_trend}회)")
        if not is_scalping_mode() and strategy_crash_buy_enabled:
            lines.append(
                f"참고: 급락 우량주 매수 ON (일 {self._crash_buy_count}/"
                f"{strategy_crash_max_buys_per_day}회, 하락장 전용)"
            )
        return "\n".join(lines)

    def _compute_today_pnl_pct(self) -> float | None:
        """오늘 매매 기준 누적 손익률(%) 근사."""
        events = self._today_journal_events()
        if not events:
            return None

        buys_by_code: dict[str, list[tuple[int, int]]] = {}
        invested = 0
        for e in events:
            if e.event not in ("buy_order", "trend_buy_order", "crash_buy_order"):
                continue
            qty = int(e.qty or 0)
            price = int(e.price or 0)
            if qty <= 0 or price <= 0:
                continue
            notional = qty * price
            invested += notional
            buys_by_code.setdefault(e.code, []).append((qty, price))

        if invested <= 0:
            return None

        pnl_amount = 0.0
        for e in events:
            if e.event != "sell_order" or e.profit_pct is None:
                continue
            q = int(e.qty or 0)
            if q <= 0:
                continue
            queue = buys_by_code.get(e.code) or []
            if not queue:
                continue
            remain = q
            while remain > 0 and queue:
                bq, bp = queue[0]
                take = min(remain, bq)
                pnl_amount += (take * bp) * (float(e.profit_pct) / 100.0)
                remain -= take
                if take == bq:
                    queue.pop(0)
                else:
                    queue[0] = (bq - take, bp)
            buys_by_code[e.code] = queue

        return (pnl_amount / invested) * 100.0

    def _daily_loss_blocks_buy(self) -> str | None:
        """일일 누적 손익률이 임계값 이하이면 당일 신규매수 중지.

        계산 방식(보수적/간단):
        - 오늘 매수(buy_order/trend_buy_order)의 '투입 금액' 합계를 분모로 사용
        - 오늘 매도(sell_order)의 profit_pct를 각 진입 투입금에 곱해 손익(원)을 근사
        - 누적 손익률 = 누적손익 / 누적투입금 * 100
        """
        try:
            limit = float(daily_loss_stop_pct)
        except Exception:
            return None
        if limit <= 0:
            return None

        # 이미 당일 중지 상태면 즉시 차단
        if self._stop_buy_for_day:
            return f"일일 손실 상한 도달(-{limit:.1f}%) - 당일 신규매수 중지"

        pnl_pct = self._compute_today_pnl_pct()
        if pnl_pct is None:
            return None
        if pnl_pct <= -limit:
            self._stop_buy_for_day = True
            return f"일일 손실 상한 도달 ({pnl_pct:.2f}% ≤ -{limit:.1f}%) - 당일 신규매수 중지"
        return None

    @staticmethod
    def _calc_order_qty(price: int) -> int:
        """종목당 목표 금액 기준 주문 수량. 비활성/가격 0이면 기본 수량."""
        if not position_sizing_enabled or not price or price <= 0:
            return max(1, int(default_order_qty))
        target = max(0, int(position_target_krw))
        if target <= 0:
            return max(1, int(default_order_qty))
        qty = target // int(price)
        qty = max(int(position_min_qty), int(qty))
        qty = min(int(position_max_qty), qty)
        return max(1, qty)

    @staticmethod
    def _krx_tick_size(price: int) -> int:
        """단순 호가단위 추정 (슬리피지 완화용)."""
        p = abs(int(price))
        if p < 2_000:
            return 1
        if p < 5_000:
            return 5
        if p < 20_000:
            return 10
        if p < 50_000:
            return 50
        if p < 200_000:
            return 100
        if p < 500_000:
            return 500
        return 1_000

    def _exit_limit_price(self, holding: HoldingView) -> int | None:
        """청산 시 보수적 지정가(매도) 가격."""
        use_limit = (
            scalping_exit_use_limit_orders
            if is_scalping_mode()
            else strategy_exit_use_limit_orders
        )
        if not use_limit or holding.current_price <= 0:
            return None
        ticks = max(
            0,
            int(
                scalping_exit_limit_price_ticks
                if is_scalping_mode()
                else strategy_exit_limit_price_ticks
            ),
        )
        tick = self._krx_tick_size(holding.current_price)
        return max(tick, holding.current_price - tick * ticks)

    def _scalping_exit_limit_price(self, holding: HoldingView) -> int | None:
        return self._exit_limit_price(holding)

    def _loss_circuit_blocks_buy(self) -> str | None:
        """연속 손실/최근 손실 과다 시 신규매수를 일시/당일 중지."""
        if self._stop_buy_for_day:
            return "연속 손실로 당일 자동매수 중지"

        now = datetime.now()
        if self._buy_block_until and now < self._buy_block_until:
            mins = int((self._buy_block_until - now).total_seconds() / 60) + 1
            return f"연속 손실 브레이커 - {mins}분 대기"

        sells = self._today_sell_events()
        if not sells:
            return None

        circuit = self._circuit_thresholds()
        recent_n = max(1, int(circuit["recent_n"]))
        recent = sells[-recent_n:]
        losses = [e for e in recent if (e.profit_pct or 0.0) < 0]
        consec = self._consecutive_loss_count(sells)

        stop_for_day_n = max(1, int(circuit["stop_for_day_n"]))
        if consec >= stop_for_day_n:
            self._stop_buy_for_day = True
            return f"연속 손실 {consec}회 - 당일 자동매수 중지"

        max_losses = max(1, int(circuit["max_losses"]))
        consec_th = max(1, int(circuit["consec_th"]))
        if len(losses) >= max_losses or consec >= consec_th:
            cool = max(1, int(circuit["cooldown"]))
            self._buy_block_until = now + timedelta(minutes=cool)
            return (
                f"연속 손실 브레이커 - 최근 {len(recent)}회 중 손실 {len(losses)}회"
                f" / 연속손실 {consec}회 → {cool}분 중지"
            )
        return None

    def get_rules_summary(self) -> str:
        if is_scalping_mode():
            ms, me, as_, ae = effective_buy_windows()
            cut, eod = effective_eod_times()
            return (
                "【스캘핑 전략】\n\n"
                f"점검 주기: {effective_auto_interval_sec()}초\n"
                f"동시 보유: 최대 {effective_max_positions()}종목\n"
                f"일일 매수: 최대 {effective_max_buys_per_day()}회\n\n"
                "■ 매도 (보유 우선)\n"
                "  · 수익실현: +10% 시 50% 매도\n"
                "    - 상위거래량 종목: +15% 50% 매도, +20% 총 80% 매도\n"
                f"  · 손절: -{hard_stop_loss_pct}% (고정)\n"
                f"  · 보유 {scalping_max_hold_minutes}분 초과 시 전량 청산\n"
                f"  · 트레일링·모멘텀 둔화·장마감 {eod} 청산\n\n"
                "■ 매수\n"
                f"  · 거래대금 상위 {scalping_scan_rank_top} · 점수 ≥{scalping_min_score}\n"
                f"  · 등락 {scalping_min_flu_rt}~{scalping_max_flu_rt}% · 순위급등 ≥{scalping_min_rank_improve}\n"
                f"  · 시간: {ms}~{me}, {as_}~{ae}\n\n"
                "■ 모드 전환: /mode swing | /mode scalping\n"
                f"■ 상위거래량 판정: 거래대금 상위 {top_volume_rank_n}\n"
                "■ /auto on · /report"
            )
        ms, me, as_, ae = effective_buy_windows()
        cut, eod = effective_eod_times()
        return (
            f"【매매 전략 · {mode_label()}】\n\n"
            f"점검 주기: {effective_auto_interval_sec()}초\n"
            f"동시 보유: 최대 {effective_max_positions()}종목\n"
            f"일반 매수: 최대 {effective_max_buys_per_day()}회/일 · "
            f"트렌드: {strategy_trend_max_buys_per_day}회/일\n\n"
            "■ 매도\n"
            f"  · 익절: +{strategy_swing_take_profit_pct}% "
            "(1주=전량, 2주+=50%)\n"
            f"  · 상위거래량: +{strategy_swing_top_volume_tp1_pct}% 50%, "
            f"+{strategy_swing_top_volume_tp2_pct}% 총 80%\n"
            f"  · 부분익절 후 트레일링: 고점 +{strategy_swing_trailing_activate_pct}% "
            f"→ -{strategy_swing_trailing_drawdown_pct}%p\n"
            f"  · 손절: -{strategy_stop_loss_pct}% · 청산: "
            f"{'지정가' if strategy_exit_use_limit_orders else '시장가'}\n"
            f"  · 장마감: {cut} 손실 정리"
            + (
                f" · {eod} 전량"
                if strategy_swing_eod_sell_all
                else (
                    f" · {eod} +{strategy_swing_eod_sell_if_below_pct:.0f}% 미만 청산"
                    if strategy_swing_eod_sell_if_below_pct > 0
                    else f" · 수익 종목 익절(+{strategy_swing_take_profit_pct:.0f}%)까지 보유"
                )
            )
            + "\n\n"
            "■ 매수 (눌림·완만상승)\n"
            f"  · 거래대금 상위 {strategy_scan_rank_top} · 점수 ≥{strategy_min_score}\n"
            f"  · 등락 {strategy_min_flu_rt}~{strategy_max_flu_rt}%\n"
            f"  · 재진입 쿨다운 {strategy_reentry_cooldown_minutes}분\n"
            f"  · 시간: {ms}~{me}, {as_}~{ae}\n\n"
            "■ 트렌드: 핫테마 연관 눌림목\n"
            + (
                f"■ 급락 우량주: 하락장 · 상위 {strategy_crash_max_rank}위 · "
                f"{strategy_crash_min_flu_rt}~{strategy_crash_max_flu_rt}% · "
                f"일 {strategy_crash_max_buys_per_day}회\n"
                if strategy_crash_buy_enabled
                else ""
            )
            + "■ 연속손실 브레이커: 3회→60분 / 5회→당일중지\n"
            "■ /mode swing|scalping · /auto on · /report"
        )

    def get_news_briefing(self) -> str:
        return self.news.get_context().summary_message()

    def get_trend_report(self) -> str:
        return self.trends.scan().format_intro()

    def trend_buy_best(self) -> str:
        """트렌드 1위 종목 매수 (수동 /trend buy)."""
        scan = self.trends.scan(force_refresh=True)
        intro = scan.format_intro()
        if not scan.picks:
            return intro + "\n\n매수할 트렌드 종목이 없습니다."

        if not self._can_buy_today():
            return intro + f"\n\n일일 매수 한도 도달 ({effective_max_buys_per_day()}회)"

        pick = scan.picks[0]
        internal = AutoRunResult()
        self._execute_trend_buy(pick, internal)
        extra = "\n".join(internal.events) if internal.events else "주문 처리 완료"
        return intro + "\n\n" + extra

    def build_manual_report(self) -> str:
        """수동 /report 용 전체 리포트."""
        lines = [
            self.get_news_briefing(),
            self.get_trend_report(),
        ]
        try:
            holdings = self._parse_holdings()
            lines.append(self._portfolio_summary(holdings, 0))
        except (KiwoomAPIError, requests.RequestException) as exc:
            lines.append(f"잔고 조회 실패: {exc}")
        lines.append(self.journal.format_recent_summary(10))
        lines.append(self._format_buy_status())
        lines.append(
            self._heartbeat(
                "수동 리포트",
                f"자동매매 {'ON' if self.enabled else 'OFF'}",
            )
        )
        return "\n\n".join(lines)

    def build_account_status(self) -> str:
        """예수금·자동매매 상태 (/status)."""
        fmt = self.client.format_amount
        trade_mode = "모의투자" if use_paper else "실전투자"
        try:
            deposit = self.client.get_deposit()
            account = (
                "【계좌】\n"
                f"예수금: {fmt(deposit.get('entr', '0'))}원\n"
                f"주문가능: {fmt(deposit.get('ord_alow_amt', '0'))}원\n"
                f"출금가능: {fmt(deposit.get('pymn_alow_amt', '0'))}원"
            )
        except (KiwoomAPIError, requests.RequestException) as exc:
            account = f"【계좌】\n조회 실패: {exc}"

        self._reset_daily_counter()
        return (
            f"【계좌 상태】 {trade_mode} · {mode_label()}\n"
            f"시각: {datetime.now():%Y-%m-%d %H:%M:%S} · 장: {market_status_text()}\n"
            f"자동매매: {'ON' if self.enabled else 'OFF'} · "
            f"일반매수 {self._buy_count}/{effective_max_buys_per_day()}회\n\n"
            f"{account}\n\n"
            "상세 보유: /balance 또는 /portfolio"
        )

    def build_balance_detail(self) -> str:
        """보유 종목 상세 (/balance)."""
        try:
            holdings = self._parse_holdings()
            return self._portfolio_summary(holdings, 0)
        except (KiwoomAPIError, requests.RequestException) as exc:
            return f"【보유 종목】\n조회 실패: {exc}"

    def build_account_dashboard(self) -> str:
        """계좌·보유·매수 상태·최근 체결 (/portfolio)."""
        trade_mode = "모의투자" if use_paper else "실전투자"
        header = (
            f"【계좌·보유 현황】 {trade_mode} · {mode_label()}\n"
            f"시각: {datetime.now():%Y-%m-%d %H:%M:%S} · 장: {market_status_text()}\n"
            f"자동매매: {'ON' if self.enabled else 'OFF'}"
        )
        sections = [header]

        fmt = self.client.format_amount
        try:
            deposit = self.client.get_deposit()
            sections.append(
                "【예수금】\n"
                f"예수금: {fmt(deposit.get('entr', '0'))}원\n"
                f"주문가능: {fmt(deposit.get('ord_alow_amt', '0'))}원\n"
                f"출금가능: {fmt(deposit.get('pymn_alow_amt', '0'))}원"
            )
        except (KiwoomAPIError, requests.RequestException) as exc:
            sections.append(f"【예수금】\n조회 실패: {exc}")

        try:
            holdings = self._parse_holdings()
            sections.append(self._portfolio_summary(holdings, 0))
        except (KiwoomAPIError, requests.RequestException) as exc:
            sections.append(f"【보유 종목】\n조회 실패: {exc}")

        sections.append(self._format_buy_status())
        sections.append(self.journal.format_recent_summary(5))
        return "\n\n".join(sections)

    def _reset_daily_counter(self) -> None:
        self._reset_circuit_for_new_day()
        today = date.today()
        if self._buy_count_date != today:
            self._buy_count_date = today
            self._buy_count = 0
        if self._trend_buy_count_date != today:
            self._trend_buy_count_date = today
            self._trend_buy_count = 0
        if self._crash_buy_count_date != today:
            self._crash_buy_count_date = today
            self._crash_buy_count = 0

    def _can_buy_today(self) -> bool:
        self._reset_daily_counter()
        return self._buy_count < effective_max_buys_per_day()

    def _record_buy(self) -> None:
        self._reset_daily_counter()
        self._buy_count += 1

    def _record_trend_buy(self) -> None:
        self._reset_daily_counter()
        self._trend_buy_count += 1

    def _can_trend_buy_today(self) -> bool:
        self._reset_daily_counter()
        if is_scalping_mode():
            return self._trend_buy_count < scalping_trend_max_buys_per_day
        return self._trend_buy_count < strategy_trend_max_buys_per_day

    def _can_crash_buy_today(self) -> bool:
        self._reset_daily_counter()
        return self._crash_buy_count < strategy_crash_max_buys_per_day

    def _record_crash_buy(self) -> None:
        self._reset_daily_counter()
        self._crash_buy_count += 1

    @staticmethod
    def _consecutive_loss_count(sells: list) -> int:
        consec = 0
        for e in reversed(sells):
            if e.profit_pct is not None and e.profit_pct < 0:
                consec += 1
            else:
                break
        return consec

    def _circuit_thresholds(self) -> dict[str, int]:
        if is_scalping_mode():
            return {
                "recent_n": scalping_circuit_recent_sells,
                "max_losses": scalping_circuit_max_losses,
                "consec_th": scalping_circuit_consecutive_losses,
                "cooldown": scalping_circuit_cooldown_minutes,
                "stop_for_day_n": scalping_circuit_stop_for_day_consecutive_losses,
            }
        return {
            "recent_n": strategy_circuit_recent_sells,
            "max_losses": strategy_circuit_max_losses,
            "consec_th": strategy_circuit_consecutive_losses,
            "cooldown": strategy_circuit_cooldown_minutes,
            "stop_for_day_n": strategy_circuit_stop_for_day_consecutive_losses,
        }

    @staticmethod
    def _calc_stage_sell_qty(
        entry_qty: int,
        sellable: int,
        already_sold: int,
        target_ratio: float,
    ) -> int:
        """부분 익절 수량. 1주는 목표 도달 시 전량."""
        if sellable <= 0 or target_ratio <= 0:
            return 0
        if entry_qty <= 0:
            entry_qty = sellable + already_sold
        if entry_qty <= 1:
            return sellable
        target_total = min(entry_qty, math.ceil(entry_qty * target_ratio))
        need = max(0, target_total - already_sold)
        return min(need, sellable)

    @staticmethod
    def _fill_key(fill: dict) -> str:
        return "|".join(
            [
                fill.get("ord_no", ""),
                fill.get("stk_cd", ""),
                fill.get("cntr_pric", ""),
                fill.get("cntr_qty", ""),
                fill.get("ord_tm", ""),
            ]
        )

    def _format_fill_message(self, fill: dict) -> str:
        code = self.client.normalize_stock_code(fill.get("stk_cd", ""))
        name = fill.get("stk_nm", code)
        price = self.client.format_amount(fill.get("cntr_pric", "0"))
        qty = fill.get("cntr_qty", "0")
        return (
            "【체결 알림】\n"
            f"종목: {name}({code})\n"
            f"구분: {fill.get('io_tp_nm', fill.get('trde_tp', ''))}\n"
            f"체결가: {price}원 · {qty}주\n"
            f"주문번호: {fill.get('ord_no', '')}"
        )

    def _journal_fill(self, fill: dict) -> None:
        """체결 내역을 저널에 기록 (매수·매도 공통)."""
        try:
            code = self.client.normalize_stock_code(fill.get("stk_cd", ""))
            name = fill.get("stk_nm", code)
            qty = self.client.parse_qty(fill.get("cntr_qty", "0"))
            price = self.client.parse_price(fill.get("cntr_pric", "0"))
            self.journal.log(
                "fill",
                code=code,
                name=name,
                qty=qty if qty > 0 else None,
                price=price if price > 0 else None,
                ord_no=str(fill.get("ord_no", "")),
            )
        except Exception:
            pass

    def _position_sync_grace_minutes(self) -> int:
        return max(0, int(strategy_position_sync_grace_minutes))

    def _should_suppress_holding_sync(self, code: str) -> bool:
        """청산 직후 API 잔고 지연으로 포지션이 재생성되는 것을 방지."""
        since = self.positions.cooldown_minutes_since_exit(code)
        if since is None:
            return False
        return since < float(self._position_sync_grace_minutes())

    def _collect_new_fills(self, result: AutoRunResult) -> None:
        try:
            fills = self.client.get_executions()
        except (KiwoomAPIError, requests.RequestException) as exc:
            result.add_event(f"체결 조회 실패: {exc}")
            return
        for fill in fills:
            key = self._fill_key(fill)
            if key in self._seen_fill_keys:
                continue
            if not fill.get("cntr_qty") or fill.get("cntr_qty") == "0":
                continue
            self._seen_fill_keys.add(key)
            result.add_event(self._format_fill_message(fill))
            self._journal_fill(fill)

    def _parse_holdings(self) -> list[HoldingView]:
        holdings: list[HoldingView] = []
        for item in self.client.get_holdings():
            raw_code = item.get("stk_cd", "")
            code = self.client.normalize_stock_code(raw_code)
            if not code:
                continue
            qty = self.client.parse_qty(item.get("rmnd_qty", "0"))
            sellable = self.client.parse_qty(item.get("trde_able_qty", "0"))
            if qty <= 0 and sellable <= 0:
                continue
            if self._should_suppress_holding_sync(code):
                continue
            profit = self.client.parse_percent(item.get("prft_rt", "0"))
            purchase = self.client.parse_price(item.get("pur_pric", "0"))
            name = item.get("stk_nm", code)
            self.positions.sync_holding(code, name, purchase, profit)
            holdings.append(
                HoldingView(
                    code=code,
                    name=name,
                    qty=qty,
                    sellable_qty=sellable,
                    profit_pct=profit,
                    current_price=self.client.parse_price(item.get("cur_prc", "0")),
                    purchase_price=purchase,
                    order_code=code,
                    raw=item,
                )
            )
        tracked = self.positions.codes()
        held_codes = {h.code for h in holdings}
        for code in list(tracked):
            if code not in held_codes:
                self.positions.remove(code)
            elif self._should_suppress_holding_sync(code):
                self.positions.remove(code)
        return holdings

    def _parse_candidates(self, rank_items: list[dict]) -> list[CandidateView]:
        candidates: list[CandidateView] = []
        for item in rank_items:
            code = self.client.normalize_stock_code(item.get("stk_cd", ""))
            if not code:
                continue
            try:
                rank = int(item.get("now_rank", "999"))
                prev_rank = int(item.get("pred_rank", "999"))
            except ValueError:
                rank, prev_rank = 999, 999
            candidates.append(
                CandidateView(
                    code=code,
                    name=item.get("stk_nm", code),
                    rank=rank,
                    prev_rank=prev_rank,
                    flu_rt=self.client.parse_percent(item.get("flu_rt", "0")),
                    current_price=self.client.parse_price(item.get("cur_prc", "0")),
                    trade_value=item.get("trde_prica", ""),
                    raw=item,
                )
            )
        return candidates

    def _is_eod_cut_loss_time(self, now: datetime | None = None) -> bool:
        if not strategy_eod_sell_enabled:
            return False
        cut, _ = effective_eod_times()
        return (now or datetime.now()).time() >= parse_hhmm(cut)

    def _is_eod_sell_all_time(self, now: datetime | None = None) -> bool:
        if not strategy_eod_sell_enabled:
            return False
        _, eod = effective_eod_times()
        return (now or datetime.now()).time() >= parse_hhmm(eod)

    def _evaluate_sell(
        self,
        holding: HoldingView,
        state: PositionState | None,
        news: MarketNewsContext | None = None,
        *,
        is_top_volume: bool = False,
    ) -> tuple[str | None, int, int | None]:
        profit = holding.profit_pct
        sellable = holding.sellable_qty
        if sellable <= 0:
            return None, 0, None

        # 수익 실현(부분매도) 규칙
        # - 일반: +10%에서 50% 매도
        # - 상위 거래량(거래대금) 종목: +15%에서 50%, +20%에서 총 80%까지 매도
        entry_qty = getattr(state, "entry_qty", 0) if state else 0
        if entry_qty <= 0:
            entry_qty = holding.qty
        already_sold = max(0, entry_qty - holding.qty)
        stage_done = getattr(state, "tp_stage", 0) if state else 0

        if is_top_volume:
            if stage_done < 1 and profit >= strategy_swing_top_volume_tp1_pct:
                qty = self._calc_stage_sell_qty(
                    entry_qty, sellable, already_sold, 0.50
                )
                if qty > 0:
                    return (
                        f"수익실현(상위거래량) +{strategy_swing_top_volume_tp1_pct:.0f}% "
                        f"{'전량' if entry_qty <= 1 else '50%'} 매도",
                        qty,
                        1,
                    )
            if stage_done < 2 and profit >= strategy_swing_top_volume_tp2_pct:
                qty = self._calc_stage_sell_qty(
                    entry_qty, sellable, already_sold, 0.80
                )
                if qty > 0:
                    return (
                        f"수익실현(상위거래량) +{strategy_swing_top_volume_tp2_pct:.0f}% "
                        f"{'전량' if entry_qty <= 1 else '총 80%'} 매도",
                        qty,
                        2,
                    )
        elif stage_done < 1 and profit >= strategy_swing_take_profit_pct:
            qty = self._calc_stage_sell_qty(entry_qty, sellable, already_sold, 0.50)
            if qty > 0:
                label = (
                    "전량"
                    if entry_qty <= 1
                    else f"{int(strategy_partial_sell_ratio * 100)}%"
                )
                return (
                    f"수익실현 +{strategy_swing_take_profit_pct:.0f}% {label} 매도",
                    qty,
                    1,
                )

        if is_scalping_mode():
            hold_min = self.positions.holding_minutes(holding.code)
            reason, qty = evaluate_scalp_sell(
                profit,
                sellable,
                state,
                hold_min,
                is_eod_sell_all=self._is_eod_sell_all_time(),
                is_eod_cut_loss=self._is_eod_cut_loss_time(),
            )
            return reason, qty, None

        qty = sellable
        peak = state.peak_profit_pct if state else profit

        if self._is_eod_sell_all_time():
            _, eod = effective_eod_times()
            if is_scalping_mode() or strategy_swing_eod_sell_all:
                return f"장마감 전량 청산 ({eod})", qty, None
            below = float(strategy_swing_eod_sell_if_below_pct)
            if below > 0 and profit < below:
                return (
                    f"장마감 익절미달 정리 ({profit:.2f}% < +{below:.1f}%, {eod})",
                    qty,
                    None,
                )

        if self._is_eod_cut_loss_time() and profit < 0:
            cut, _ = effective_eod_times()
            return f"장마감 손실 정리 ({cut})", qty, None

        if profit <= -strategy_stop_loss_pct:
            return f"손절 ({profit:.2f}% <= -{strategy_stop_loss_pct}%)", qty, None

        # 부분 익절 후에만 트레일링 (조기 청산 방지)
        if stage_done >= 1 and peak >= strategy_swing_trailing_activate_pct:
            trail_floor = peak - strategy_swing_trailing_drawdown_pct
            if profit < trail_floor:
                return (
                    f"트레일링 스탑 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                    qty,
                    None,
                )

        # 수익 보호: 1주 포지션 포함 모든 보유에 적용 (부분익절 게이트 없음)
        # 1) 일반 트레일링 — 고점이 충분히 높으면 되돌림 시 청산
        if peak >= strategy_swing_protect_trailing_activate_pct:
            protect_floor = peak - strategy_swing_protect_trailing_drawdown_pct
            if profit < protect_floor:
                return (
                    f"수익보호 트레일링 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                    qty,
                    None,
                )
        # 2) 본전스탑 — 한 번 +N% 갔다가 본전 부근으로 되돌아오면 소소익/본전 청산
        if peak >= strategy_swing_breakeven_activate_pct and (
            profit < strategy_swing_breakeven_floor_pct
        ):
            return (
                f"본전스탑 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                qty,
                None,
            )

        if news and news.defensive_mode:
            hold_min = self.positions.holding_minutes(holding.code)
            min_def_hold = (
                0
                if is_scalping_mode()
                else max(0, int(strategy_defensive_min_hold_minutes))
            )
            in_grace = (
                min_def_hold > 0
                and hold_min is not None
                and hold_min < min_def_hold
            )
            if not in_grace:
                if profit <= news_defensive_loss_pct:
                    return (
                        f"방어모드 매도 (뉴스 악화, 수익 {profit:.2f}%)",
                        qty,
                        None,
                    )
                trail_peak = (
                    1.0
                    if is_scalping_mode()
                    else max(1.0, float(strategy_defensive_trailing_min_peak_pct))
                )
                if peak >= trail_peak and profit < peak - 0.8:
                    return (
                        f"방어모드 트레일링 (리스크 {news.risk_score:.2f})",
                        qty,
                        None,
                    )

        return None, 0, None

    def _execute_sell(
        self,
        holding: HoldingView,
        reason: str,
        sell_qty: int,
        result: AutoRunResult,
        *,
        partial: bool = False,
        tp_stage: int | None = None,
    ) -> bool:
        sell_qty = min(sell_qty, holding.sellable_qty)
        order_code = self.client.normalize_stock_code(
            holding.order_code or holding.code
        )
        if sell_qty <= 0:
            result.add_event(
                "【매도 불가】\n"
                f"종목: {holding.name}({holding.code})\n"
                f"사유: {reason}\n"
                f"매매가능수량 0주 (결제·미체결 대기 가능)"
            )
            return False

        try:
            limit_price = self._exit_limit_price(holding)

            if limit_price:
                order = self.client.sell_limit(
                    order_code,
                    sell_qty,
                    limit_price,
                    dmst_stex_tp=dmst_stex_tp,
                )
            else:
                order = self.client.sell_market(
                    order_code,
                    sell_qty,
                    dmst_stex_tp=dmst_stex_tp,
                )
            ord_no = order.get("ord_no", "")
            try:
                self.journal.log(
                    "sell_order",
                    code=holding.code,
                    name=holding.name,
                    qty=sell_qty,
                    price=holding.current_price or None,
                    profit_pct=holding.profit_pct,
                    reason=reason + (f" / 지정가 {limit_price}" if limit_price else ""),
                    ord_no=ord_no,
                )
            except Exception:
                pass
            result.add_event(
                "【자동매도】\n"
                f"사유: {reason}\n"
                f"종목: {holding.name}({holding.code})\n"
                f"수량: {sell_qty}주 / 매매가능 {holding.sellable_qty}주\n"
                f"수익률: {holding.profit_pct:+.2f}%\n"
                f"주문: {'지정가' if limit_price else '시장가'}\n"
                f"주문번호: {ord_no}\n"
                f"{order.get('return_msg', '')}"
            )
            fill_msg = self.check_order_fill(
                ord_no,
                order_code,
                sell_tp="1",
                stk_nm=holding.name,
            )
            if fill_msg:
                if is_event_message(fill_msg):
                    result.add_event(fill_msg)
                else:
                    result.add_report(fill_msg)
            if partial:
                self.positions.mark_partial_sold(holding.code)
            if tp_stage is not None:
                self.positions.mark_tp_stage(holding.code, tp_stage)
            if sell_qty >= holding.sellable_qty:
                self.positions.mark_exit(holding.code)
                self.positions.remove(holding.code)
            return True
        except KiwoomAPIError as exc:
            use_limit = (
                scalping_exit_use_limit_orders
                if is_scalping_mode()
                else strategy_exit_use_limit_orders
            )
            if use_limit:
                # 지정가 청산 실패 시 시장가로 한 번 더 시도 (청산 실패 방지)
                try:
                    order = self.client.sell_market(
                        order_code,
                        sell_qty,
                        dmst_stex_tp=dmst_stex_tp,
                    )
                    ord_no = order.get("ord_no", "")
                    result.add_event(
                        "【자동매도(대체)】\n"
                        "지정가 실패 → 시장가 재시도\n"
                        f"종목: {holding.name}({holding.code})\n"
                        f"수량: {sell_qty}주\n"
                        f"주문번호: {ord_no}\n"
                        f"{order.get('return_msg', '')}"
                    )
                    fill_msg = self.check_order_fill(
                        ord_no,
                        order_code,
                        sell_tp="1",
                        stk_nm=holding.name,
                    )
                    if fill_msg:
                        if is_event_message(fill_msg):
                            result.add_event(fill_msg)
                        else:
                            result.add_report(fill_msg)
                    if sell_qty >= holding.sellable_qty:
                        self.positions.mark_exit(holding.code)
                        self.positions.remove(holding.code)
                    return True
                except Exception:
                    pass
            try:
                self.journal.log(
                    "sell_fail",
                    code=order_code,
                    name=holding.name,
                    qty=sell_qty,
                    price=holding.current_price or None,
                    profit_pct=holding.profit_pct,
                    reason=reason,
                    ord_no="",
                )
            except Exception:
                pass
            result.add_event(
                "【매도 실패】\n"
                f"종목: {holding.name}({order_code})\n"
                f"수량: {sell_qty}주\n"
                f"사유: {reason}\n"
                f"오류: {exc}"
            )
            return False
        except requests.RequestException as exc:
            result.add_event(
                f"【매도 실패】 {holding.name}({holding.code})\n네트워크: {exc}"
            )
            return False

    def _run_sell_phase(
        self,
        result: AutoRunResult,
        news: MarketNewsContext | None = None,
    ) -> int:
        sold_count = 0
        try:
            holdings = self._parse_holdings()
        except (KiwoomAPIError, requests.RequestException) as exc:
            result.add_event(f"잔고 조회 실패(매도): {exc}")
            return 0

        top_volume_codes: set[str] = set()
        if holdings:
            try:
                rank_items = self.client.get_trade_value_rank(
                    top_n=max(1, int(top_volume_rank_n))
                )
                top_volume_codes = {self.client.normalize_stock_code(i.get("stk_cd", "")) for i in rank_items}
            except Exception:
                top_volume_codes = set()

        for holding in holdings:
            state = self.positions.get(holding.code)
            is_top_volume = holding.code in top_volume_codes
            reason, sell_qty, tp_stage = self._evaluate_sell(
                holding, state, news, is_top_volume=is_top_volume
            )

            if not reason:
                continue

            if holding.sellable_qty <= 0 and holding.qty > 0:
                result.add_event(
                    "【매도 불가】\n"
                    f"종목: {holding.name}({holding.code})\n"
                    f"신호: {reason}\n"
                    f"보유 {holding.qty}주 있으나 매매가능 0주"
                )
                continue

            if sell_qty > 0:
                is_partial = sell_qty < holding.sellable_qty
                if self._execute_sell(
                    holding, reason, sell_qty, result, partial=is_partial, tp_stage=tp_stage
                ):
                    sold_count += 1
        return sold_count

    def _portfolio_heat_blocks_buy(self, holdings: list[HoldingView]) -> str | None:
        heat_limit, heat_pct = effective_portfolio_heat()
        losers = [h for h in holdings if h.profit_pct <= heat_pct]
        if len(losers) >= heat_limit:
            names = ", ".join(h.name for h in losers[:3])
            return f"손실 종목 {len(losers)}개 ({names}) - 신규매수 중단"
        return None

    def _run_buy_phase(
        self,
        result: AutoRunResult,
        holdings: list[HoldingView],
        news: MarketNewsContext | None = None,
    ) -> None:
        held_codes = {h.code for h in holdings}

        if news and not news.allow_buy:
            result.add_report(
                self._heartbeat(
                    "뉴스 필터 - 신규매수 중단 "
                    f"(심리 {news.sentiment:+.2f}, 리스크 {news.risk_score:.2f})"
                )
            )
            return

        daily = self._daily_loss_blocks_buy()
        if daily:
            self._alert_buy_block(result, daily)
            result.add_report(self._heartbeat(daily))
            return

        breaker = self._loss_circuit_blocks_buy()
        if breaker:
            self._alert_buy_block(result, breaker)
            result.add_report(self._heartbeat(breaker))
            return

        max_pos = effective_max_positions()
        if len(holdings) >= max_pos:
            result.add_report(
                self._heartbeat(f"보유 한도 ({len(holdings)}/{max_pos})")
            )
            return

        if not self._can_buy_today():
            result.add_report(
                self._heartbeat(f"일일 매수 한도 ({effective_max_buys_per_day()}회)")
            )
            return

        ms, me, as_, ae = effective_buy_windows()
        if not is_buy_window(ms, me, as_, ae):
            result.add_report(
                self._heartbeat(f"매수시간 외 ({ms}~{me}, {as_}~{ae})")
            )
            return

        heat = self._portfolio_heat_blocks_buy(holdings)
        if heat:
            result.add_report(self._heartbeat(heat))
            return

        scan_top = scalping_scan_rank_top if is_scalping_mode() else strategy_scan_rank_top
        min_score = scalping_min_score if is_scalping_mode() else strategy_min_score

        try:
            rank_items = self.client.get_trade_value_rank(top_n=scan_top)
            candidates = self._parse_candidates(rank_items)
        except (KiwoomAPIError, requests.RequestException) as exc:
            result.add_report(self._heartbeat(f"순위 조회 실패 - {exc}"))
            return

        if is_scalping_mode():
            bullish, market_msg = is_scalp_market_bullish(candidates)
            filter_fn = filter_scalp_candidates
        else:
            bullish, market_msg = is_market_bullish(candidates)
            filter_fn = filter_and_rank_candidates
            bull_n, bull_total, _, bull_detail = market_bullish_stats(candidates)
            if (
                news
                and news.sentiment <= strategy_weak_market_sentiment
                and bull_n < strategy_weak_market_min_bullish_count
            ):
                result.add_report(
                    self._heartbeat(
                        f"부정 뉴스·약세 - 매수 보류 ({bull_detail}, "
                        f"심리 {news.sentiment:+.2f})"
                    )
                )
                return

        if not bullish:
            result.add_report(self._heartbeat(f"매수 보류 - {market_msg}"))
            return

        eligible, rejected = filter_fn(candidates, held_codes)
        if not eligible:
            detail = rejected[0] if rejected else "조건 충족 없음"
            result.add_report(self._heartbeat(f"매수 보류 - {detail}"))
            return

        # 청산 직후 동일 종목 재진입 쿨다운
        cooldown_min = (
            scalping_reentry_cooldown_minutes
            if is_scalping_mode()
            else strategy_reentry_cooldown_minutes
        )
        if cooldown_min > 0:
            cooled: list[str] = []
            filtered: list[tuple[CandidateView, float]] = []
            for cand, score in eligible:
                since = self.positions.cooldown_minutes_since_exit(cand.code)
                if since is not None and since < cooldown_min:
                    cooled.append(
                        f"{cand.name}({cand.code}) {since:.0f}분 < {cooldown_min}분"
                    )
                    continue
                filtered.append((cand, score))
            if not filtered:
                note = cooled[0] if cooled else "쿨다운"
                result.add_report(self._heartbeat(f"재진입 쿨다운 - {note}"))
                return
            eligible = filtered

        best, score = eligible[0]
        news_adj = news.score_adjustment if news else 0.0
        adjusted = score + news_adj
        # 부정 뉴스일 때는 점수 완화 없음 (저품질·레버리지 종목 유입 방지)
        if news and news.sentiment <= strategy_weak_market_sentiment:
            effective_min = max(0.0, min_score)
        else:
            effective_min = max(0.0, min_score - 3.0)
        if adjusted < effective_min:
            result.add_report(
                self._heartbeat(
                    f"점수 부족 - {best.name} {adjusted:.1f} < {effective_min:.1f}점"
                )
            )
            return

        news_note = ""
        if news:
            news_note = f"뉴스심리 {news.sentiment:+.2f} 리스크 {news.risk_score:.2f}"
        self._execute_buy(best, adjusted, market_msg, result, news_note)

    def _run_crash_buy_phase(
        self,
        result: AutoRunResult,
        holdings: list[HoldingView],
        news: MarketNewsContext | None = None,
    ) -> None:
        """하락장에서 거래대금 상위 개별주 급락 구간 매수."""
        if is_scalping_mode() or not strategy_crash_buy_enabled:
            return
        if self._daily_loss_blocks_buy() or self._loss_circuit_blocks_buy():
            return
        if news and not news.allow_buy:
            return
        if news and news.risk_score >= strategy_crash_max_news_risk:
            return
        if not self._can_crash_buy_today():
            return
        if len(holdings) >= effective_max_positions():
            return

        ms, me, as_, ae = effective_buy_windows()
        if not is_buy_window(ms, me, as_, ae):
            return

        heat = self._portfolio_heat_blocks_buy(holdings)
        if heat:
            return

        held_codes = {h.code for h in holdings}
        try:
            rank_items = self.client.get_trade_value_rank(
                top_n=strategy_crash_scan_rank_top
            )
            candidates = self._parse_candidates(rank_items)
        except (KiwoomAPIError, requests.RequestException) as exc:
            result.add_report(self._heartbeat(f"급락매수 순위 조회 실패 - {exc}"))
            return

        bearish, market_msg = is_bear_market(candidates)
        if not bearish:
            return

        eligible, rejected = filter_crash_candidates(candidates, held_codes)
        if not eligible:
            detail = rejected[0] if rejected else "급락 조건 충족 없음"
            result.add_report(self._heartbeat(f"급락매수 보류 - {detail}"))
            return

        cooldown_min = strategy_crash_reentry_cooldown_minutes
        if cooldown_min > 0:
            cooled: list[str] = []
            filtered: list[tuple[CandidateView, float]] = []
            for cand, score in eligible:
                since = self.positions.cooldown_minutes_since_exit(cand.code)
                if since is not None and since < cooldown_min:
                    cooled.append(
                        f"{cand.name}({cand.code}) {since:.0f}분 < {cooldown_min}분"
                    )
                    continue
                filtered.append((cand, score))
            if not filtered:
                note = cooled[0] if cooled else "쿨다운"
                result.add_report(self._heartbeat(f"급락매수 쿨다운 - {note}"))
                return
            eligible = filtered

        best, score = eligible[0]
        news_note = ""
        if news:
            news_note = f"뉴스심리 {news.sentiment:+.2f} 리스크 {news.risk_score:.2f}"
        self._execute_crash_buy(best, score, market_msg, result, news_note)

    def _execute_crash_buy(
        self,
        candidate: CandidateView,
        score: float,
        market_msg: str,
        result: AutoRunResult,
        news_note: str = "",
    ) -> None:
        try:
            order_qty = self._calc_order_qty(candidate.current_price)
            order = self.client.buy_market(
                candidate.code,
                order_qty,
                dmst_stex_tp=dmst_stex_tp,
            )
            self._record_crash_buy()
            ord_no = order.get("ord_no", "")
            self.positions.register(
                candidate.code,
                candidate.name,
                candidate.current_price,
                entry_qty=order_qty,
            )
            reason = f"{market_msg} · 급락 {candidate.flu_rt:+.2f}%"
            try:
                self.journal.log(
                    "crash_buy_order",
                    code=candidate.code,
                    name=candidate.name,
                    qty=order_qty,
                    price=candidate.current_price,
                    reason=reason,
                    ord_no=ord_no,
                )
            except Exception:
                pass
            buy_msg = (
                "【급락 매수】\n"
                f"종목: {candidate.name}({candidate.code})\n"
                f"점수: {score:.1f}점 · {market_msg}\n"
                f"등락률: {candidate.flu_rt:+.2f}% · 거래대금 {candidate.rank}위\n"
            )
            if news_note:
                buy_msg += f"뉴스: {news_note}\n"
            buy_msg += (
                f"수량: {order_qty}주 시장가\n"
                f"주문번호: {ord_no}\n"
                f"{order.get('return_msg', '')}"
            )
            result.add_event(buy_msg)
            fill_msg = self.check_order_fill(
                ord_no, candidate.code, stk_nm=candidate.name
            )
            if fill_msg and is_event_message(fill_msg):
                result.add_event(fill_msg)
            elif fill_msg:
                result.add_report(fill_msg)
            result.add_report(
                self._heartbeat(
                    f"급락 매수 - {candidate.name}",
                    f"{candidate.flu_rt:+.2f}% · {score:.1f}점",
                )
            )
        except KiwoomAPIError as exc:
            result.add_event(
                f"【매수 실패】 급락 {candidate.name}({candidate.code})\n{exc}"
            )
        except requests.RequestException as exc:
            result.add_event(f"【매수 실패】 급락 {candidate.name}\n네트워크: {exc}")

    def _run_trend_buy_phase(
        self,
        result: AutoRunResult,
        holdings: list[HoldingView],
        news: MarketNewsContext | None = None,
    ) -> None:
        if is_scalping_mode() and scalping_disable_trend_buy:
            return
        if not trend_auto_buy_enabled:
            return
        if self._daily_loss_blocks_buy() or self._loss_circuit_blocks_buy():
            return
        if news and not news.allow_buy:
            return
        if not self._can_trend_buy_today():
            return
        if len(holdings) >= effective_max_positions():
            return
        if not self._can_buy_today():
            return
        ms, me, as_, ae = effective_buy_windows()
        if not is_buy_window(ms, me, as_, ae):
            return
        if not is_market_open():
            return

        held = {h.code for h in holdings}
        scan = self.trends.scan()
        if not scan.active_trends or not scan.picks:
            return

        for pick in scan.picks:
            if pick.code in held:
                continue
            if strategy_block_leveraged_etf and is_leveraged_etf(pick.name, pick.code):
                continue
            cooldown_min = (
                scalping_reentry_cooldown_minutes
                if is_scalping_mode()
                else strategy_reentry_cooldown_minutes
            )
            if cooldown_min > 0:
                since = self.positions.cooldown_minutes_since_exit(pick.code)
                if since is not None and since < cooldown_min:
                    continue
            self._execute_trend_buy(pick, result)
            result.add_report(
                self._heartbeat(
                    f"트렌드 매수 - {pick.name}",
                    f"[{pick.theme_name}] {pick.flu_rt:+.2f}%",
                )
            )
            return

    def _execute_trend_buy(self, pick: TrendPick, result: AutoRunResult) -> None:
        try:
            order_qty = self._calc_order_qty(pick.current_price)
            order = self.client.buy_market(
                pick.code,
                order_qty,
                dmst_stex_tp=dmst_stex_tp,
            )
            self._record_trend_buy()
            ord_no = order.get("ord_no", "")
            self.positions.register(
                pick.code,
                pick.name,
                pick.current_price,
                entry_qty=order_qty,
            )
            try:
                self.journal.log(
                    "trend_buy_order",
                    code=pick.code,
                    name=pick.name,
                    qty=order_qty,
                    price=pick.current_price,
                    reason=f"[{pick.theme_name}] {pick.reason}",
                    ord_no=ord_no,
                )
            except Exception:
                pass
            msg = (
                "【트렌드 매수】\n"
                f"테마: {pick.theme_name}\n"
                f"종목: {pick.name}({pick.code})\n"
                f"등락률: {pick.flu_rt:+.2f}% · {pick.current_price:,}원\n"
                f"점수: {pick.score:.1f} · {pick.reason}\n"
                f"수량: {order_qty}주 시장가\n"
                f"주문번호: {ord_no}\n"
                f"{order.get('return_msg', '')}"
            )
            result.add_event(msg)
            fill_msg = self.check_order_fill(ord_no, pick.code, stk_nm=pick.name)
            if fill_msg and is_event_message(fill_msg):
                result.add_event(fill_msg)
        except KiwoomAPIError as exc:
            result.add_event(
                f"【매수 실패】 트렌드 {pick.name}({pick.code})\n{exc}"
            )
        except requests.RequestException as exc:
            result.add_event(f"【매수 실패】 트렌드 {pick.name}\n{exc}")

    def _execute_buy(
        self,
        candidate: CandidateView,
        score: float,
        market_msg: str,
        result: AutoRunResult,
        news_note: str = "",
    ) -> None:
        try:
            order_qty = self._calc_order_qty(candidate.current_price)
            order = self.client.buy_market(
                candidate.code,
                order_qty,
                dmst_stex_tp=dmst_stex_tp,
            )
            self._record_buy()
            ord_no = order.get("ord_no", "")
            self.positions.register(
                candidate.code,
                candidate.name,
                candidate.current_price,
                entry_qty=order_qty,
            )
            try:
                self.journal.log(
                    "buy_order",
                    code=candidate.code,
                    name=candidate.name,
                    qty=order_qty,
                    price=candidate.current_price,
                    reason=market_msg,
                    ord_no=ord_no,
                )
            except Exception:
                pass
            buy_tag = "【스캘핑 매수】" if is_scalping_mode() else "【자동매수】"
            buy_msg = (
                f"{buy_tag}\n"
                f"종목: {candidate.name}({candidate.code})\n"
                f"점수: {score:.1f}점 · {market_msg}\n"
            )
            if news_note:
                buy_msg += f"뉴스: {news_note}\n"
            buy_msg += (
                f"순위: {candidate.prev_rank}→{candidate.rank}위\n"
                f"등락률: {candidate.flu_rt:+.2f}%\n"
                f"수량: {order_qty}주 시장가\n"
                f"주문번호: {ord_no}\n"
                f"{order.get('return_msg', '')}"
            )
            result.add_event(buy_msg)
            fill_msg = self.check_order_fill(
                ord_no, candidate.code, stk_nm=candidate.name
            )
            if fill_msg and is_event_message(fill_msg):
                result.add_event(fill_msg)
            elif fill_msg:
                result.add_report(fill_msg)
        except KiwoomAPIError as exc:
            result.add_event(f"【매수 실패】 {candidate.name}({candidate.code})\n{exc}")
        except requests.RequestException as exc:
            result.add_event(f"【매수 실패】 {candidate.name}\n네트워크: {exc}")

    def check_order_fill(
        self,
        ord_no: str,
        stk_cd: str,
        *,
        sell_tp: str = "2",
        stk_nm: str = "",
    ) -> str | None:
        name = stk_nm or stk_cd
        code = self.client.normalize_stock_code(stk_cd)
        deadline = time.time() + fill_poll_wait_sec
        while time.time() < deadline:
            time.sleep(fill_poll_interval_sec)
            try:
                fills = self.client.get_executions(
                    stk_cd=code,
                    ord_no=ord_no,
                    qry_tp="1",
                    sell_tp=sell_tp,
                )
            except (KiwoomAPIError, requests.RequestException):
                continue
            for fill in fills:
                if fill.get("ord_no") != ord_no:
                    continue
                if not fill.get("cntr_qty") or fill.get("cntr_qty") == "0":
                    continue
                key = self._fill_key(fill)
                if key in self._seen_fill_keys:
                    return None
                self._seen_fill_keys.add(key)
                self._journal_fill(fill)
                return self._format_fill_message(fill)
        return f"【주문 접수】 {name}({code}) #{ord_no} 체결 대기 중"

    def _heartbeat(self, action: str, target: str = "") -> str:
        self._reset_daily_counter()
        mode = "스캘핑" if is_scalping_mode() else "스윙"
        lines = [
            f"【자동매매 점검 · {mode}】",
            f"시각: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"장: {market_status_text()}",
            f"일반매수: {self._buy_count}/{effective_max_buys_per_day()}회",
            f"조치: {action}",
        ]
        if not is_scalping_mode() and trend_auto_buy_enabled:
            lines.insert(
                -1,
                f"트렌드매수: {self._trend_buy_count}/{strategy_trend_max_buys_per_day}회",
            )
        if target:
            lines.insert(-1, f"대상: {target}")
        return "\n".join(lines)

    def _portfolio_summary(
        self,
        holdings: list[HoldingView],
        sold_count: int,
    ) -> str:
        max_pos = effective_max_positions()
        fmt = self.client.format_amount
        lines = [
            "【보유 종목】",
            f"보유 {len(holdings)}/{max_pos} · 매도 {sold_count}건",
        ]
        if not holdings:
            lines.append("  보유 없음")
            return "\n".join(lines)

        total_eval = 0
        for h in holdings:
            total_eval += h.qty * h.current_price
            state = self.positions.get(h.code)
            peak = state.peak_profit_pct if state else h.profit_pct
            hold = self.positions.holding_minutes(h.code)
            hold_txt = f" · 보유 {hold:.0f}분" if hold is not None else ""
            price_line = f"    {h.qty}주 (매매가능 {h.sellable_qty}) @ {fmt(str(h.current_price))}원"
            if state and state.entry_price > 0:
                price_line += f" · 진입 {fmt(str(state.entry_price))}원"
            elif h.purchase_price > 0:
                price_line += f" · 매입 {fmt(str(h.purchase_price))}원"
            tags: list[str] = []
            if state:
                if state.partial_sold:
                    tags.append("부분익절")
                if state.tp_stage:
                    tags.append(f"TP{state.tp_stage}")
            tag_txt = f" [{', '.join(tags)}]" if tags else ""
            lines.append(
                f"  {h.name}({h.code})\n"
                f"{price_line}\n"
                f"    수익 {h.profit_pct:+.2f}% · 고점 {peak:+.2f}%{hold_txt}{tag_txt}"
            )
        if total_eval > 0:
            lines.insert(1, f"평가합계(근사): {fmt(str(total_eval))}원")
        return "\n".join(lines)

    def run_cycle(self) -> AutoRunResult:
        result = AutoRunResult()
        if not self.enabled:
            result.add_event("자동매매 OFF")
            return result

        self._reset_daily_counter()
        self._collect_new_fills(result)

        news_ctx = self.news.get_context()
        result.add_report(news_ctx.summary_message())

        sold_count = 0
        holdings: list[HoldingView] = []

        if is_market_open():
            # 시장이 강세일 때는 뉴스로 인한 신규매수 중단/방어모드를 완화
            if news_override_when_market_bullish and news_enabled:
                try:
                    scan_top = (
                        scalping_scan_rank_top
                        if is_scalping_mode()
                        else strategy_scan_rank_top
                    )
                    rank_items = self.client.get_trade_value_rank(top_n=scan_top)
                    candidates = self._parse_candidates(rank_items)
                    if is_scalping_mode():
                        bullish, _ = is_scalp_market_bullish(candidates)
                        strong_market = bullish
                    else:
                        bullish, _ = is_market_bullish(candidates)
                        bull_n, bull_total, bull_ratio, _ = market_bullish_stats(
                            candidates
                        )
                        strong_market = (
                            bullish
                            and bull_total > 0
                            and bull_ratio >= news_override_min_bullish_ratio
                        )
                    if (
                        strong_market
                        and news_ctx.risk_score < news_override_max_risk_score
                    ):
                        changed = False
                        notes: list[str] = []
                        if (
                            news_override_disable_buy_block
                            and not news_ctx.allow_buy
                            and news_ctx.sentiment
                            >= news_override_allow_buy_sentiment_floor
                        ):
                            news_ctx.allow_buy = True
                            changed = True
                            notes.append("신규매수 중단 OFF")
                        if (
                            news_override_disable_defensive_mode
                            and news_ctx.defensive_mode
                        ):
                            news_ctx.defensive_mode = False
                            changed = True
                            notes.append("방어모드 OFF")
                        if changed:
                            note = "강세장 감지 → 뉴스 override (" + ", ".join(notes) + ")"
                            news_ctx.error = f"{news_ctx.error} | {note}".strip(" |")
                except (KiwoomAPIError, requests.RequestException):
                    pass

            sold_count = self._run_sell_phase(result, news_ctx)
            try:
                holdings = self._parse_holdings()
                self._run_buy_phase(result, holdings, news_ctx)
                holdings = self._parse_holdings()
                self._run_crash_buy_phase(result, holdings, news_ctx)
                holdings = self._parse_holdings()
                self._run_trend_buy_phase(result, holdings, news_ctx)
            except (KiwoomAPIError, requests.RequestException) as exc:
                result.add_event(f"잔고 오류: {exc}")
        else:
            try:
                holdings = self._parse_holdings()
            except (KiwoomAPIError, requests.RequestException):
                pass
            result.add_report(self._heartbeat("장 마감 - 규칙 대기"))

        result.add_report(self._portfolio_summary(holdings, sold_count))
        return result

    def run_once(self) -> str:
        msgs = self.run_cycle().events
        return msgs[-1] if msgs else ""
