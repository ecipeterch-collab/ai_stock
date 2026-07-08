"""웹 대시보드 서버 (폰·외부 접속용, JWT 로그인)."""

from __future__ import annotations

import socket
import subprocess
import sys

import uvicorn

try:
    from config.config import web_host, web_port, web_tunnel_enabled
except ImportError:
    web_host = "0.0.0.0"
    web_port = 8081
    web_tunnel_enabled = True

from config.secrets import load_secrets


def _port_listening_pid(port: int) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            errors="replace",
            timeout=10,
        )
        needle = f":{port}"
        for line in out.splitlines():
            if "LISTENING" not in line or needle not in line:
                continue
            parts = line.split()
            if parts and parts[-1].isdigit():
                return int(parts[-1])
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    return None


def ensure_port_available(host: str, port: int) -> None:
    bind_host = "0.0.0.0" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind_host, port))
        except OSError as exc:
            pid = _port_listening_pid(port)
            if pid:
                raise SystemExit(
                    f"포트 {port}이(가) 이미 사용 중입니다 (PID {pid}).\n"
                    f"  기존 서버 종료: taskkill /F /PID {pid}\n"
                    f"  또는 실행 중인 'python run_web.py'를 Ctrl+C로 중지하세요."
                ) from exc
            raise SystemExit(f"포트 {port}을(를) 사용할 수 없습니다: {exc}") from exc


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

    port = int(web_port)
    ensure_port_available(web_host, port)

    print(f"웹 대시보드 (로컬): http://{web_host}:{port}")
    if web_tunnel_enabled:
        print("외부 HTTPS: cloudflared 터널 자동 시작 (URL은 기동 후 출력)")
    else:
        print("외부 HTTPS: docs/REMOTE_ACCESS.md")
        print("  Tailscale  -> .\\scripts\\tailscale-serve.ps1")
        print("  Caddy      -> .\\scripts\\caddy-serve.ps1")
    uvicorn.run(
        "web.app:app",
        host=web_host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
