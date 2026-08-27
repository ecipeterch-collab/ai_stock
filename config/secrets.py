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
    web_username: str
    web_password: str
    web_secret_key: str
    web_tunnel_token: str = ""


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
            "web_username": getattr(_local, "web_username", ""),
            "web_password": getattr(_local, "web_password", ""),
            "web_secret_key": getattr(_local, "web_secret_key", ""),
            "web_tunnel_token": getattr(_local, "web_tunnel_token", ""),
        }
    except Exception:
        local = {}

    # config.py fallback (local_secrets 미사용 시)
    try:
        from config import config as _cfg  # type: ignore

        for key in ("web_username", "web_password", "web_secret_key"):
            if not local.get(key):
                val = getattr(_cfg, key, "")
                if val:
                    local[key] = val
    except Exception:
        pass

    # 2) environment variables override everything
    return Secrets(
        real_app_key=_env("KIWOOM_REAL_APP_KEY", local.get("real_app_key", "")),
        real_app_secret=_env("KIWOOM_REAL_APP_SECRET", local.get("real_app_secret", "")),
        paper_app_key=_env("KIWOOM_PAPER_APP_KEY", local.get("paper_app_key", "")),
        paper_app_secret=_env("KIWOOM_PAPER_APP_SECRET", local.get("paper_app_secret", "")),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID", local.get("telegram_chat_id", "")),
        telegram_token=_env("TELEGRAM_BOT_TOKEN", local.get("telegram_token", "")),
        web_username=_env("WEB_USERNAME", local.get("web_username", "")),
        web_password=_env("WEB_PASSWORD", local.get("web_password", "")),
        web_secret_key=_env("WEB_SECRET_KEY", local.get("web_secret_key", "")),
        web_tunnel_token=_env("WEB_TUNNEL_TOKEN", local.get("web_tunnel_token", "")),
    )

