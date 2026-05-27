from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Secrets:
    real_app_key: str
    real_app_secret: str
    paper_app_key: str
    paper_app_secret: str
    telegram_chat_id: str
    telegram_token: str


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def load_secrets() -> Secrets:
    # 1) optional local file (ignored by git)
    local = {}
    try:
        from config import local_secrets as _local  # type: ignore

        local = {
            "real_app_key": getattr(_local, "real_app_key", ""),
            "real_app_secret": getattr(_local, "real_app_secret", ""),
            "paper_app_key": getattr(_local, "paper_app_key", ""),
            "paper_app_secret": getattr(_local, "paper_app_secret", ""),
            "telegram_chat_id": getattr(_local, "telegram_chat_id", ""),
            "telegram_token": getattr(_local, "telegram_token", ""),
        }
    except Exception:
        local = {}

    # 2) environment variables override everything
    return Secrets(
        real_app_key=_env("KIWOOM_REAL_APP_KEY", local.get("real_app_key", "")),
        real_app_secret=_env("KIWOOM_REAL_APP_SECRET", local.get("real_app_secret", "")),
        paper_app_key=_env("KIWOOM_PAPER_APP_KEY", local.get("paper_app_key", "")),
        paper_app_secret=_env("KIWOOM_PAPER_APP_SECRET", local.get("paper_app_secret", "")),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID", local.get("telegram_chat_id", "")),
        telegram_token=_env("TELEGRAM_BOT_TOKEN", local.get("telegram_token", "")),
    )

