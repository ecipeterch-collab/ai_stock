from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from trading.dashboard_data import build_dashboard_snapshot
from trading.journal_stats import build_journal_stats
from web.auth import LoginRequest, TokenResponse, authenticate_user, require_user

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="AI Stock Dashboard", docs_url=None, redoc_url=None)


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
    return {"ok": True}


@app.post("/api/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request) -> TokenResponse:
    client_key = request.client.host if request.client else "unknown"
    return authenticate_user(body.username, body.password, client_key=client_key)


@app.get("/api/dashboard")
def dashboard(_user: str = Depends(require_user)) -> dict:
    return build_dashboard_snapshot()


@app.get("/api/journal/stats")
def journal_stats(days: int = 30, _user: str = Depends(require_user)) -> dict:
    if days <= 0:
        return build_journal_stats(days=None)
    return build_journal_stats(days=days)


@app.exception_handler(RuntimeError)
async def runtime_config_error(_request: Request, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
