from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import requests

from config.config import (
    chart_filter_enabled,
    chart_eval_max_candidates,
    chart_primary_mode,
    chart_primary_eval_max_candidates,
    chart_min_score,
    strategy_chart_primary_max_flu_rt,
    orb_enabled,
    orb_range_start,
    orb_range_end,
    orb_trade_end,
    orb_volume_breakout_ratio,
    orb_require_above_vwap,
    orb_min_range_pct,
    orb_max_range_pct,
    orb_score_bonus,
    orb_wait_for_range,
    orb_morning_momentum_only,
    default_order_qty,
    position_sizing_enabled,
    position_target_krw,
    position_min_qty,
    position_max_qty,
    position_addon_enabled,
    position_addon_min_drop_pct,
    position_addon_quality_max_rank,
    position_addon_momentum_min_peak_pct,
    position_addon_max_per_day,
    position_addon_max_qty_multiplier,
    strategy_swing_breakeven_activate_pct,
    strategy_swing_breakeven_floor_pct,
    strategy_swing_protect_trailing_activate_pct,
    strategy_swing_protect_trailing_drawdown_pct,
    strategy_swing_be_remainder_drawdown_pct,
    strategy_swing_exit_confirm_cycles,
    strategy_swing_exit_vol_lookback,
    strategy_swing_exit_vol_light_ratio,
    strategy_swing_exit_vol_heavy_ratio,
    strategy_swing_stagnation_minutes,
    strategy_swing_stagnation_max_profit_pct,
    strategy_loser_reentry_cooldown_hours,
    strategy_momentum_buy_enabled,
    strategy_momentum_window_end,
    dmst_stex_tp,
    use_paper,
    fill_poll_interval_sec,
    fill_poll_wait_sec,
    daily_loss_stop_pct,
    hard_stop_loss_pct,
    top_volume_rank_n,
    news_defensive_loss_pct,
    news_enabled,
    news_filter_secondary,
    news_override_min_bullish_ratio,
    news_override_when_market_bullish,
    strategy_block_etf,
    strategy_block_leveraged_etf,
    strategy_defensive_min_hold_minutes,
    strategy_defensive_skip_overnight,
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
    strategy_swing_trailing_activate_pct,
    strategy_swing_trailing_drawdown_pct,
    strategy_trend_max_buys_per_day,
    strategy_breakeven_activate_pct,
    strategy_breakeven_floor_pct,
    strategy_eod_cut_loss_enabled,
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
    regime_enabled,
    drawdown_scale_enabled,
    drawdown_scale_max_mult,
    regime_scan_top,
    drawdown_benchmark_code,
)
try:
    from config.config import api_error_notify_cooldown_sec as api_error_notify_cooldown_sec
except ImportError:
    api_error_notify_cooldown_sec = 1800.0
try:
    from config.config import strategy_other_stop_loss_pct as strategy_other_stop_loss_pct
except ImportError:
    strategy_other_stop_loss_pct = 2.5
try:
    from config.config import strategy_other_trail_activate_pct as strategy_other_trail_activate_pct
except ImportError:
    strategy_other_trail_activate_pct = 1.5
try:
    from config.config import strategy_other_trail_drawdown_pct as strategy_other_trail_drawdown_pct
except ImportError:
    strategy_other_trail_drawdown_pct = 1.0
try:
    from config.config import strategy_other_eod_sell_all as strategy_other_eod_sell_all
except ImportError:
    strategy_other_eod_sell_all = True
try:
    from config.config import strategy_other_flatten_overnight as strategy_other_flatten_overnight
except ImportError:
    strategy_other_flatten_overnight = True
from kiwoom.client import KiwoomAPIError, KiwoomClient
from trading.market_utils import (
    calc_profit_pct,
    is_buy_window,
    is_market_open,
    market_status_text,
    parse_hhmm,
)
from trading.journal_stats import build_daily_summary, format_daily_summary_text
from trading.account_pnl import build_account_summary, format_account_summary_text
from trading.account_settings import round_trip_cost_pct
from trading.mega_cap import is_mega_cap
from trading.position_tracker import PositionState, PositionTracker
from trading.news_analyzer import MarketNewsAnalyzer, MarketNewsContext
from trading.news_priority import apply_bullish_news_override, news_score_gate
from trading.chart_primary import (
    advisory_market_note,
    advisory_strategy_score,
    build_buy_advisory_notes,
    chart_modes_for_candidate,
    chart_primary_channel_flags,
    filter_chart_primary_universe,
)
from trading.scoring import (
    CandidateView,
    filter_and_rank_candidates,
    is_market_bullish,
    is_momentum_candidate,
    market_bullish_stats,
    qualifies_for_position_addon,
)
from trading.symbol_filters import is_etf, is_leveraged_etf
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
from trading.chart_signals import (
    ChartSignalAnalyzer,
    ChartSignalResult,
    classify_exit_volume,
    latest_vs_avg_volume_ratio,
)
from trading.crash_buy import (
    filter_crash_candidates,
    is_bear_market,
)
from trading.orb import (
    evaluate_orb_breakout,
    is_orb_range_forming,
    is_orb_trade_window,
)
from trading.market_regime import (
    MarketContext,
    format_buy_meta,
    is_channel_allowed,
    detect_regime,
)
from trading.drawdown_scale import DrawdownScaleCalculator, scale_multiplier_for_channel
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


def throttle_error_event(
    state: dict[str, dict],
    bucket: str,
    message: str,
    *,
    now: float,
    cooldown_sec: float,
) -> str | None:
    """같은 조회 오류는 cooldown 동안 한 번만 알린다. 재알림 시 생략 횟수를 붙인다."""
    slot = state.setdefault(bucket, {"key": "", "at": 0.0, "suppressed": 0})
    cooldown = max(0.0, float(cooldown_sec))
    if slot["key"] == message and (now - float(slot["at"])) < cooldown:
        slot["suppressed"] = int(slot["suppressed"]) + 1
        return None
    skipped = int(slot["suppressed"] or 0)
    slot["key"] = message
    slot["at"] = now
    slot["suppressed"] = 0
    if skipped:
        return f"{message}\n(동일 오류 {skipped}회 생략)"
    return message


def clear_error_event_bucket(state: dict[str, dict], bucket: str) -> None:
    state.pop(bucket, None)


def _is_token_auth_error(message: str) -> bool:
    text = message or ""
    return (
        "Token이 유효하지 않습니다" in text
        or "[8005" in text
        or "8005:" in text
        or "[8001]" in text
    )


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
        self._addon_buys_today: dict[str, int] = {}
        self._seen_fill_keys: set[str] = set()
        self._holdings_cache: list[HoldingView] | None = None
        self._holdings_cache_ts: float = 0.0
        self._holdings_cache_ttl_sec: float = 3.0
        self._buy_block_until: datetime | None = None
        self._stop_buy_for_day: bool = False
        self._circuit_reset_date: date | None = None
        self._breaker_alert_date: date | None = None
        self.positions = PositionTracker()
        self.news = MarketNewsAnalyzer()
        self.trends = TrendScanner(client)
        self.journal = TradeJournal()
        self.chart = ChartSignalAnalyzer(client)
        self._drawdown = DrawdownScaleCalculator(client)
        self._cycle_ctx: MarketContext | None = None
        self._error_notify_state: dict[str, dict] = {}
        self._seed_seen_fills_from_journal()

    def _seed_seen_fills_from_journal(self) -> None:
        """재시작 시 과거 체결을 다시 알림하지 않도록 저널에서 키 복원."""
        for event in self.journal.read_all():
            if event.event != "fill" or not event.ord_no:
                continue
            self._seen_fill_keys.add(
                "|".join(
                    [
                        event.ord_no,
                        event.code or "",
                        str(event.price or ""),
                        str(event.qty or ""),
                        "",
                    ]
                )
            )

    def _invalidate_holdings_cache(self) -> None:
        self._holdings_cache = None
        self._holdings_cache_ts = 0.0

    def _pick_with_chart_filter(
        self,
        eligible: list[tuple[CandidateView, float]],
        *,
        allow_momentum: bool = False,
        channel_pullback: bool = True,
    ) -> tuple[CandidateView, float, ChartSignalResult] | None:
        """차트 필터 통과 후보 중 최고 점수 선택."""
        pool = eligible[: max(1, int(chart_eval_max_candidates))]
        if chart_filter_enabled and pool:
            self.chart.prefetch_daily([cand.code for cand, _ in pool])
        best: tuple[CandidateView, float, ChartSignalResult] | None = None
        for cand, score in pool:
            momentum = allow_momentum and is_momentum_candidate(cand)
            if not momentum and not channel_pullback:
                continue
            chart = self.chart.evaluate_candidate(cand, momentum=momentum)
            if not chart.passed:
                continue
            total = score + self.chart.chart_score_bonus(chart)
            if best is None or total > best[1]:
                best = (cand, total, chart)
        return best

    def _in_morning_buy_window(self, now: datetime | None = None) -> bool:
        current = now or datetime.now()
        ms, me, _, _ = effective_buy_windows()
        t = current.time()
        return parse_hhmm(ms) <= t < parse_hhmm(me)

    def _pick_chart_primary(
        self,
        universe: list[CandidateView],
        *,
        allow_momentum: bool = True,
        allow_pullback: bool = True,
    ) -> tuple[CandidateView, float, ChartSignalResult, bool] | None:
        """차트 우선: 허용된 차트 모드만 시도해 최고점 선택.

        Returns:
            (candidate, total_score, chart_result, used_momentum)
        """
        if not allow_momentum and not allow_pullback:
            return None
        limit = max(
            1,
            int(chart_primary_eval_max_candidates or chart_eval_max_candidates),
        )
        pool = universe[:limit]
        if not pool:
            return None
        if chart_filter_enabled:
            self.chart.prefetch_daily([cand.code for cand in pool])

        best: tuple[CandidateView, float, ChartSignalResult, bool] | None = None
        for cand in pool:
            modes = chart_modes_for_candidate(
                cand,
                allow_momentum=allow_momentum,
                allow_pullback=allow_pullback,
            )
            for momentum in modes:
                chart = self.chart.evaluate_candidate(cand, momentum=momentum)
                if not chart.passed:
                    continue
                base = advisory_strategy_score(cand, momentum=momentum)
                total = base + self.chart.chart_score_bonus(chart)
                if best is None or total > best[1]:
                    best = (cand, total, chart, momentum)
        return best

    def _apply_orb_morning_filter(
        self,
        eligible: list[tuple[CandidateView, float]],
        result: AutoRunResult,
    ) -> list[tuple[CandidateView, float]] | None:
        """아침 ORB 창: 돌파 종목 우선, 미통과 시 눌림/일반매수로 fall-through.

        Returns:
            ORB 통과 후보, fall-through 시 원본 eligible,
            시초 레인지 형성 중(대기)일 때만 None.
        """
        if is_scalping_mode() or not orb_enabled:
            return eligible
        now = datetime.now()
        if is_orb_range_forming(
            now, range_start=orb_range_start, range_end=orb_range_end
        ):
            if orb_wait_for_range:
                result.add_report(
                    self._heartbeat(
                        f"ORB 시초구간 형성 중 ({orb_range_start}~{orb_range_end})"
                    )
                )
                return None
            return eligible
        if not is_orb_trade_window(
            now, range_end=orb_range_end, trade_end=orb_trade_end
        ):
            return eligible

        pool = eligible
        if orb_morning_momentum_only:
            pool = [
                (cand, score)
                for cand, score in eligible
                if is_momentum_candidate(cand)
            ]
            if not pool:
                result.add_report(
                    self._heartbeat(
                        "ORB 미통과 - 모멘텀 후보 없음 · 눌림/일반매수 계속"
                    )
                )
                return eligible

        passed: list[tuple[CandidateView, float]] = []
        rejects: list[str] = []
        for cand, score in pool[: max(1, int(chart_eval_max_candidates))]:
            try:
                minutes = self.chart.load_minute_candles(cand.code)
            except (KiwoomAPIError, requests.RequestException) as exc:
                rejects.append(f"{cand.name}: 분봉실패 {exc}")
                continue
            check = evaluate_orb_breakout(
                minutes,
                current_price=cand.current_price,
                now=now,
                range_start=orb_range_start,
                range_end=orb_range_end,
                trade_end=orb_trade_end,
                volume_breakout_ratio=orb_volume_breakout_ratio,
                require_above_vwap=orb_require_above_vwap,
                min_range_pct=orb_min_range_pct,
                max_range_pct=orb_max_range_pct,
                score_bonus=orb_score_bonus,
            )
            if not check.passed:
                rejects.append(f"{cand.name}: {check.reason}")
                continue
            passed.append((cand, score + check.bonus))

        if not passed:
            detail = rejects[0] if rejects else "ORB 돌파 없음"
            result.add_report(
                self._heartbeat(f"ORB 미통과 - {detail} · 눌림/일반매수 계속")
            )
            return eligible
        result.add_report(
            self._heartbeat(f"ORB 통과 {len(passed)}종목 (시초 {orb_range_end} 돌파)")
        )
        return passed

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
        pnl_krw = self._compute_today_pnl_krw()
        lines = ["【매수 상태】"]
        if pnl_pct is not None:
            krw_txt = f" · 순손익 {pnl_krw:+,}원" if pnl_krw is not None else ""
            lines.append(f"오늘 누적 손익률(근사): {pnl_pct:+.2f}%{krw_txt}")
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
        if self._cycle_ctx and self._cycle_ctx.regime:
            r = self._cycle_ctx.regime
            lines.append(f"국면: {r.label} ({r.message})")
        if self._cycle_ctx and self._cycle_ctx.drawdown:
            lines.append(f"드로다운: {self._cycle_ctx.drawdown.message}")
        return "\n".join(lines)

    def _compute_today_pnl_krw(self) -> int | None:
        """오늘 완결 매매 순손익(원, 수수료·세금 반영)."""
        try:
            summary = build_daily_summary()
            net = (summary.get("summary") or {}).get("net_pnl_krw")
            if net is None:
                return None
            return int(net)
        except OSError:
            return None

    def get_account_summary(self, *, include_live_balance: bool = True) -> str:
        """원금 대비 실계좌 손익 요약."""
        try:
            summary = build_account_summary(include_live_balance=include_live_balance)
            return format_account_summary_text(summary)
        except OSError as exc:
            return f"【원금 대비 손익】\n조회 실패: {exc}"

    def get_daily_pnl_summary(self, target_date: date | None = None) -> str:
        """일별 매매·손익 요약 텍스트."""
        try:
            summary = build_daily_summary(target_date=target_date)
            return format_daily_summary_text(summary)
        except OSError as exc:
            return f"【매매·손익】\n저널 조회 실패: {exc}"

    def _compute_today_pnl_pct(self) -> float | None:
        """오늘 매매 기준 누적 손익률(%) 근사."""
        events = self._today_journal_events()
        if not events:
            return None

        buys_by_code: dict[str, list[tuple[int, int]]] = {}
        invested = 0
        for e in events:
            if e.event not in (
                "buy_order",
                "trend_buy_order",
                "crash_buy_order",
                "addon_buy_order",
            ):
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
            if e.event != "sell_order":
                continue
            q = int(e.qty or 0)
            if q <= 0:
                continue
            queue = buys_by_code.get(e.code) or []
            if not queue:
                continue
            remain = q
            sell_price = int(e.price or 0)
            while remain > 0 and queue:
                bq, bp = queue[0]
                take = min(remain, bq)
                if sell_price > 0 and bp > 0:
                    pnl_amount += take * (sell_price - bp)
                elif e.profit_pct is not None:
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
    def _base_order_qty(price: int, *, scale_mult: float = 1.0) -> int:
        """종목당 목표 금액 기준 주문 수량. 비활성/가격 0이면 기본 수량."""
        if not position_sizing_enabled or not price or price <= 0:
            return max(1, int(default_order_qty))
        target = max(0, int(position_target_krw))
        if target <= 0:
            return max(1, int(default_order_qty))
        if scale_mult > 0 and scale_mult != 1.0:
            target = int(target * scale_mult)
        if int(price) > target:
            return 0
        qty = target // int(price)
        qty = max(int(position_min_qty), int(qty))
        qty = min(int(position_max_qty), qty)
        return max(1, qty)

    def _channel_scale_mult(self, channel: str) -> float:
        if not drawdown_scale_enabled or not self._cycle_ctx:
            return 1.0
        return scale_multiplier_for_channel(self._cycle_ctx.drawdown, channel)

    def _calc_order_qty(self, price: int, *, channel: str = "pullback") -> int:
        return self._base_order_qty(
            price, scale_mult=self._channel_scale_mult(channel)
        )

    def _buy_reason_prefix(self, channel: str) -> str:
        snap = self._cycle_ctx.regime if self._cycle_ctx else None
        scale = self._channel_scale_mult(channel)
        return format_buy_meta(snap, scale_mult=scale)

    def _merge_buy_reason(self, channel: str, detail: str) -> str:
        prefix = self._buy_reason_prefix(channel)
        if prefix and detail:
            return f"{prefix} · {detail}"
        return prefix or detail

    def _resolve_cycle_context(
        self,
        news: MarketNewsContext | None = None,
    ) -> MarketContext:
        """한 사이클당 국면·드로다운·후보 종목을 한 번 계산."""
        ctx = MarketContext()
        if not regime_enabled and not drawdown_scale_enabled:
            self._cycle_ctx = ctx
            return ctx

        scan_top = max(
            regime_scan_top,
            strategy_scan_rank_top,
            strategy_crash_scan_rank_top,
            scalping_scan_rank_top if is_scalping_mode() else 0,
        )
        try:
            rank_items = self.client.get_trade_value_rank(top_n=scan_top)
            candidates = self._parse_candidates(rank_items)
            ctx.candidates = candidates
            if regime_enabled and candidates:
                risk = news.risk_score if news else None
                ctx.regime = detect_regime(candidates, news_risk_score=risk)
            if drawdown_scale_enabled:
                ctx.drawdown = self._drawdown.compute()
        except (KiwoomAPIError, requests.RequestException):
            pass

        self._cycle_ctx = ctx
        return ctx

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

    @staticmethod
    def _exit_uses_market(reason: str) -> bool:
        """손절·본전스탑·방어 강제매도는 시장가. 트레일·익절은 지정가."""
        if reason.startswith("손절"):
            return True
        if reason.startswith("방어모드 매도"):
            return True
        if reason.startswith("오버나잇"):
            return True
        if reason.startswith("장마감"):
            return True
        if reason.startswith("본전스탑") and "트레일링" not in reason:
            return True
        return False

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

    def _recent_loss_blocked_codes(self) -> dict[str, str]:
        """최근 손실 청산 종목 → 차단 사유. 반복 손실 재매수 방지."""
        hours = float(strategy_loser_reentry_cooldown_hours)
        if hours <= 0:
            return {}
        now = datetime.now()
        last_sells: dict[str, tuple[datetime, float]] = {}
        for e in self.journal.tail(500):
            if e.event != "sell_order" or not e.code or e.profit_pct is None:
                continue
            try:
                ts = datetime.fromisoformat(e.ts)
            except ValueError:
                continue
            last_sells[e.code] = (ts, float(e.profit_pct))

        blocked: dict[str, str] = {}
        for code, (ts, pnl) in last_sells.items():
            if pnl >= 0:
                continue
            elapsed_h = (now - ts).total_seconds() / 3600.0
            if elapsed_h < hours:
                blocked[code] = (
                    f"최근 손실 {pnl:+.2f}% "
                    f"(경과 {elapsed_h:.0f}h < {hours:.0f}h)"
                )
        return blocked

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
        _, eod = effective_eod_times()
        return (
            f"【매매 전략 · {mode_label()}】\n\n"
            f"점검 주기: {effective_auto_interval_sec()}초\n"
            f"동시 보유: 최대 {effective_max_positions()}종목\n"
            f"일반 매수: 최대 {effective_max_buys_per_day()}회/일 · "
            f"트렌드: {strategy_trend_max_buys_per_day}회/일\n\n"
            "■ 매도\n"
            "  · 시총 대형(삼성·하이닉스·NAVER 등 10종): "
            f"손절 -{strategy_stop_loss_pct}% · 당일 강제청산 없음 · "
            "본전스탑·수익보호 트레일\n"
            f"  · 그 외: 손절 -{strategy_other_stop_loss_pct}% · "
            f"고점 -{strategy_other_trail_drawdown_pct}%p 트레일 · "
            "당일 마감 전량 · 오버나잇 금지\n"
            f"  · 대형 본전스탑: 고점 +{strategy_swing_breakeven_activate_pct}% 후 "
            f"+{strategy_swing_breakeven_floor_pct}% 미만·왕복비용 이상이면 "
            f"50%(1주는 전량), "
            f"잔량은 고점-{strategy_swing_be_remainder_drawdown_pct}%p(바닥 0%) 트레일 · "
            f"{strategy_swing_exit_confirm_cycles}회 확인 · "
            f"거래량 {strategy_swing_exit_vol_light_ratio:.1f}x 미만 대기/"
            f"{strategy_swing_exit_vol_heavy_ratio:.1f}x 이상 즉시\n"
            f"  · 대형 수익보호 트레일: 고점 +{strategy_swing_protect_trailing_activate_pct}% "
            f"→ -{strategy_swing_protect_trailing_drawdown_pct}%p · "
            f"{strategy_swing_exit_confirm_cycles}회 확인 · "
            f"거래량 {strategy_swing_exit_vol_light_ratio:.1f}x 미만 대기/"
            f"{strategy_swing_exit_vol_heavy_ratio:.1f}x 이상 즉시\n"
            f"  · 손절·본전스탑·방어·장마감 시장가, "
            f"트레일 {'지정가' if strategy_exit_use_limit_orders else '시장가'}\n"
            + (
                "  · 정체 청산: 비활성\n"
                if int(strategy_swing_stagnation_minutes) <= 0
                else (
                    f"  · 정체 청산: {strategy_swing_stagnation_minutes}분+ 보유 & "
                    f"+{strategy_swing_stagnation_max_profit_pct:.1f}% 미만\n"
                )
            )
            + (
                f"  · 장마감: 대형 강제청산 없음"
                + (
                    f" · 그 외 {eod} 전량"
                    if strategy_other_eod_sell_all
                    else ""
                )
            )
            + "\n\n"
            + (
                "■ 매수 (차트 우선)\n"
                f"  · 거래대금 상위 {strategy_scan_rank_top} → 차트 ≥{chart_min_score:.0f}점이 본결정\n"
                f"  · 차트 평가 상위 {chart_primary_eval_max_candidates}종목 "
                f"(오전 모멘텀·이후 눌림)\n"
                f"  · 등락 +{strategy_chart_primary_max_flu_rt:.0f}% 초과 금지 · "
                "고변동 오후 신규 차트매수 없음\n"
                f"  · 재진입 쿨다운 {strategy_reentry_cooldown_minutes}분 · "
                "방어모드면 신규 금지\n"
                "  · 전략점수·뉴스는 참고/알림 (방어·심리 중단선은 하드스톱)\n"
                "  · ETF/ETN 제외 · 보유·미체결 제외\n"
                if chart_primary_mode
                else (
                    "■ 매수 (모멘텀·ORB 우선)\n"
                    f"  · 거래대금 상위 {strategy_scan_rank_top} · 점수 ≥{strategy_min_score}\n"
                    f"  · 등락 {strategy_min_flu_rt}~{strategy_max_flu_rt}%\n"
                    f"  · 재진입 쿨다운 {strategy_reentry_cooldown_minutes}분 · "
                    f"손실 종목 {strategy_loser_reentry_cooldown_hours:.0f}h 차단\n"
                    + (
                        f"  · ORB: 시초 {orb_range_start}~{orb_range_end} 고가 돌파"
                        f" · 거래량×{orb_volume_breakout_ratio:.1f}"
                        f" · ~{orb_trade_end}\n"
                        if orb_enabled
                        else ""
                    )
                    + (
                        "  · ETF/ETN 자동매수 제외\n"
                        if strategy_block_etf
                        else (
                            "  · 레버리지/인버스 ETF 제외\n"
                            if strategy_block_leveraged_etf
                            else ""
                        )
                    )
                )
            )
            + (
                f"  · 시간: {ms}~{me} (오후 매수 없음)\n"
                if as_ == ae
                else f"  · 시간: {ms}~{me}, {as_}~{ae}\n"
            )
            + (
                f"  · 모멘텀 차트모드: ~{strategy_momentum_window_end} 참고\n"
                if chart_primary_mode and strategy_momentum_buy_enabled
                else (
                    f"  · 모멘텀 채널: ~{strategy_momentum_window_end} "
                    "상승 중·순위 급등 허용\n"
                    if strategy_momentum_buy_enabled
                    else "\n"
                )
            )
            + (
                f"  · 추가매수: 진입가 -{position_addon_min_drop_pct:.1f}%↓ · "
                f"우량 상위{position_addon_quality_max_rank}위/모멘텀 · "
                f"종목당 일{position_addon_max_per_day}회 · "
                f"최대 {position_addon_max_qty_multiplier:.0f}배\n"
                if position_addon_enabled and not is_scalping_mode()
                else ""
            )
            + (
                f"  · 종목당 목표 {position_target_krw:,}원\n"
                if position_sizing_enabled
                else ""
            )
            + (
                "■ 트렌드 자동매수: OFF (수동 /trend buy)\n"
                if not trend_auto_buy_enabled
                else "■ 트렌드: 핫테마 연관 눌림목\n"
            )
            + (
                f"■ 급락 우량주: 하락장 · 상위 {strategy_crash_max_rank}위 · "
                f"{strategy_crash_min_flu_rt}~{strategy_crash_max_flu_rt}% · "
                f"일 {strategy_crash_max_buys_per_day}회\n"
                if strategy_crash_buy_enabled
                else ""
            )
            + "■ 연속손실 브레이커: 3회→60분 / 5회→당일중지\n"
            + (
                "■ 국면감지: 참고/알림 (매수 하드게이트 아님)\n"
                "■ 차트우선: 모멘텀 차트는 +2~+4% 러너만 · 뉴스 심리 -0.70 이하면 매수중단\n"
                "■ 방어모드: 당일 포지션만 (오버나잇은 손절)\n"
                if chart_primary_mode and regime_enabled
                else (
                    "■ 국면감지: 강세(모멘텀·눌림·추가) / 횡보(추가만) / "
                    "약세(급락·추가) / 고변동(모멘텀·급락·추가)\n"
                    if regime_enabled
                    else ""
                )
            )
            + (
                f"■ 드로다운스케일: {drawdown_benchmark_code} MDD 구간별 "
                f"최대 {drawdown_scale_max_mult:.1f}배\n"
                if drawdown_scale_enabled
                else ""
            )
            + "■ /mode swing|scalping · /auto on · /report"
        )

    def get_news_briefing(self) -> str:
        live = self.news.get_context().summary_message()
        try:
            from trading.news_sentiment_log import format_session_summary_text

            sessions = format_session_summary_text()
        except OSError:
            sessions = ""
        if sessions:
            return live + "\n\n" + sessions
        return live

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
        lines.append(self.get_daily_pnl_summary())
        lines.append(self.get_account_summary())
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
            f"{self.get_account_summary()}\n\n"
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
        sections.append(self.get_daily_pnl_summary())
        sections.append(self.get_account_summary(include_live_balance=False))
        sections.append(self.journal.format_recent_summary(5))
        return "\n\n".join(sections)

    def _reset_daily_counter(self) -> None:
        self._reset_circuit_for_new_day()
        today = date.today()
        if self._buy_count_date != today:
            self._buy_count_date = today
            self._buy_count = 0
            self._addon_buys_today = {}
        if self._trend_buy_count_date != today:
            self._trend_buy_count_date = today
            self._trend_buy_count = 0
        if self._crash_buy_count_date != today:
            self._crash_buy_count_date = today
            self._crash_buy_count = 0

    def _can_addon_buy_today(self, code: str) -> bool:
        self._reset_daily_counter()
        return (
            self._addon_buys_today.get(code, 0) < position_addon_max_per_day
        )

    def _record_addon_buy(self, code: str) -> None:
        self._reset_daily_counter()
        self._buy_count += 1
        self._addon_buys_today[code] = self._addon_buys_today.get(code, 0) + 1

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

    def _is_recent_open_lot(self, code: str, now: datetime | None = None) -> bool:
        """매수 직후 키움 잔고 반영 전. 이 동안 tracker 종목은 지우지 않는다."""
        state = self.positions.get(code)
        if state is None or not state.entry_time:
            return False
        try:
            entered = datetime.fromisoformat(state.entry_time)
        except ValueError:
            return False
        minutes = ((now or datetime.now()) - entered).total_seconds() / 60.0
        return 0 <= minutes < float(self._position_sync_grace_minutes())

    def _should_suppress_holding_sync(self, code: str) -> bool:
        """청산 직후 API 잔고 지연으로 포지션이 재생성되는 것을 방지."""
        since = self.positions.cooldown_minutes_since_exit(code)
        if since is None:
            return False
        return since < float(self._position_sync_grace_minutes())

    def _add_throttled_error(self, result: AutoRunResult, bucket: str, message: str) -> None:
        text = throttle_error_event(
            self._error_notify_state,
            bucket,
            message,
            now=time.monotonic(),
            cooldown_sec=float(api_error_notify_cooldown_sec),
        )
        if not text:
            return
        if _is_token_auth_error(message):
            print(text)
            return
        result.add_event(text)

    def _collect_new_fills(self, result: AutoRunResult) -> None:
        try:
            fills = self.client.get_executions()
        except (KiwoomAPIError, requests.RequestException) as exc:
            self._add_throttled_error(result, "fills", f"체결 조회 실패: {exc}")
            return
        clear_error_event_bucket(self._error_notify_state, "fills")
        for fill in fills:
            key = self._fill_key(fill)
            if key in self._seen_fill_keys:
                continue
            if not fill.get("cntr_qty") or fill.get("cntr_qty") == "0":
                continue
            self._seen_fill_keys.add(key)
            result.add_event(self._format_fill_message(fill))
            self._journal_fill(fill)

    def _parse_holdings(self, *, force_refresh: bool = False) -> list[HoldingView]:
        now = time.monotonic()
        if (
            not force_refresh
            and self._holdings_cache is not None
            and now - self._holdings_cache_ts < self._holdings_cache_ttl_sec
        ):
            return self._holdings_cache

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
            current = self.client.parse_price(item.get("cur_prc", "0"))
            name = item.get("stk_nm", code)
            state = self.positions.get(code)
            entry_price = (
                state.entry_price
                if state and state.entry_price > 0
                else purchase
            )
            if entry_price > 0 and current > 0:
                computed = calc_profit_pct(entry_price, current)
                if computed is not None:
                    profit = computed
            self.positions.sync_holding(code, name, purchase, profit)
            holdings.append(
                HoldingView(
                    code=code,
                    name=name,
                    qty=qty,
                    sellable_qty=sellable,
                    profit_pct=profit,
                    current_price=current,
                    purchase_price=purchase,
                    order_code=code,
                    raw=item,
                )
            )
        tracked = self.positions.codes()
        held_codes = {h.code for h in holdings}
        for code in list(tracked):
            if code not in held_codes:
                if self._is_recent_open_lot(code):
                    continue
                self.positions.remove(code)
            elif self._should_suppress_holding_sync(code):
                self.positions.remove(code)
        self._holdings_cache = holdings
        self._holdings_cache_ts = time.monotonic()
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
        if not strategy_eod_sell_enabled or not strategy_eod_cut_loss_enabled:
            return False
        cut, _ = effective_eod_times()
        return (now or datetime.now()).time() >= parse_hhmm(cut)

    def _is_eod_sell_all_time(self, now: datetime | None = None) -> bool:
        if not strategy_eod_sell_enabled:
            return False
        _, eod = effective_eod_times()
        return (now or datetime.now()).time() >= parse_hhmm(eod)

    def _exit_needs_confirm(self, reason: str) -> bool:
        if reason.startswith("본전스탑"):
            return True
        return "수익보호 트레일링" in reason

    def _exit_confirm_key(self, reason: str) -> str:
        if "잔량 트레일링" in reason:
            return "be_remainder"
        if reason.startswith("본전스탑"):
            return "breakeven"
        if "수익보호 트레일링" in reason:
            return "protect"
        return reason

    def _exit_volume_class(
        self, code: str, reason: str | None
    ) -> tuple[str, float | None]:
        """본전스탑·수익보호만 분봉 거래량으로 light/normal/heavy 판정."""
        if not reason or not self._exit_needs_confirm(reason):
            return "normal", None
        try:
            candles = self.chart.load_minute_candles(code)
        except Exception:
            return "normal", None
        ratio = latest_vs_avg_volume_ratio(
            candles, lookback=int(strategy_swing_exit_vol_lookback)
        )
        kind = classify_exit_volume(
            ratio,
            light_ratio=float(strategy_swing_exit_vol_light_ratio),
            heavy_ratio=float(strategy_swing_exit_vol_heavy_ratio),
        )
        return kind, ratio

    def _confirm_exit_signal(
        self,
        code: str,
        reason: str | None,
        *,
        volume_class: str = "normal",
    ) -> str | None:
        """본전스탑·수익보호는 연속 N회 충족해야 청산. 손절·장마감은 즉시.

        거래량 light: 가짜 눌림으로 대기 카운트 리셋.
        거래량 heavy: 매도 압력으로 즉시 청산.
        """
        if not reason:
            self.positions.clear_exit_signal(code)
            return None
        if not self._exit_needs_confirm(reason):
            self.positions.clear_exit_signal(code)
            return reason
        if volume_class == "light":
            self.positions.clear_exit_signal(code)
            return None
        if volume_class == "heavy":
            self.positions.clear_exit_signal(code)
            return reason
        cycles = max(1, int(strategy_swing_exit_confirm_cycles))
        count = self.positions.note_exit_signal(
            code, self._exit_confirm_key(reason)
        )
        if count >= cycles:
            return reason
        return None

    def _evaluate_sell(
        self,
        holding: HoldingView,
        state: PositionState | None,
        news: MarketNewsContext | None = None,
    ) -> tuple[str | None, int, int | None]:
        profit = holding.profit_pct
        sellable = holding.sellable_qty
        if sellable <= 0:
            return None, 0, None

        mega = is_mega_cap(holding.code)
        entry_qty = getattr(state, "entry_qty", 0) if state else 0
        if entry_qty <= 0:
            entry_qty = holding.qty
        already_sold = max(0, entry_qty - holding.qty)
        stage_done = getattr(state, "tp_stage", 0) if state else 0

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

        if (
            not mega
            and strategy_other_flatten_overnight
            and self.positions.is_overnight(holding.code)
            and not (0 < profit < round_trip_cost_pct())
        ):
            return "오버나잇 금지 청산", qty, None

        if not mega and self._is_eod_sell_all_time():
            _, eod = effective_eod_times()
            if (
                is_scalping_mode()
                or strategy_swing_eod_sell_all
                or strategy_other_eod_sell_all
            ) and not (0 < profit < round_trip_cost_pct()):
                return f"장마감 전량 청산 ({eod})", qty, None
            below = float(strategy_swing_eod_sell_if_below_pct)
            if below > 0 and profit < below:
                return (
                    f"장마감 익절미달 정리 ({profit:.2f}% < +{below:.1f}%, {eod})",
                    qty,
                    None,
                )

        if not mega and self._is_eod_cut_loss_time() and profit < 0:
            cut, _ = effective_eod_times()
            return f"장마감 손실 정리 ({cut})", qty, None

        stop_pct = (
            float(strategy_stop_loss_pct)
            if mega
            else float(strategy_other_stop_loss_pct)
        )
        if profit <= -stop_pct:
            return f"손절 ({profit:.2f}% <= -{stop_pct}%)", qty, None

        if not mega:
            act = float(strategy_other_trail_activate_pct)
            dd = float(strategy_other_trail_drawdown_pct)
            if peak >= act and profit < peak - dd:
                return (
                    f"중소형 트레일링 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                    qty,
                    None,
                )
        else:
            stagnation_min = max(0, int(strategy_swing_stagnation_minutes))
            if stagnation_min > 0:
                hold_min = self.positions.holding_minutes(holding.code)
                if (
                    hold_min is not None
                    and hold_min >= stagnation_min
                    and profit < float(strategy_swing_stagnation_max_profit_pct)
                ):
                    return (
                        f"정체 청산 (보유 {hold_min:.0f}분 ≥ {stagnation_min}분, "
                        f"수익 {profit:.2f}% < "
                        f"+{strategy_swing_stagnation_max_profit_pct:.1f}%)",
                        qty,
                        None,
                    )

            if stage_done >= 1 and peak >= strategy_swing_trailing_activate_pct:
                trail_floor = peak - strategy_swing_trailing_drawdown_pct
                if profit < trail_floor:
                    return (
                        f"트레일링 스탑 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                        qty,
                        None,
                    )

            be_scaled = bool(getattr(state, "be_scaled", False)) if state else False
            if be_scaled:
                remainder_dd = float(strategy_swing_be_remainder_drawdown_pct)
                protect_floor = max(0.0, peak - remainder_dd)
                if profit < protect_floor:
                    return (
                        f"본전스탑 잔량 트레일링 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                        qty,
                        None,
                    )
            elif peak >= strategy_swing_protect_trailing_activate_pct:
                protect_floor = peak - strategy_swing_protect_trailing_drawdown_pct
                if profit < protect_floor:
                    return (
                        f"수익보호 트레일링 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                        qty,
                        None,
                    )
            if (
                not be_scaled
                and peak >= strategy_swing_breakeven_activate_pct
                and profit < strategy_swing_breakeven_floor_pct
                and profit >= round_trip_cost_pct()
            ):
                be_qty = self._calc_stage_sell_qty(
                    entry_qty, sellable, already_sold, 0.50
                )
                if be_qty > 0:
                    label = (
                        f"본전스탑 (고점 {peak:.2f}% → 현재 {profit:.2f}%)"
                        if entry_qty <= 1 or be_qty >= sellable
                        else (
                            f"본전스탑 50% 매도 (고점 {peak:.2f}% → 현재 {profit:.2f}%)"
                        )
                    )
                    return label, be_qty, None

        if news and news.defensive_mode:
            skip_overnight = (
                strategy_defensive_skip_overnight
                and not is_scalping_mode()
                and self.positions.is_overnight(holding.code)
            )
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
            if not skip_overnight and not in_grace:
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

    def _log_sell_order(
        self,
        holding: HoldingView,
        sell_qty: int,
        *,
        price: int | None,
        profit_pct: float | None,
        reason: str,
        ord_no: str,
    ) -> None:
        try:
            self.journal.log(
                "sell_order",
                code=holding.code,
                name=holding.name,
                qty=sell_qty,
                price=price,
                profit_pct=profit_pct,
                reason=reason,
                ord_no=ord_no,
            )
        except Exception:
            pass

    def latest_fill_price(self, ord_no: str) -> int | None:
        """최근 저널 체결가 (수동매수 등 주문가 보완)."""
        if not ord_no:
            return None
        for event in reversed(self.journal.tail(40)):
            if (
                event.event == "fill"
                and str(event.ord_no) == str(ord_no)
                and event.price
            ):
                return int(event.price)
        return None

    def _execute_sell(
        self,
        holding: HoldingView,
        reason: str,
        sell_qty: int,
        result: AutoRunResult,
        *,
        partial: bool = False,
        tp_stage: int | None = None,
        be_scaled: bool = False,
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
            limit_price = (
                None
                if self._exit_uses_market(reason)
                else self._exit_limit_price(holding)
            )

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
            state = self.positions.get(holding.code)
            entry_price = (
                state.entry_price
                if state and state.entry_price > 0
                else holding.purchase_price
            )
            sell_price = holding.current_price or 0
            profit_pct = holding.profit_pct
            if entry_price > 0 and sell_price > 0:
                computed = calc_profit_pct(entry_price, sell_price)
                if computed is not None:
                    profit_pct = computed
            self._log_sell_order(
                holding,
                sell_qty,
                price=sell_price or None,
                profit_pct=profit_pct,
                reason=reason + (f" / 지정가 {limit_price}" if limit_price else ""),
                ord_no=ord_no,
            )
            result.add_event(
                "【자동매도】\n"
                f"사유: {reason}\n"
                f"종목: {holding.name}({holding.code})\n"
                f"수량: {sell_qty}주 / 매매가능 {holding.sellable_qty}주\n"
                f"수익률: {profit_pct:+.2f}%\n"
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
            if be_scaled:
                self.positions.mark_be_scaled(holding.code)
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
                    state = self.positions.get(holding.code)
                    entry_price = (
                        state.entry_price
                        if state and state.entry_price > 0
                        else holding.purchase_price
                    )
                    profit_pct = holding.profit_pct
                    if entry_price > 0 and holding.current_price > 0:
                        computed = calc_profit_pct(entry_price, holding.current_price)
                        if computed is not None:
                            profit_pct = computed
                    self._log_sell_order(
                        holding,
                        sell_qty,
                        price=holding.current_price or None,
                        profit_pct=profit_pct,
                        reason=f"{reason} / 지정가 실패 → 시장가",
                        ord_no=ord_no,
                    )
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
                    if partial:
                        self.positions.mark_partial_sold(holding.code)
                    if tp_stage is not None:
                        self.positions.mark_tp_stage(holding.code, tp_stage)
                    if be_scaled:
                        self.positions.mark_be_scaled(holding.code)
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
        *,
        holdings: list[HoldingView] | None = None,
    ) -> int:
        sold_count = 0
        try:
            if holdings is None:
                holdings = self._parse_holdings()
            clear_error_event_bucket(self._error_notify_state, "holdings_sell")
        except (KiwoomAPIError, requests.RequestException) as exc:
            self._add_throttled_error(result, "holdings_sell", f"잔고 조회 실패(매도): {exc}")
            return 0

        for holding in holdings:
            state = self.positions.get(holding.code)
            reason, sell_qty, tp_stage = self._evaluate_sell(
                holding, state, news
            )
            vol_class, vol_ratio = self._exit_volume_class(holding.code, reason)
            if reason and vol_class == "heavy" and vol_ratio is not None:
                reason = f"{reason} · 거래량 {vol_ratio:.1f}x"
            confirmed = self._confirm_exit_signal(
                holding.code, reason, volume_class=vol_class
            )
            if reason and not confirmed:
                wait = "한 번 더 확인"
                if vol_class == "light" and vol_ratio is not None:
                    wait = f"거래량 부족 ({vol_ratio:.2f}x)"
                result.add_report(
                    f"【청산 대기】 {holding.name}({holding.code}) "
                    f"{wait} · {reason}"
                )
                continue
            if not confirmed:
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
                mark_be = is_partial and reason.startswith("본전스탑")
                if self._execute_sell(
                    holding,
                    reason,
                    sell_qty,
                    result,
                    partial=is_partial,
                    tp_stage=tp_stage,
                    be_scaled=mark_be,
                ):
                    sold_count += 1
                    self._invalidate_holdings_cache()
                    self.positions.clear_exit_signal(holding.code)
        return sold_count

    def _portfolio_heat_blocks_buy(self, holdings: list[HoldingView]) -> str | None:
        heat_limit, heat_pct = effective_portfolio_heat()
        losers = [h for h in holdings if h.profit_pct <= heat_pct]
        if len(losers) >= heat_limit:
            names = ", ".join(h.name for h in losers[:3])
            return f"손실 종목 {len(losers)}개 ({names}) - 신규매수 중단"
        return None

    def _try_addon_buys(
        self,
        result: AutoRunResult,
        holdings: list[HoldingView],
        candidates: list[CandidateView],
    ) -> None:
        """보유 종목 중 우량·모멘텀 + 진입가 하락 시 추가매수."""
        if not position_addon_enabled or is_scalping_mode() or not holdings:
            return
        snap = self._cycle_ctx.regime if self._cycle_ctx else None
        if snap and not is_channel_allowed(snap, "addon"):
            if not chart_primary_mode:
                return

        loss_blocked = self._recent_loss_blocked_codes()
        by_code = {c.code: c for c in candidates}

        for holding in sorted(holdings, key=lambda h: h.profit_pct):
            if not self._can_addon_buy_today(holding.code):
                continue
            if holding.code in loss_blocked:
                continue
            if holding.sellable_qty <= 0 and holding.qty > 0:
                continue

            candidate = by_code.get(holding.code)
            if candidate is None:
                continue

            state = self.positions.get(holding.code)
            peak = state.peak_profit_pct if state else holding.profit_pct
            ok, tag = qualifies_for_position_addon(
                candidate=candidate,
                holding_profit_pct=holding.profit_pct,
                peak_profit_pct=peak,
                min_drop_pct=position_addon_min_drop_pct,
                quality_max_rank=position_addon_quality_max_rank,
                momentum_min_peak_pct=position_addon_momentum_min_peak_pct,
            )
            if not ok:
                continue

            chart = self.chart.evaluate(
                code=holding.code,
                current_price=holding.current_price,
                mode="pullback",
            )
            if chart_filter_enabled and not chart.passed:
                continue

            baseline_qty = max(
                (state.entry_qty if state else 0),
                holding.qty,
                1,
            )
            order_qty = self._calc_order_qty(holding.current_price, channel="addon")
            max_total = int(baseline_qty * position_addon_max_qty_multiplier)
            max_total = min(max_total, int(position_max_qty))
            if holding.qty + order_qty > max_total:
                order_qty = max(0, max_total - holding.qty)
            if order_qty <= 0:
                continue

            self._execute_addon_buy(
                holding,
                candidate,
                order_qty,
                tag,
                chart,
                result,
            )
            self._invalidate_holdings_cache()
            return

    def _execute_addon_buy(
        self,
        holding: HoldingView,
        candidate: CandidateView,
        order_qty: int,
        tag: str,
        chart: ChartSignalResult,
        result: AutoRunResult,
    ) -> None:
        try:
            order = self.client.buy_market(
                holding.code,
                order_qty,
                dmst_stex_tp=dmst_stex_tp,
            )
            self._record_addon_buy(holding.code)
            ord_no = order.get("ord_no", "")
            self.positions.add_to_position(
                holding.code,
                order_qty,
                holding.current_price,
                profit_pct=holding.profit_pct,
            )
            reason = self._merge_buy_reason(
                "addon",
                (
                    f"추가매수({tag}) 진입대비 {holding.profit_pct:+.2f}% · "
                    f"{candidate.rank}위"
                ),
            )
            if chart.reasons:
                reason += f" / 차트 {chart.score:.0f} ({', '.join(chart.reasons)})"
            try:
                self.journal.log(
                    "addon_buy_order",
                    code=holding.code,
                    name=holding.name,
                    qty=order_qty,
                    price=holding.current_price,
                    reason=reason,
                    ord_no=ord_no,
                )
            except Exception:
                pass
            buy_msg = (
                "【추가 매수】\n"
                f"종목: {holding.name}({holding.code})\n"
                f"유형: {tag} · 진입대비 {holding.profit_pct:+.2f}%\n"
                f"거래대금 {candidate.rank}위 · 등락 {candidate.flu_rt:+.2f}%\n"
                f"수량: {order_qty}주 시장가 (보유 {holding.qty}→{holding.qty + order_qty}주)\n"
                f"주문번호: {ord_no}\n"
                f"{order.get('return_msg', '')}"
            )
            result.add_event(buy_msg)
            fill_msg = self.check_order_fill(
                ord_no, holding.code, stk_nm=holding.name
            )
            if fill_msg and is_event_message(fill_msg):
                result.add_event(fill_msg)
            elif fill_msg:
                result.add_report(fill_msg)
        except KiwoomAPIError as exc:
            result.add_event(
                f"【추가매수 실패】 {holding.name}({holding.code})\n{exc}"
            )
        except requests.RequestException as exc:
            result.add_event(
                f"【추가매수 실패】 {holding.name}\n네트워크: {exc}"
            )

    def _blocked_buy_codes(self, holdings: list[HoldingView]) -> set[str]:
        """키움 잔고 + 방금 등록한 미체결 로트. 디스크에서 다시 읽어 다른 프로세스 주문을 본다."""
        try:
            self.positions.load()
        except Exception:
            pass
        codes = {h.code for h in holdings}
        codes.update(self.positions.codes())
        return codes

    def _news_blocks_new_buys(self, news: MarketNewsContext | None) -> str | None:
        if news is None:
            return None
        if news.defensive_mode:
            return (
                f"방어모드 - 신규매수 중단 "
                f"(심리 {news.sentiment:+.2f})"
            )
        return None

    def _run_buy_phase(
        self,
        result: AutoRunResult,
        holdings: list[HoldingView],
        news: MarketNewsContext | None = None,
        *,
        candidates: list[CandidateView] | None = None,
    ) -> None:
        held_codes = self._blocked_buy_codes(holdings)
        snap = self._cycle_ctx.regime if self._cycle_ctx else None
        channel_pullback = is_channel_allowed(snap, "pullback")
        channel_momentum = is_channel_allowed(snap, "momentum")

        blocked = self._news_blocks_new_buys(news)
        if blocked:
            result.add_report(self._heartbeat(blocked))
            return

        # 뉴스 1순위 하드게이트는 레거시 모드에서만. 차순위는 점수 단계에서 반영.
        if (
            news
            and not news.allow_buy
            and not news_filter_secondary
        ):
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

        scan_top = scalping_scan_rank_top if is_scalping_mode() else strategy_scan_rank_top

        if candidates is None:
            try:
                rank_items = self.client.get_trade_value_rank(top_n=scan_top)
                candidates = self._parse_candidates(rank_items)
            except (KiwoomAPIError, requests.RequestException) as exc:
                result.add_report(self._heartbeat(f"순위 조회 실패 - {exc}"))
                return

        if position_addon_enabled and not is_scalping_mode():
            self._try_addon_buys(result, holdings, candidates)

        max_pos = effective_max_positions()
        if len(holdings) >= max_pos:
            result.add_report(
                self._heartbeat(f"보유 한도 ({len(holdings)}/{max_pos})")
            )
            return

        heat = self._portfolio_heat_blocks_buy(holdings)
        if heat:
            result.add_report(self._heartbeat(heat))
            return

        # 차트 우선: 국면·점수·뉴스는 참고. 심리 ≤ news_block_buy_sentiment 는 매수 중단.
        if chart_primary_mode and not is_scalping_mode():
            self._run_chart_primary_buy(
                result,
                holdings,
                news,
                candidates=candidates,
                held_codes=held_codes,
                snap=snap,
            )
            return

        if is_scalping_mode():
            if not channel_pullback:
                result.add_report(
                    self._heartbeat(
                        f"국면 {snap.label if snap else '—'} - 스캘핑 매수 채널 OFF"
                    )
                )
                return
        else:
            momentum_window = (
                strategy_momentum_buy_enabled
                and datetime.now().time()
                <= parse_hhmm(strategy_momentum_window_end)
            )
            allow_momentum = momentum_window and channel_momentum
            if not channel_pullback and not allow_momentum:
                result.add_report(
                    self._heartbeat(
                        f"국면 {snap.label if snap else '—'} - 일반매수 채널 OFF"
                    )
                )
                return

        min_score = scalping_min_score if is_scalping_mode() else strategy_min_score

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

        self.chart.prune_stale_cache()

        if is_scalping_mode():
            eligible, rejected = filter_fn(candidates, held_codes)
        else:
            # 아침 모멘텀 채널: 지정 시각까지 러너 프로필(상승 중+순위 급등) 허용
            allow_momentum = (
                strategy_momentum_buy_enabled
                and channel_momentum
                and datetime.now().time()
                <= parse_hhmm(strategy_momentum_window_end)
            )
            eligible, rejected = filter_and_rank_candidates(
                candidates, held_codes, allow_momentum=allow_momentum
            )
            if not channel_pullback:
                eligible = [
                    (cand, score)
                    for cand, score in eligible
                    if is_momentum_candidate(cand)
                ]
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

        # 최근 손실 청산 종목 재진입 차단 (반복 손실 방지)
        loss_blocked = self._recent_loss_blocked_codes()
        if loss_blocked:
            blocked_notes: list[str] = []
            filtered = []
            for cand, score in eligible:
                note = loss_blocked.get(cand.code)
                if note:
                    blocked_notes.append(f"{cand.name}({cand.code}) {note}")
                    continue
                filtered.append((cand, score))
            if not filtered:
                note = blocked_notes[0] if blocked_notes else "손실 쿨다운"
                result.add_report(self._heartbeat(f"손실 재진입 차단 - {note}"))
                return
            eligible = filtered

        orb_filtered = self._apply_orb_morning_filter(eligible, result)
        if orb_filtered is None:
            return
        eligible = orb_filtered

        allow_momentum = (
            not is_scalping_mode()
            and strategy_momentum_buy_enabled
            and channel_momentum
            and datetime.now().time() <= parse_hhmm(strategy_momentum_window_end)
        )
        picked = self._pick_with_chart_filter(
            eligible,
            allow_momentum=allow_momentum,
            channel_pullback=channel_pullback,
        )
        if picked is None:
            if chart_filter_enabled:
                result.add_report(
                    self._heartbeat("차트 필터 - 조건 충족 종목 없음")
                )
            else:
                result.add_report(self._heartbeat("매수 보류 - 조건 충족 없음"))
            return

        best, adjusted, chart_result = picked
        hard_stop, adjusted, news_gate_note = news_score_gate(
            base_score=adjusted,
            news=news,
            min_score=min_score,
        )
        if hard_stop:
            result.add_report(self._heartbeat(news_gate_note or "뉴스 극단 부정 중단"))
            return
        # 부정 뉴스일 때는 점수 완화 없음 (저품질·레버리지 종목 유입 방지)
        if news and news.sentiment <= strategy_weak_market_sentiment:
            effective_min = max(0.0, min_score)
        else:
            effective_min = max(0.0, min_score - 3.0)
        if adjusted < effective_min:
            detail = (
                f"점수 부족 - {best.name} {adjusted:.1f} < {effective_min:.1f}점"
            )
            if news_gate_note:
                detail = f"{detail} ({news_gate_note})"
            result.add_report(self._heartbeat(detail))
            return

        news_note = ""
        if news:
            news_note = f"뉴스심리 {news.sentiment:+.2f} 리스크 {news.risk_score:.2f}"
            if news_gate_note:
                news_note = f"{news_note} · {news_gate_note}"
        chart_note = ""
        if chart_filter_enabled and chart_result.reasons:
            chart_note = f"차트 {chart_result.score:.0f}점 ({', '.join(chart_result.reasons)})"
        if not is_scalping_mode() and is_momentum_candidate(best):
            market_msg = f"{market_msg} / 모멘텀 ({best.flu_rt:+.2f}%, 순위 {best.prev_rank}→{best.rank})"
        if chart_note:
            market_msg = f"{market_msg} / {chart_note}"
        buy_channel = (
            "momentum"
            if not is_scalping_mode() and is_momentum_candidate(best)
            else "pullback"
        )
        market_msg = self._merge_buy_reason(buy_channel, market_msg)
        self._execute_buy(
            best, adjusted, market_msg, result, news_note, channel=buy_channel
        )

    def _run_chart_primary_buy(
        self,
        result: AutoRunResult,
        holdings: list[HoldingView],
        news: MarketNewsContext | None,
        *,
        candidates: list[CandidateView],
        held_codes: set[str],
        snap,
    ) -> None:
        """차트 우선 매수: 차트 통과가 본결정. 급등·국면·오전 외 모멘텀은 차단."""
        self.chart.prune_stale_cache()
        allow_momentum, allow_pullback = chart_primary_channel_flags(
            snap,
            in_morning=self._in_morning_buy_window(),
        )
        if not allow_momentum and not allow_pullback:
            result.add_report(
                self._heartbeat("차트우선 - 국면/시간상 채널 없음")
            )
            return

        universe, rejected = filter_chart_primary_universe(
            candidates,
            held_codes,
            block_etf=strategy_block_etf,
            block_leveraged_etf=strategy_block_leveraged_etf,
        )
        if not universe:
            detail = rejected[0] if rejected else "후보 없음"
            result.add_report(self._heartbeat(f"차트우선 - {detail}"))
            return

        cooldown_min = (
            scalping_reentry_cooldown_minutes
            if is_scalping_mode()
            else strategy_reentry_cooldown_minutes
        )
        if cooldown_min > 0:
            cooled: list[str] = []
            kept: list[CandidateView] = []
            for cand in universe:
                since = self.positions.cooldown_minutes_since_exit(cand.code)
                if since is not None and since < cooldown_min:
                    cooled.append(
                        f"{cand.name}({cand.code}) {since:.0f}분 < {cooldown_min}분"
                    )
                    continue
                kept.append(cand)
            if not kept:
                note = cooled[0] if cooled else "쿨다운"
                result.add_report(self._heartbeat(f"재진입 쿨다운 - {note}"))
                return
            universe = kept

        market_note = advisory_market_note(candidates)
        regime_note = ""
        if snap is not None:
            regime_note = getattr(snap, "message", "") or getattr(snap, "label", "")
        news_msg = ""
        if news:
            news_msg = f"심리 {news.sentiment:+.2f}, 리스크 {news.risk_score:.2f}"

        result.add_report(
            self._heartbeat(
                f"차트우선 점검 (후보 {len(universe)} · {market_note}"
                + (f" · {regime_note}" if regime_note else "")
                + ")"
            )
        )

        picked = self._pick_chart_primary(
            universe,
            allow_momentum=allow_momentum,
            allow_pullback=allow_pullback,
        )
        if picked is None:
            result.add_report(
                self._heartbeat(
                    f"차트 미통과 - 평가 {min(len(universe), int(chart_primary_eval_max_candidates))}종목"
                )
            )
            return

        best, adjusted, chart_result, used_momentum = picked
        hard_stop, adjusted, news_gate_note = news_score_gate(
            base_score=adjusted,
            news=news,
            min_score=0.0,
        )
        if hard_stop:
            result.add_report(
                self._heartbeat(news_gate_note or "차트우선 - 뉴스 심리 중단")
            )
            return
        strat_score = advisory_strategy_score(best, momentum=used_momentum)
        advisory = build_buy_advisory_notes(
            candidate=best,
            market_msg=market_note,
            regime_msg=regime_note,
            news_msg=news_msg,
            strategy_score=strat_score,
            strategy_min_score=float(strategy_min_score),
        )
        chart_note = (
            f"차트 {chart_result.score:.0f}점"
            f" (≥{chart_min_score:.0f}, {', '.join(chart_result.reasons) or '통과'})"
        )
        buy_channel = "momentum" if used_momentum else "pullback"
        reason = self._merge_buy_reason(
            buy_channel,
            f"{chart_note} · {advisory}",
        )
        if news_gate_note:
            reason = f"{reason} · {news_gate_note}"
        news_note = news_msg
        if news_gate_note:
            news_note = f"{news_note} · {news_gate_note}".strip(" ·")
        self._execute_buy(
            best, adjusted, reason, result, news_note, channel=buy_channel
        )

    def _run_crash_buy_phase(
        self,
        result: AutoRunResult,
        holdings: list[HoldingView],
        news: MarketNewsContext | None = None,
        *,
        candidates: list[CandidateView] | None = None,
    ) -> None:
        """하락장에서 거래대금 상위 개별주 급락 구간 매수."""
        if is_scalping_mode() or not strategy_crash_buy_enabled:
            return
        snap = self._cycle_ctx.regime if self._cycle_ctx else None
        if snap and not is_channel_allowed(snap, "crash"):
            return
        if self._daily_loss_blocks_buy() or self._loss_circuit_blocks_buy():
            return
        if self._news_blocks_new_buys(news):
            return
        if news and not news.allow_buy and not news_filter_secondary and not chart_primary_mode:
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

        held_codes = self._blocked_buy_codes(holdings)
        if candidates is None:
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

        loss_blocked = self._recent_loss_blocked_codes()
        if loss_blocked:
            eligible = [
                (cand, score)
                for cand, score in eligible
                if cand.code not in loss_blocked
            ]
            if not eligible:
                result.add_report(
                    self._heartbeat("급락매수 보류 - 최근 손실 종목 차단")
                )
                return

        best, score = eligible[0]
        news_note = ""
        if news:
            news_note = f"뉴스심리 {news.sentiment:+.2f} 리스크 {news.risk_score:.2f}"
        detail = f"{market_msg} · 급락 {best.flu_rt:+.2f}%"
        self._execute_crash_buy(
            best, score, self._merge_buy_reason("crash", detail), result, news_note
        )

    def _execute_crash_buy(
        self,
        candidate: CandidateView,
        score: float,
        market_msg: str,
        result: AutoRunResult,
        news_note: str = "",
    ) -> None:
        try:
            order_qty = self._calc_order_qty(candidate.current_price, channel="crash")
            if order_qty <= 0:
                result.add_report(
                    f"수량 0 스킵 - {candidate.name}({candidate.code}) "
                    f"1주가 목표 {position_target_krw:,}원 초과"
                )
                return
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
            reason = market_msg
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
        snap = self._cycle_ctx.regime if self._cycle_ctx else None
        if snap and not is_channel_allowed(snap, "trend"):
            return
        if self._daily_loss_blocks_buy() or self._loss_circuit_blocks_buy():
            return
        if self._news_blocks_new_buys(news):
            return
        if news and not news.allow_buy and not news_filter_secondary and not chart_primary_mode:
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

        held = self._blocked_buy_codes(holdings)
        scan = self.trends.scan()
        if not scan.active_trends or not scan.picks:
            return

        loss_blocked = self._recent_loss_blocked_codes()
        for pick in scan.picks:
            if pick.code in held:
                continue
            if pick.code in loss_blocked:
                continue
            if strategy_block_etf and is_etf(pick.name, pick.code):
                continue
            if (
                not strategy_block_etf
                and strategy_block_leveraged_etf
                and is_leveraged_etf(pick.name, pick.code)
            ):
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
            chart = self.chart.evaluate(
                code=pick.code,
                current_price=pick.current_price,
                mode="pullback",
            )
            if chart_filter_enabled and not chart.passed:
                result.add_report(
                    self._heartbeat(
                        f"트렌드 차트 보류 - {pick.name}: {chart.reject_reason}"
                    )
                )
                continue
            self._execute_trend_buy(pick, result, chart)
            result.add_report(
                self._heartbeat(
                    f"트렌드 매수 - {pick.name}",
                    f"[{pick.theme_name}] {pick.flu_rt:+.2f}%",
                )
            )
            return

    def _execute_trend_buy(
        self,
        pick: TrendPick,
        result: AutoRunResult,
        chart: ChartSignalResult | None = None,
    ) -> None:
        try:
            order_qty = self._calc_order_qty(pick.current_price, channel="trend")
            if order_qty <= 0:
                result.add_report(
                    f"수량 0 스킵 - {pick.name}({pick.code}) "
                    f"1주가 목표 {position_target_krw:,}원 초과"
                )
                return
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
            reason = self._merge_buy_reason(
                "trend", f"[{pick.theme_name}] {pick.reason}"
            )
            if chart and chart.reasons:
                reason += f" / 차트 {chart.score:.0f} ({', '.join(chart.reasons)})"
            try:
                self.journal.log(
                    "trend_buy_order",
                    code=pick.code,
                    name=pick.name,
                    qty=order_qty,
                    price=pick.current_price,
                    reason=reason,
                    ord_no=ord_no,
                )
            except Exception:
                pass
            msg = (
                "【트렌드 매수】\n"
                f"테마: {pick.theme_name}\n"
                f"종목: {pick.name}({pick.code})\n"
                f"등락률: {pick.flu_rt:+.2f}% · {pick.current_price:,}원\n"
                f"점수: {pick.score:.1f} · {reason}\n"
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
        *,
        channel: str = "pullback",
    ) -> None:
        try:
            order_qty = self._calc_order_qty(
                candidate.current_price, channel=channel
            )
            if order_qty <= 0:
                result.add_report(
                    f"수량 0 스킵 - {candidate.name}({candidate.code}) "
                    f"1주가 목표 {position_target_krw:,}원 초과"
                )
                return
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
                if state.be_scaled:
                    tags.append("본전스케일")
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
            # (키워드 리스크 점수와 무관 — 지정학 RSS 노이즈 대응)
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
                    changed, notes = apply_bullish_news_override(
                        news_ctx, strong_market=strong_market
                    )
                    if changed:
                        note = "강세장 감지 → 뉴스 override (" + ", ".join(notes) + ")"
                        news_ctx.error = f"{news_ctx.error} | {note}".strip(" |")
                except (KiwoomAPIError, requests.RequestException):
                    pass

            try:
                holdings = self._parse_holdings()
                clear_error_event_bucket(self._error_notify_state, "holdings")
            except (KiwoomAPIError, requests.RequestException) as exc:
                self._add_throttled_error(result, "holdings", f"잔고 조회 실패: {exc}")
                holdings = None

            if holdings is not None:
                sold_count = self._run_sell_phase(result, news_ctx, holdings=holdings)
                if sold_count > 0:
                    self._invalidate_holdings_cache()
                    try:
                        holdings = self._parse_holdings(force_refresh=True)
                    except (KiwoomAPIError, requests.RequestException) as exc:
                        result.add_event(f"잔고 오류: {exc}")
                        holdings = []
                try:
                    cycle_ctx = self._resolve_cycle_context(news_ctx)
                    if cycle_ctx.regime:
                        result.add_report(
                            self._heartbeat(f"국면 - {cycle_ctx.regime.message}")
                        )
                    if cycle_ctx.drawdown and drawdown_scale_enabled:
                        result.add_report(
                            self._heartbeat(f"스케일 - {cycle_ctx.drawdown.message}")
                        )
                    shared = cycle_ctx.candidates
                    self._run_buy_phase(
                        result, holdings, news_ctx, candidates=shared
                    )
                    self._run_crash_buy_phase(
                        result, holdings, news_ctx, candidates=shared
                    )
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
