from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from config.config import web_port, web_tunnel_enabled, web_tunnel_provider
except ImportError:
    web_port = 8081
    web_tunnel_enabled = True
    web_tunnel_provider = "cloudflared"
from trading.dashboard_data import build_dashboard_snapshot
from trading.account_pnl import build_account_summary, format_account_summary_text
from trading.journal_stats import build_daily_summary, build_journal_stats
from pydantic import BaseModel, Field

from web.auth import LoginRequest, TokenResponse, authenticate_user, require_user
from web.commands import get_command_menu, run_command
from web.tunnel import get_external_url, start_web_tunnel, stop_web_tunnel

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 봇·자동매매 루프 초기화 (runtime_settings.auto_trading_enabled 복원)
    from web.commands import _get_bot

    _get_bot()

    if web_tunnel_enabled:
        def on_url(url: str) -> None:
            print("=" * 50)
            print(f"외부 접속: {url}")
            print("웹 로그인: config/local_secrets.py 의 web_username / web_password")
            print("=" * 50)

        start_web_tunnel(
            int(web_port),
            provider=web_tunnel_provider,
            on_url=on_url,
        )
    yield
    stop_web_tunnel()


app = FastAPI(title="AI Stock Dashboard", docs_url=None, redoc_url=None, lifespan=lifespan)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.get("/api/health")
def health() -> dict:
    url = get_external_url()
    return {"ok": True, "external_url": url, "tunnel_enabled": web_tunnel_enabled}


@app.post("/api/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request) -> TokenResponse:
    client_key = request.client.host if request.client else "unknown"
    return authenticate_user(body.username, body.password, client_key=client_key)


@app.get("/api/dashboard")
def dashboard(_user: str = Depends(require_user)) -> dict:
    data = build_dashboard_snapshot()
    data["external_url"] = get_external_url()
    return data


@app.get("/api/journal/stats")
def journal_stats(days: int = 30, _user: str = Depends(require_user)) -> dict:
    if days <= 0:
        return build_journal_stats(days=None)
    return build_journal_stats(days=days)


@app.get("/api/journal/daily")
def journal_daily(_user: str = Depends(require_user)) -> dict:
    return build_daily_summary()


@app.get("/api/account/summary")
def account_summary(_user: str = Depends(require_user)) -> dict:
    return build_account_summary()


@app.get("/api/journal/traded-stocks")
def journal_traded_stocks(
    days: int = 30,
    limit: int = 20,
    _user: str = Depends(require_user),
) -> dict:
    from trading.trade_charts import list_traded_stocks

    return list_traded_stocks(days=max(1, days), limit=max(1, min(limit, 50)))


@app.get("/api/journal/trade-charts/{code}")
def journal_trade_chart(
    code: str,
    days: int = 90,
    _user: str = Depends(require_user),
) -> dict:
    from trading.trade_charts import build_stock_chart

    return build_stock_chart(code, days=max(7, min(days, 365)))


class CommandRunBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


@app.get("/api/commands/menu")
def commands_menu(_user: str = Depends(require_user)) -> dict:
    return get_command_menu()


@app.post("/api/commands/run")
def commands_run(body: CommandRunBody, _user: str = Depends(require_user)) -> dict:
    return run_command(body.text)


@app.exception_handler(RuntimeError)
async def runtime_config_error(_request: Request, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
