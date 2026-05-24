from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

from config.config import (
    auto_max_buys_per_day,
    default_order_qty,
    dmst_stex_tp,
    fill_poll_interval_sec,
    fill_poll_wait_sec,
    news_defensive_loss_pct,
    news_enabled,
    strategy_breakeven_activate_pct,
    strategy_breakeven_floor_pct,
    strategy_buy_afternoon_end,
    strategy_buy_afternoon_start,
    strategy_buy_morning_end,
    strategy_buy_morning_start,
    strategy_eod_cut_loss_time,
    strategy_eod_sell_enabled,
    strategy_eod_sell_time,
    strategy_max_positions,
    strategy_min_score,
    strategy_partial_sell_ratio,
    strategy_portfolio_heat_limit,
    strategy_portfolio_heat_pct,
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
)
from trading.trend_scanner import TrendPick, TrendScanner

# 텔레그램 자동 알림 대상 (이벤트만)
EVENT_PREFIXES = (
    "【체결",
    "【자동매수",
    "【트렌드 매수",
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
        self._seen_fill_keys: set[str] = set()
        self.positions = PositionTracker()
        self.news = MarketNewsAnalyzer()
        self.trends = TrendScanner(client)

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def get_rules_summary(self) -> str:
        return (
            "【매매 전략 v3】\n\n"
            "■ 매도 (보유 점검 우선)\n"
            f"  · 1차 익절: +{strategy_take_profit_partial_pct}% → "
            f"{int(strategy_partial_sell_ratio * 100)}% 물량 매도\n"
            f"  · 최종 익절: +{strategy_take_profit_pct}% → 전량 매도\n"
            f"  · 손절: -{strategy_stop_loss_pct}% → 전량 매도\n"
            f"  · 트레일링/본전스탑/방어모드/장마감 청산\n"
            "  · 종목코드 A005930 형식 → 005930 변환 후 주문\n\n"
            "■ 매수: 거래대금·점수·뉴스 필터\n"
            "■ 트렌드: 글로벌 핫테마 + 연관종목 눌림목 매수\n"
            "  · /trend 소개 · /trend buy 수동매수\n\n"
            "■ 알림\n"
            "  · /auto on: 체결·매수·매도·실패만 자동 알림\n"
            "  · /report: 뉴스·잔고·점검 수동 리포트"
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
            return intro + f"\n\n일일 매수 한도 도달 ({auto_max_buys_per_day}회)"

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
        lines.append(
            self._heartbeat(
                "수동 리포트",
                f"자동매매 {'ON' if self.enabled else 'OFF'}",
            )
        )
        return "\n\n".join(lines)

    def _reset_daily_counter(self) -> None:
        today = date.today()
        if self._buy_count_date != today:
            self._buy_count_date = today
            self._buy_count = 0

    def _can_buy_today(self) -> bool:
        self._reset_daily_counter()
        return self._buy_count < auto_max_buys_per_day

    def _record_buy(self) -> None:
        self._reset_daily_counter()
        self._buy_count += 1

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
        for code in list(tracked):
            if code not in {h.code for h in holdings}:
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
        return (now or datetime.now()).time() >= parse_hhmm(strategy_eod_cut_loss_time)

    def _is_eod_sell_all_time(self, now: datetime | None = None) -> bool:
        if not strategy_eod_sell_enabled:
            return False
        return (now or datetime.now()).time() >= parse_hhmm(strategy_eod_sell_time)

    def _evaluate_sell(
        self,
        holding: HoldingView,
        state: PositionState | None,
        news: MarketNewsContext | None = None,
    ) -> tuple[str | None, int]:
        profit = holding.profit_pct
        sellable = holding.sellable_qty
        if sellable <= 0:
            return None, 0

        qty = sellable
        peak = state.peak_profit_pct if state else profit
        partial_sold = state.partial_sold if state else False

        if self._is_eod_sell_all_time():
            return f"장마감 전량 청산 ({strategy_eod_sell_time})", qty

        if self._is_eod_cut_loss_time() and profit < 0:
            return f"장마감 손실 정리 ({strategy_eod_cut_loss_time})", qty

        if profit <= -strategy_stop_loss_pct:
            return f"손절 ({profit:.2f}% <= -{strategy_stop_loss_pct}%)", qty

        if profit >= strategy_take_profit_pct:
            return f"최종 익절 (+{profit:.2f}% >= +{strategy_take_profit_pct}%)", qty

        if (
            not partial_sold
            and profit >= strategy_take_profit_partial_pct
            and qty >= 2
        ):
            sell_qty = max(1, min(int(qty * strategy_partial_sell_ratio), qty))
            return (
                f"1차 익절 (+{profit:.2f}% >= +{strategy_take_profit_partial_pct}%)",
                sell_qty,
            )

        if peak >= strategy_trailing_activate_pct:
            trail_floor = peak - strategy_trailing_drawdown_pct
            if profit < trail_floor:
                return (
                    f"트레일링 스탑 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                    qty,
                )

        if peak >= strategy_breakeven_activate_pct:
            if profit < strategy_breakeven_floor_pct:
                return (
                    f"본전 스탑 (고점 {peak:.2f}% → 현재 {profit:.2f}%)",
                    qty,
                )

        if news and news.defensive_mode:
            if profit <= news_defensive_loss_pct:
                return (
                    f"방어모드 매도 (뉴스 악화, 수익 {profit:.2f}%)",
                    qty,
                )
            if peak >= 1.0 and profit < peak - 0.8:
                return (
                    f"방어모드 트레일링 (리스크 {news.risk_score:.2f})",
                    qty,
                )

        return None, 0

    def _execute_sell(
        self,
        holding: HoldingView,
        reason: str,
        sell_qty: int,
        result: AutoRunResult,
        *,
        partial: bool = False,
    ) -> bool:
        sell_qty = min(sell_qty, holding.sellable_qty)
        if sell_qty <= 0:
            result.add_event(
                "【매도 불가】\n"
                f"종목: {holding.name}({holding.code})\n"
                f"사유: {reason}\n"
                f"매매가능수량 0주 (결제·미체결 대기 가능)"
            )
            return False

        try:
            order = self.client.sell_market(
                holding.order_code,
                sell_qty,
                dmst_stex_tp=dmst_stex_tp,
            )
            ord_no = order.get("ord_no", "")
            result.add_event(
                "【자동매도】\n"
                f"사유: {reason}\n"
                f"종목: {holding.name}({holding.code})\n"
                f"수량: {sell_qty}주 / 매매가능 {holding.sellable_qty}주\n"
                f"수익률: {holding.profit_pct:+.2f}%\n"
                f"주문번호: {ord_no}\n"
                f"{order.get('return_msg', '')}"
            )
            fill_msg = self.check_order_fill(
                ord_no,
                holding.order_code,
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
            if sell_qty >= holding.sellable_qty:
                self.positions.remove(holding.code)
            return True
        except KiwoomAPIError as exc:
            result.add_event(
                "【매도 실패】\n"
                f"종목: {holding.name}({holding.code})\n"
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

        for holding in holdings:
            state = self.positions.get(holding.code)
            reason, sell_qty = self._evaluate_sell(holding, state, news)

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
                is_partial = "1차 익절" in reason and sell_qty < holding.sellable_qty
                if self._execute_sell(
                    holding, reason, sell_qty, result, partial=is_partial
                ):
                    sold_count += 1
        return sold_count

    def _portfolio_heat_blocks_buy(self, holdings: list[HoldingView]) -> str | None:
        losers = [
            h for h in holdings if h.profit_pct <= strategy_portfolio_heat_pct
        ]
        if len(losers) >= strategy_portfolio_heat_limit:
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

        if len(holdings) >= strategy_max_positions:
            result.add_report(
                self._heartbeat(f"보유 한도 ({len(holdings)}/{strategy_max_positions})")
            )
            return

        if not self._can_buy_today():
            result.add_report(self._heartbeat(f"일일 매수 한도 ({auto_max_buys_per_day}회)"))
            return

        if not is_buy_window(
            strategy_buy_morning_start,
            strategy_buy_morning_end,
            strategy_buy_afternoon_start,
            strategy_buy_afternoon_end,
        ):
            result.add_report(
                self._heartbeat(
                    f"매수시간 외 "
                    f"({strategy_buy_morning_start}~{strategy_buy_morning_end}, "
                    f"{strategy_buy_afternoon_start}~{strategy_buy_afternoon_end})"
                )
            )
            return

        heat = self._portfolio_heat_blocks_buy(holdings)
        if heat:
            result.add_report(self._heartbeat(heat))
            return

        try:
            rank_items = self.client.get_trade_value_rank(
                top_n=strategy_scan_rank_top,
            )
            candidates = self._parse_candidates(rank_items)
        except (KiwoomAPIError, requests.RequestException) as exc:
            result.add_report(self._heartbeat(f"순위 조회 실패 - {exc}"))
            return

        bullish, market_msg = is_market_bullish(candidates)
        if not bullish:
            result.add_report(self._heartbeat(f"매수 보류 - {market_msg}"))
            return

        eligible, rejected = filter_and_rank_candidates(candidates, held_codes)
        if not eligible:
            detail = rejected[0] if rejected else "조건 충족 없음"
            result.add_report(self._heartbeat(f"매수 보류 - {detail}"))
            return

        best, score = eligible[0]
        news_adj = news.score_adjustment if news else 0.0
        adjusted = score + news_adj
        if adjusted < strategy_min_score:
            result.add_report(
                self._heartbeat(
                    f"점수 부족 - {best.name} {adjusted:.1f} < {strategy_min_score}점"
                )
            )
            return

        news_note = ""
        if news:
            news_note = f"뉴스심리 {news.sentiment:+.2f} 리스크 {news.risk_score:.2f}"
        self._execute_buy(best, adjusted, market_msg, result, news_note)

    def _run_trend_buy_phase(
        self,
        result: AutoRunResult,
        holdings: list[HoldingView],
        news: MarketNewsContext | None = None,
    ) -> None:
        if not trend_auto_buy_enabled:
            return
        if news and not news.allow_buy:
            return
        if len(holdings) >= strategy_max_positions:
            return
        if not self._can_buy_today():
            return
        if not is_buy_window(
            strategy_buy_morning_start,
            strategy_buy_morning_end,
            strategy_buy_afternoon_start,
            strategy_buy_afternoon_end,
        ):
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
            order = self.client.buy_market(
                pick.code,
                default_order_qty,
                dmst_stex_tp=dmst_stex_tp,
            )
            self._record_buy()
            ord_no = order.get("ord_no", "")
            self.positions.register(pick.code, pick.name, pick.current_price)
            msg = (
                "【트렌드 매수】\n"
                f"테마: {pick.theme_name}\n"
                f"종목: {pick.name}({pick.code})\n"
                f"등락률: {pick.flu_rt:+.2f}% · {pick.current_price:,}원\n"
                f"점수: {pick.score:.1f} · {pick.reason}\n"
                f"수량: {default_order_qty}주 시장가\n"
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
            order = self.client.buy_market(
                candidate.code,
                default_order_qty,
                dmst_stex_tp=dmst_stex_tp,
            )
            self._record_buy()
            ord_no = order.get("ord_no", "")
            self.positions.register(
                candidate.code,
                candidate.name,
                candidate.current_price,
            )
            buy_msg = (
                "【자동매수】\n"
                f"종목: {candidate.name}({candidate.code})\n"
                f"점수: {score:.1f}점 · {market_msg}\n"
            )
            if news_note:
                buy_msg += f"뉴스: {news_note}\n"
            buy_msg += (
                f"순위: {candidate.prev_rank}→{candidate.rank}위\n"
                f"등락률: {candidate.flu_rt:+.2f}%\n"
                f"수량: {default_order_qty}주 시장가\n"
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
                return self._format_fill_message(fill)
        return f"【주문 접수】 {name}({code}) #{ord_no} 체결 대기 중"

    def _heartbeat(self, action: str, target: str = "") -> str:
        self._reset_daily_counter()
        lines = [
            "【자동매매 점검】",
            f"시각: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"장: {market_status_text()}",
            f"매수: {self._buy_count}/{auto_max_buys_per_day}회",
            f"조치: {action}",
        ]
        if target:
            lines.insert(-1, f"대상: {target}")
        return "\n".join(lines)

    def _portfolio_summary(
        self,
        holdings: list[HoldingView],
        sold_count: int,
    ) -> str:
        lines = [
            "【포트폴리오】",
            f"보유 {len(holdings)}/{strategy_max_positions} · 매도 {sold_count}건",
        ]
        for h in holdings[:5]:
            state = self.positions.get(h.code)
            peak = state.peak_profit_pct if state else h.profit_pct
            lines.append(
                f"  {h.name}({h.code}) {h.qty}주 "
                f"매매가능 {h.sellable_qty}주 "
                f"{h.profit_pct:+.2f}% (고점 {peak:+.2f}%)"
            )
        if not holdings:
            lines.append("  보유 없음")
        return "\n".join(lines)

    def run_cycle(self) -> AutoRunResult:
        result = AutoRunResult()
        if not self.enabled:
            result.add_event("자동매매 OFF")
            return result

        self._collect_new_fills(result)

        news_ctx = self.news.get_context()
        result.add_report(news_ctx.summary_message())

        sold_count = 0
        holdings: list[HoldingView] = []

        if is_market_open():
            sold_count = self._run_sell_phase(result, news_ctx)
            try:
                holdings = self._parse_holdings()
                self._run_buy_phase(result, holdings, news_ctx)
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
