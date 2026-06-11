from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from config.secrets import load_secrets

try:
    from config.config import web_token_expire_hours
except ImportError:
    web_token_expire_hours = 24

_bearer = HTTPBearer(auto_error=False)
_login_attempts: dict[str, list[float]] = {}
_MAX_LOGIN_ATTEMPTS = 8
_LOGIN_WINDOW_SEC = 300


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def _web_credentials() -> tuple[str, str, str]:
    s = load_secrets()
    username = s.web_username.strip()
    password = s.web_password
    secret = s.web_secret_key.strip()
    if not username or not password or not secret:
        raise RuntimeError(
            "웹 로그인 설정이 비어 있습니다. "
            "config/local_secrets.py 에 web_username, web_password, web_secret_key 를 설정하세요."
        )
    if len(secret) < 16:
        raise RuntimeError("web_secret_key 는 16자 이상으로 설정하세요.")
    return username, password, secret


def _check_rate_limit(client_key: str) -> None:
    now = datetime.now(timezone.utc).timestamp()
    attempts = _login_attempts.setdefault(client_key, [])
    attempts[:] = [t for t in attempts if now - t < _LOGIN_WINDOW_SEC]
    if len(attempts) >= _MAX_LOGIN_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.",
        )


def authenticate_user(username: str, password: str, client_key: str = "global") -> TokenResponse:
    _check_rate_limit(client_key)
    expected_user, expected_pass, secret = _web_credentials()
    ok = secrets.compare_digest(username.strip(), expected_user) and secrets.compare_digest(
        password, expected_pass
    )
    _login_attempts.setdefault(client_key, []).append(
        datetime.now(timezone.utc).timestamp()
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )
    expire_hours = max(1, int(web_token_expire_hours))
    expires_delta = timedelta(hours=expire_hours)
    expires_at = datetime.now(timezone.utc) + expires_delta
    token = jwt.encode(
        {"sub": expected_user, "exp": expires_at},
        secret,
        algorithm="HS256",
    )
    return TokenResponse(
        access_token=token,
        expires_in=int(expires_delta.total_seconds()),
    )


def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _, _, secret = _web_credentials()
    try:
        payload = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 만료되었거나 유효하지 않습니다.",
        ) from None
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰")
    return str(sub)
