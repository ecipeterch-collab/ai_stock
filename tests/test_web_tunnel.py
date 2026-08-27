"""고정 HTTPS URL / named cloudflared 터널 명령."""

from __future__ import annotations

from web.tunnel import (
    build_cloudflared_cmd,
    hostname_from_public_url,
    named_tunnel_config_text,
    named_tunnel_ready,
    normalize_public_url,
)


def test_quick_tunnel_uses_ephemeral_url_flag() -> None:
    cmd = build_cloudflared_cmd(8081)
    assert cmd[:3] == ["cloudflared", "tunnel", "--no-autoupdate"]
    assert cmd[-2:] == ["--url", "http://127.0.0.1:8081"]


def test_named_tunnel_prefers_token_over_quick_url() -> None:
    cmd = build_cloudflared_cmd(8081, token="tok_abc")
    assert cmd == [
        "cloudflared",
        "tunnel",
        "--no-autoupdate",
        "run",
        "--token",
        "tok_abc",
    ]


def test_named_tunnel_uses_config_file(tmp_path) -> None:
    cfg = tmp_path / "cloudflared.yml"
    cfg.write_text("tunnel: ai-stock\n", encoding="utf-8")
    cmd = build_cloudflared_cmd(8081, name="ai-stock", config_path=str(cfg))
    assert "--url" not in cmd
    assert "--config" in cmd
    assert str(cfg) in cmd
    assert cmd[-1] == "run"


def test_normalize_public_url_adds_https_and_strips_slash() -> None:
    assert normalize_public_url("stock.jhunnet.com/") == "https://stock.jhunnet.com"
    assert normalize_public_url("https://stock.jhunnet.com") == "https://stock.jhunnet.com"
    assert normalize_public_url("  ") == ""


def test_hostname_from_public_url() -> None:
    assert hostname_from_public_url("https://stock.jhunnet.com") == "stock.jhunnet.com"
    assert hostname_from_public_url("") == ""


def test_named_tunnel_config_routes_hostname_to_local_port() -> None:
    text = named_tunnel_config_text(
        tunnel="ai-stock",
        credentials_file=r"C:\Users\me\.cloudflared\id.json",
        hostname="stock.jhunnet.com",
        port=8081,
    )
    assert "tunnel: ai-stock" in text
    assert "hostname: stock.jhunnet.com" in text
    assert "service: http://127.0.0.1:8081" in text
    assert "http_status:404" in text


def test_named_tunnel_ready_requires_token_config_or_cert(monkeypatch) -> None:
    monkeypatch.setattr("web.tunnel.origin_cert_exists", lambda: False)
    assert named_tunnel_ready(token="tok") is True
    assert named_tunnel_ready(config_path=__file__) is True
    assert named_tunnel_ready(name="ai-stock") is False
    assert named_tunnel_ready(name="ai-stock", config_path=r"C:\missing\cloudflared.yml") is False


def test_named_tunnel_without_credentials_falls_back_to_quick_url(monkeypatch) -> None:
    monkeypatch.setattr("web.tunnel.origin_cert_exists", lambda: False)
    cmd = build_cloudflared_cmd(8081, name="ai-stock")
    assert cmd[-2:] == ["--url", "http://127.0.0.1:8081"]
    assert "run" not in cmd
