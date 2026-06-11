"""웹 대시보드 서버 (폰·외부 접속용, JWT 로그인)."""

from __future__ import annotations

import sys

import uvicorn

try:
    from config.config import web_host, web_port
except ImportError:
    web_host = "0.0.0.0"
    web_port = 8080

from config.secrets import load_secrets


def main() -> None:
    secrets = load_secrets()
    if not secrets.web_username or not secrets.web_password or not secrets.web_secret_key:
        print(
            "오류: 웹 로그인 설정이 없습니다.\n"
            "config/local_secrets.py 에 web_username, web_password, web_secret_key 를 추가하세요.\n"
            "예시: config/local_secrets.example.py 참고",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"웹 대시보드 (로컬): http://{web_host}:{web_port}")
    print("외부 HTTPS: docs/REMOTE_ACCESS.md")
    print("  Tailscale  -> .\\scripts\\tailscale-serve.ps1")
    print("  Caddy      -> .\\scripts\\caddy-serve.ps1")
    uvicorn.run(
        "web.app:app",
        host=web_host,
        port=int(web_port),
        reload=False,
    )


if __name__ == "__main__":
    main()
