"""외부 HTTPS 접속 (cloudflared / ngrok). ai_coin과 동시 실행 시 전역 프로세스 종료 없음."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

TUNNEL_URL_PATTERN = re.compile(
    r"https://[a-z0-9.-]+\.(trycloudflare\.com|ngrok[^\s]*|ngrok-free\.app|cfargotunnel\.com)"
)

_tunnel_proc: subprocess.Popen | None = None
_external_url: str | None = None
DEFAULT_NAMED_CONFIG = Path(__file__).resolve().parents[1] / "config" / "cloudflared.yml"


def origin_cert_path() -> Path:
    return Path.home() / ".cloudflared" / "cert.pem"


def origin_cert_exists() -> bool:
    return origin_cert_path().is_file()


def named_tunnel_ready(
    *,
    token: str = "",
    name: str = "",
    config_path: str = "",
) -> bool:
    """고정 도메인 터널을 띄울 자격 증명(토큰·설정·origin cert)이 있는지."""
    if (token or "").strip():
        return True
    cfg = (config_path or "").strip()
    if cfg and Path(cfg).is_file():
        return True
    return bool((name or "").strip() and origin_cert_exists())


def normalize_public_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value.rstrip("/")


def hostname_from_public_url(url: str) -> str:
    normalized = normalize_public_url(url)
    if not normalized:
        return ""
    return urlparse(normalized).hostname or ""


def named_tunnel_config_text(
    *,
    tunnel: str,
    credentials_file: str,
    hostname: str,
    port: int,
) -> str:
    return (
        f"tunnel: {tunnel}\n"
        f"credentials-file: {credentials_file}\n"
        "ingress:\n"
        f"  - hostname: {hostname}\n"
        f"    service: http://127.0.0.1:{int(port)}\n"
        "  - service: http_status:404\n"
    )


def build_cloudflared_cmd(
    port: int,
    *,
    token: str = "",
    name: str = "",
    config_path: str = "",
) -> list[str]:
    cmd = ["cloudflared", "tunnel", "--no-autoupdate"]
    token = (token or "").strip()
    name = (name or "").strip()
    config_path = (config_path or "").strip()
    if token:
        return cmd + ["run", "--token", token]
    if config_path and Path(config_path).is_file():
        return cmd + ["--config", config_path, "run"]
    if name and origin_cert_exists():
        return cmd + ["run", name]
    if name or config_path:
        logger.error(
            "named tunnel 자격 증명이 없습니다 (token/config/cert.pem). "
            "임시 trycloudflare 터널로 대체합니다. "
            "고정 URL은 scripts/setup-named-tunnel.ps1 을 완료하세요."
        )
    return cmd + ["--url", f"http://127.0.0.1:{int(port)}"]


def get_external_url() -> str | None:
    return _external_url


class TunnelManager:
    """로컬 web_port → 공개 HTTPS URL."""

    def __init__(
        self,
        port: int,
        provider: str = "cloudflared",
        *,
        token: str = "",
        name: str = "",
        public_url: str = "",
        config_path: str = "",
    ) -> None:
        self.port = port
        self.provider = provider
        self.token = (token or "").strip()
        self.name = (name or "").strip()
        self.public_url = normalize_public_url(public_url)
        self.config_path = (config_path or "").strip()
        if not self.config_path and self.name and not self.token and DEFAULT_NAMED_CONFIG.is_file():
            self.config_path = str(DEFAULT_NAMED_CONFIG)
        self.url: str | None = None
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def start(self, on_url: Callable[[str], None] | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            kwargs={"on_url": on_url},
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        global _tunnel_proc
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if _tunnel_proc is self._proc:
            _tunnel_proc = None
        self._proc = None
        self.url = None

    def _run(self, on_url: Callable[[str], None] | None = None) -> None:
        if self.provider == "ngrok":
            self._run_ngrok(on_url)
        else:
            self._run_cloudflared(on_url)

    def _run_cloudflared(self, on_url: Callable[[str], None] | None) -> None:
        global _tunnel_proc
        if not shutil.which("cloudflared"):
            logger.error(
                "cloudflared 미설치 — winget install Cloudflare.cloudflared"
            )
            return

        cmd = [
            "cloudflared",
            "tunnel",
            "--url",
            f"http://127.0.0.1:{self.port}",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        _tunnel_proc = self._proc
        self._read_output(self._proc, on_url)

    def _run_ngrok(self, on_url: Callable[[str], None] | None) -> None:
        global _tunnel_proc
        if not shutil.which("ngrok"):
            logger.error("ngrok 미설치 — https://ngrok.com/download")
            return

        cmd = ["ngrok", "http", str(self.port), "--log=stdout"]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        _tunnel_proc = self._proc
        self._read_output(self._proc, on_url, ngrok_json=True)

    def _read_output(
        self,
        proc: subprocess.Popen,
        on_url: Callable[[str], None] | None,
        ngrok_json: bool = False,
    ) -> None:
        if proc.stdout is None:
            return

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if "ERR " in line or line.lower().startswith("error"):
                logger.error("tunnel: %s", line)
            else:
                logger.debug("tunnel: %s", line)

            if ngrok_json and '"url"' in line and "https://" in line:
                match = re.search(r'"https://[^"]+"', line)
                if match:
                    self._set_url(match.group(0).strip('"'), on_url)
                    continue

            match = TUNNEL_URL_PATTERN.search(line)
            if match:
                self._set_url(match.group(0), on_url)

        code = proc.poll()
        if code is None:
            proc.wait()
            code = proc.poll()
        if code not in (0, None):
            logger.error("tunnel process exited with code %s", code)

    def _set_url(self, url: str, on_url: Callable[[str], None] | None) -> None:
        global _external_url
        if self.url:
            return
        self.url = url
        _external_url = url
        logger.info("외부 접속 URL: %s", url)
        if on_url:
            on_url(url)


_manager: TunnelManager | None = None


def start_web_tunnel(
    port: int,
    *,
    provider: str = "cloudflared",
    on_url: Callable[[str], None] | None = None,
    token: str = "",
    name: str = "",
    public_url: str = "",
    config_path: str = "",
) -> TunnelManager | None:
    """터널 시작 (이미 실행 중이면 무시)."""
    global _manager
    if _manager:
        return _manager
    _manager = TunnelManager(
        port,
        provider=provider,
        token=token,
        name=name,
        public_url=public_url,
        config_path=config_path,
    )
    _manager.start(on_url=on_url)
    return _manager


def stop_web_tunnel() -> None:
    global _manager, _external_url
    if _manager:
        _manager.stop()
        _manager = None
    _external_url = None
