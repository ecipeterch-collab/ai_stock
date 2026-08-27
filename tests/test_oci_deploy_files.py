from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_uses_python_312_and_requirements():
    text = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12-slim" in text
    assert "requirements.txt" in text


def test_compose_binds_localhost_8081_and_kst():
    text = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "127.0.0.1:8081:8081" in text
    assert "TZ=Asia/Seoul" in text or "TZ: Asia/Seoul" in text
    assert "auto_trade.py" in text
    assert "run_web.py" in text
    assert "unless-stopped" in text


def test_nginx_example_proxies_stock_host_to_8081():
    text = (ROOT / "deploy" / "nginx-stock.jhunnet.com.conf.example").read_text(
        encoding="utf-8"
    )
    assert "stock.jhunnet.com" in text
    assert "proxy_pass http://127.0.0.1:8081" in text
    assert "ssl_certificate" in text


def test_systemd_units_set_kst_and_restart():
    bot = (ROOT / "deploy" / "ai-stock-bot.service").read_text(encoding="utf-8")
    web = (ROOT / "deploy" / "ai-stock-web.service").read_text(encoding="utf-8")
    assert "TZ=Asia/Seoul" in bot
    assert "auto_trade.py" in bot
    assert "Restart=always" in bot
    assert "TZ=Asia/Seoul" in web
    assert "run_web.py" in web
    assert "Restart=always" in web


def test_deploy_script_pulls_and_restarts():
    text = (ROOT / "scripts" / "deploy-oci.ps1").read_text(encoding="utf-8")
    assert "git pull" in text
    assert "jhunnet-migrate" in text
    assert "docker compose" in text
    assert "ai-stock-bot" in text
