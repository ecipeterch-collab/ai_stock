from __future__ import annotations

import json
import threading
import time
from typing import Callable

import requests

from config.config import (
    default_order_qty,
    dmst_stex_tp,
    notify_on_auto_events_only,
    strategy_mode as config_strategy_mode,
    telegram_chat_id,
    telegram_token,
    use_paper,
)
from kiwoom.client import KiwoomAPIError, KiwoomClient
from telegram.tel_send import send_message
from trading.mode_settings import (
    SETTINGS_FILE,
    set_auto_trading_enabled,
    set_strategy_mode,
)
from trading.runtime_config import (
    effective_auto_interval_sec,
    effective_max_buys_per_day,
    get_strategy_mode,
    mode_label,
    set_strategy_mode,
)
from trading.strategy import AutoTradingStrategy

def _get_updates_url() -> str:
    if not telegram_token:
        return ""
    return f"https://api.telegram.org/bot{telegram_token}/getUpdates"


def _target_chat_id() -> int | None:
    try:
        return int(str(telegram_chat_id).strip())
    except (TypeError, ValueError):
        return None


GET_UPDATES_URL = _get_updates_url()
TARGET_CHAT_ID = _target_chat_id()
POLL_TIMEOUT = 30


class TelegramTradingBot:
    """텔레그램 명령으로 키움 API 매매를 제어하는 봇."""

    def __init__(self) -> None:
        self.client = KiwoomClient()
        self.strategy = AutoTradingStrategy(self.client)
        self._auto_thread: threading.Thread | None = None
        self._stop_auto = threading.Event()
        if not SETTINGS_FILE.exists():
            set_strategy_mode(config_strategy_mode)

    def notify(self, text: str) -> None:
        send_message(text)

    def _commands(self) -> dict[str, Callable[[list[str]], str]]:
        return {
            "/help": self._cmd_help,
            "/도움": self._cmd_help,
            "/status": self._cmd_status,
            "/상태": self._cmd_status,
            "/balance": self._cmd_balance,
            "/잔고": self._cmd_balance,
            "/portfolio": self._cmd_portfolio,
            "/포트폴리오": self._cmd_portfolio,
            "/현황": self._cmd_portfolio,
            "/rank": self._cmd_rank,
            "/순위": self._cmd_rank,
            "/buy": self._cmd_buy,
            "/매수": self._cmd_buy,
            "/sell": self._cmd_sell,
            "/매도": self._cmd_sell,
            "/auto": self._cmd_auto,
            "/자동": self._cmd_auto,
            "/strategy": self._cmd_strategy,
            "/전략": self._cmd_strategy,
            "/mode": self._cmd_mode,
            "/모드": self._cmd_mode,
            "/news": self._cmd_news,
            "/뉴스": self._cmd_news,
            "/report": self._cmd_report,
            "/리포트": self._cmd_report,
            "/trend": self._cmd_trend,
            "/트렌드": self._cmd_trend,
            "/trendbuy": self._cmd_trend_buy,
            "/트렌드매수": self._cmd_trend_buy,
            "/resetbuys": self._cmd_reset_buys,
            "/리셋": self._cmd_reset_buys,
            "/reset": self._cmd_reset_buys,
        }

    def _cmd_help(self, _args: list[str]) -> str:
        mode = "모의투자" if use_paper else "실전투자"
        strat = mode_label()
        interval = effective_auto_interval_sec()
        return (
            f"키움 자동매매 봇 ({mode} · {strat})\n\n"
            "/status - 예수금·자동매매 상태\n"
            "/balance - 보유 종목 (진입가·수익률)\n"
            "/portfolio - 계좌·보유·매수상태·최근거래\n"
            "/rank - 거래대금 상위 5\n"
            f"/mode - 전략 모드 (현재: {strat})\n"
            f"/strategy - {strat} 매매 규칙\n"
            "/news - 시장·경제·지정학 뉴스 브리핑\n"
            "/buy 종목코드 [수량] - 시장가 매수\n"
            "/sell 종목코드 [수량] - 시장가 매도\n"
            f"/auto on|off - 자동매매 ({interval}초 주기, 이벤트만 알림)\n"
            "/report - 뉴스·잔고·점검 수동 리포트\n"
            "/trend - 글로벌 트렌드·저가 후보 소개\n"
            "/trendbuy - 트렌드 1위 종목 매수\n"
            "/resetbuys - 일일 매수 제한 리셋\n"
            "/help - 명령어 목록"
        )

    def _cmd_reset_buys(self, _args: list[str]) -> str:
        self.strategy.reset_daily_buy_limits()
        return (
            "일일 매수 제한을 리셋했습니다.\n"
            "- 매수 카운터: 0\n"
            "- 트렌드 매수 카운터: 0\n"
            "- 급락 매수 카운터: 0\n"
            "- 연속손실 브레이커: 해제\n"
            "- 일일 손실 상한: 해제"
        )

    def _cmd_trend(self, args: list[str]) -> str:
        if args and args[0].lower() in ("buy", "매수"):
            return self._cmd_trend_buy([])
        return self.strategy.get_trend_report()

    def _cmd_trend_buy(self, _args: list[str]) -> str:
        return self.strategy.trend_buy_best()

    def _cmd_report(self, _args: list[str]) -> str:
        return self.strategy.build_manual_report()

    def _cmd_mode(self, args: list[str]) -> str:
        if not args:
            mode = get_strategy_mode()
            interval = effective_auto_interval_sec()
            return (
                f"【전략 모드】 {mode_label(mode)} ({mode})\n"
                f"점검 주기: {interval}초\n"
                f"일일 매수: 최대 {effective_max_buys_per_day()}회\n\n"
                "변경: /mode swing 또는 /mode scalping\n"
                "(한글: /mode 스윙 · /mode 스캘핑)"
            )

        try:
            new_mode = set_strategy_mode(args[0])
        except ValueError as exc:
            return str(exc)

        was_running = self.strategy.enabled
        if was_running:
            self._restart_auto_loop()

        label = mode_label(new_mode)
        interval = effective_auto_interval_sec()
        lines = [
            f"전략 모드를 {label}({new_mode})로 변경했습니다.",
            f"점검 주기: {interval}초",
        ]
        if was_running:
            lines.append("자동매매 루프를 새 모드로 재시작했습니다.")
        else:
            lines.append("/auto on 으로 자동매매를 시작하세요.")
        return "\n".join(lines)

    def _cmd_strategy(self, _args: list[str]) -> str:
        return self.strategy.get_rules_summary()

    def _cmd_news(self, _args: list[str]) -> str:
        return self.strategy.get_news_briefing()

    def _cmd_status(self, _args: list[str]) -> str:
        return self.strategy.build_account_status()

    def _cmd_balance(self, _args: list[str]) -> str:
        return self.strategy.build_balance_detail()

    def _cmd_portfolio(self, _args: list[str]) -> str:
        return self.strategy.build_account_dashboard()

    def _cmd_rank(self, _args: list[str]) -> str:
        items = self.client.get_trade_value_rank(top_n=5)
        if not items:
            return "순위 데이터가 없습니다."

        lines = ["【거래대금 상위 5】"]
        for item in items:
            rank = item.get("now_rank", "?")
            name = item.get("stk_nm", "")
            code = self.client.normalize_stock_code(item.get("stk_cd", ""))
            price = item.get("cur_prc", "")
            amount = item.get("trde_prica", "")
            lines.append(f"{rank}. {name}({code}) {price} / {amount}")
        return "\n".join(lines)

    def _cmd_buy(self, args: list[str]) -> str:
        if not args:
            return "사용법: /buy 종목코드 [수량]"
        code = self.client.normalize_stock_code(args[0])
        qty = int(args[1]) if len(args) > 1 else default_order_qty
        result = self.client.buy_market(code, qty, dmst_stex_tp=dmst_stex_tp)
        ord_no = result.get("ord_no", "")
        lines = [
            f"[매수] {code} {qty}주",
            f"{result.get('return_msg', '')} (주문번호: {ord_no})",
        ]
        fill_msg = self.strategy.check_order_fill(ord_no, code)
        if fill_msg:
            lines.append(fill_msg)
            threading.Thread(target=self.notify, args=(fill_msg,), daemon=True).start()
        return "\n".join(lines)

    def _cmd_sell(self, args: list[str]) -> str:
        if not args:
            return "사용법: /sell 종목코드 [수량]"
        code = self.client.normalize_stock_code(args[0])
        qty = int(args[1]) if len(args) > 1 else default_order_qty

        holdings = self.client.get_holdings()
        sellable = 0
        for item in holdings:
            if self.client.normalize_stock_code(item.get("stk_cd", "")) == code:
                sellable = self.client.parse_qty(item.get("trde_able_qty", "0"))
                break
        if sellable <= 0:
            return (
                f"【매도 불가】 {code}\n"
                "매매가능수량 0주입니다. (결제 대기·미체결 확인)"
            )
        if qty > sellable:
            qty = sellable

        result = self.client.sell_market(code, qty, dmst_stex_tp=dmst_stex_tp)
        ord_no = result.get("ord_no", "")
        lines = [
            f"[매도] {code} {qty}주",
            f"{result.get('return_msg', '')} (주문번호: {ord_no})",
        ]
        fill_msg = self.strategy.check_order_fill(ord_no, code, sell_tp="1")
        if fill_msg:
            lines.append(fill_msg)
            threading.Thread(target=self.notify, args=(fill_msg,), daemon=True).start()
        return "\n".join(lines)

    def _cmd_auto(self, args: list[str]) -> str:
        if not args:
            state = "ON" if self.strategy.enabled else "OFF"
            return f"자동매매: {state}\n사용법: /auto on 또는 /auto off"

        action = args[0].lower()
        if action in ("on", "start", "1"):
            self.strategy.enable()
            set_auto_trading_enabled(True)
            self._start_auto_loop()
            threading.Thread(
                target=self._run_auto_cycle_silent_check,
                daemon=True,
            ).start()
            return (
                f"자동매매 시작 ({effective_auto_interval_sec()}초 · "
                f"{mode_label()})\n"
                "알림: 체결·매수·매도·실패 시에만 전송\n"
                "계좌·보유: /portfolio"
            )
        if action in ("off", "stop", "0"):
            self.strategy.disable()
            set_auto_trading_enabled(False)
            self._stop_auto_loop()
            return "자동매매 중지"
        return "사용법: /auto on 또는 /auto off"

    def _notify_cycle_events(self, result) -> None:
        messages = (
            result.events
            if notify_on_auto_events_only
            else result.messages
        )
        for message in messages:
            self.notify(message)

    def _run_auto_cycle_silent_check(self) -> None:
        """주기 점검: 이벤트(체결·주문·실패)만 텔레그램 전송."""
        try:
            result = self.strategy.run_cycle()
            self._notify_cycle_events(result)
        except requests.RequestException as exc:
            self.notify(f"자동매매 통신 오류: {exc}")

    def _start_auto_loop(self) -> None:
        if self._auto_thread and self._auto_thread.is_alive():
            return
        self._stop_auto.clear()

        def loop() -> None:
            while not self._stop_auto.is_set():
                if self._stop_auto.wait(effective_auto_interval_sec()):
                    break
                if self.strategy.enabled:
                    self._run_auto_cycle_silent_check()

        self._auto_thread = threading.Thread(target=loop, daemon=True)
        self._auto_thread.start()

    def _stop_auto_loop(self) -> None:
        self._stop_auto.set()

    def _restart_auto_loop(self) -> None:
        """모드 변경 등으로 점검 주기가 바뀔 때 자동 루프 재시작."""
        self._stop_auto_loop()
        if self._auto_thread and self._auto_thread.is_alive():
            self._auto_thread.join(timeout=5)
        self._auto_thread = None
        if self.strategy.enabled:
            self._start_auto_loop()

    def handle_command(self, text: str) -> str | None:
        text = text.strip()
        if not text.startswith("/"):
            return None

        parts = text.split()
        command = parts[0].split("@")[0]
        args = parts[1:]

        handler = self._commands().get(command)
        if not handler:
            return f"알 수 없는 명령: {command}\n/help 로 명령어를 확인하세요."

        try:
            return handler(args)
        except KiwoomAPIError as exc:
            return f"API 오류: {exc}"
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            return f"HTTP 오류 ({status}): {exc}"
        except requests.RequestException as exc:
            return f"네트워크 오류: {exc}"
        except (ValueError, IndexError) as exc:
            return f"입력 오류: {exc}"

    def _fetch_updates(self, offset: int | None) -> list[dict]:
        if not GET_UPDATES_URL:
            raise RuntimeError("Telegram token 미설정")
        params: dict = {"timeout": POLL_TIMEOUT}
        if offset is not None:
            params["offset"] = offset

        response = requests.get(
            GET_UPDATES_URL,
            params=params,
            timeout=POLL_TIMEOUT + 10,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API 오류: {json.dumps(data, ensure_ascii=False)}")
        return data.get("result", [])

    def _skip_backlog(self) -> int | None:
        updates = self._fetch_updates(offset=None)
        if not updates:
            return None
        return updates[-1]["update_id"] + 1

    def _handle_update(self, update: dict) -> None:
        message = update.get("message")
        if not message:
            return
        if TARGET_CHAT_ID is None or message.get("chat", {}).get("id") != TARGET_CHAT_ID:
            return
        if (message.get("from") or {}).get("is_bot"):
            return

        text = message.get("text")
        if not text:
            return

        print(f"수신: {text!r}")
        reply = self.handle_command(text)
        if reply:
            print(f"응답: {reply[:80]}...")
            send_message(reply)

    def run(self) -> None:
        if not telegram_token or TARGET_CHAT_ID is None:
            raise RuntimeError(
                "텔레그램 설정이 비어 있습니다. "
                "config/local_secrets.py 또는 환경변수(TELEGRAM_CHAT_ID, TELEGRAM_BOT_TOKEN)를 설정하세요."
            )
        offset = self._skip_backlog()
        mode = "모의투자" if use_paper else "실전투자"
        strat = mode_label()
        startup = (
            f"키움 자동매매 봇 시작 ({mode} · {strat})\n"
            "/help 로 명령어를 확인하세요."
        )
        print(startup)
        self.notify(startup)
        print(f"채팅 {TARGET_CHAT_ID} 명령 대기 중... (종료: Ctrl+C)")

        while True:
            try:
                updates = self._fetch_updates(offset)
                for update in updates:
                    self._handle_update(update)
                    offset = update["update_id"] + 1
            except KeyboardInterrupt:
                self.strategy.disable()
                self._stop_auto_loop()
                self.notify("자동매매 봇을 종료합니다.")
                print("\n종료합니다.")
                break
            except requests.RequestException as exc:
                print(f"요청 오류, 5초 후 재시도: {exc}")
                time.sleep(5)
