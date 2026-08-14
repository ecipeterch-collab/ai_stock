"""웹 대시보드 — 텔레그램 /help 명령 실행."""

from __future__ import annotations

import threading
from typing import Any

from trading.bot import TelegramTradingBot

_bot: TelegramTradingBot | None = None
_bot_lock = threading.Lock()

# id → 실행 문자열 (텔레그램 handle_command 와 동일)
WEB_COMMAND_MENU: list[dict[str, Any]] = [
    {
        "group": "조회",
        "items": [
            {"id": "help", "label": "도움말", "cmd": "/help"},
            {"id": "status", "label": "상태", "cmd": "/status"},
            {"id": "balance", "label": "잔고", "cmd": "/balance"},
            {"id": "portfolio", "label": "포트폴리오", "cmd": "/portfolio"},
            {"id": "rank", "label": "순위 Top5", "cmd": "/rank"},
            {"id": "strategy", "label": "전략 규칙", "cmd": "/strategy"},
            {"id": "news", "label": "뉴스", "cmd": "/news"},
            {"id": "report", "label": "리포트", "cmd": "/report"},
            {"id": "pnl", "label": "오늘 손익", "cmd": "/pnl"},
            {"id": "account", "label": "원금 손익", "cmd": "/account"},
            {"id": "trend", "label": "트렌드", "cmd": "/trend"},
        ],
    },
    {
        "group": "매매",
        "items": [
            {
                "id": "buy",
                "label": "매수",
                "cmd": "/buy",
                "needs_args": True,
                "args_label": "종목코드 [수량]",
                "args_placeholder": "005930 1",
            },
            {
                "id": "sell",
                "label": "매도",
                "cmd": "/sell",
                "needs_args": True,
                "args_label": "종목코드 [수량]",
                "args_placeholder": "005930 1",
            },
            {"id": "trendbuy", "label": "트렌드 매수", "cmd": "/trendbuy"},
        ],
    },
    {
        "group": "설정 · 제어",
        "items": [
            {"id": "auto_on", "label": "자동매매 ON", "cmd": "/auto on"},
            {"id": "auto_off", "label": "자동매매 OFF", "cmd": "/auto off"},
            {"id": "mode_swing", "label": "스윙 모드", "cmd": "/mode swing"},
            {"id": "mode_scalping", "label": "스캘핑 모드", "cmd": "/mode scalping"},
            {
                "id": "capital",
                "label": "원금 설정",
                "cmd": "/capital",
                "needs_args": True,
                "args_label": "원금(원)",
                "args_placeholder": "500000000",
            },
            {
                "id": "pnl_date",
                "label": "일자 손익",
                "cmd": "/pnl",
                "needs_args": True,
                "args_label": "YYYY-MM-DD",
                "args_placeholder": "2026-06-22",
            },
            {"id": "resetbuys", "label": "매수한도 리셋", "cmd": "/resetbuys"},
        ],
    },
]


def get_command_menu() -> dict[str, Any]:
    return {"groups": WEB_COMMAND_MENU}


def _get_bot() -> TelegramTradingBot:
    global _bot
    with _bot_lock:
        if _bot is None:
            _bot = TelegramTradingBot()
        return _bot


def _command_failed(text: str) -> bool:
    """핸들러가 문자열로 돌려준 실패/불가 응답 판별."""
    head = (text or "").lstrip()
    if head.startswith(
        (
            "API 오류",
            "HTTP 오류",
            "네트워크 오류",
            "입력 오류",
            "사용법:",
            "알 수 없는 명령",
            "【매수 불가】",
            "【매도 불가】",
            "【매수 실패】",
            "【매도 실패】",
        )
    ):
        return True
    return False


def run_command(text: str) -> dict[str, Any]:
    """텔레그램과 동일한 명령 실행."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "text": "명령을 입력하세요.", "command": ""}

    if not text.startswith("/"):
        text = f"/{text}"

    bot = _get_bot()
    try:
        result = bot.handle_command(text)
    except Exception as exc:
        return {"ok": False, "text": str(exc), "command": text.split()[0]}

    if result is None:
        return {"ok": False, "text": "명령 형식이 올바르지 않습니다.", "command": text}

    ok = not _command_failed(result)
    return {"ok": ok, "text": result, "command": text.split()[0]}
