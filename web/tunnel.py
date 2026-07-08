"""외부 HTTPS 접속 (cloudflared / ngrok). ai_coin과 동시 실행 시 전역 프로세스 종료 없음."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from typing import Callable

logger = logging.getLogger(__name__)

TUNNEL_URL_PATTERN = re.compile(
    r"https://[a-z0-9-]+\.(trycloudflare\.com|ngrok[^\s]*|ngrok-free\.app)"
)

_tunnel_proc: subprocess.Popen | None = None
_external_url: str | None = None


def get_external_url() -> str | None:
    return _external_url


class TunnelManager:
    """로컬 web_port → 공개 HTTPS URL."""

    def __init__(self, port: int, provider: str = "cloudflared") -> None:
        self.port = port
        self.provider = provider
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
            logger.debug("tunnel: %s", line)

            if ngrok_json and '"url"' in line and "https://" in line:
                match = re.search(r'"https://[^"]+"', line)
                if match:
                    self._set_url(match.group(0).strip('"'), on_url)
                    continue

            match = TUNNEL_URL_PATTERN.search(line)
            if match:
                self._set_url(match.group(0), on_url)

        if proc.poll() is None:
            proc.wait()

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
) -> TunnelManager | None:
    """터널 시작 (이미 실행 중이면 무시)."""
    global _manager
    if _manager:
        return _manager
    _manager = TunnelManager(port, provider=provider)
    _manager.start(on_url=on_url)
    return _manager


def stop_web_tunnel() -> None:
    global _manager, _external_url
    if _manager:
        _manager.stop()
        _manager = None
    _external_url = None
