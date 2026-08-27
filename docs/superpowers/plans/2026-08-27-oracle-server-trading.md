# Oracle Server Production Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship repo deploy artifacts and small app changes so live trading can run on a dedicated OCI VM (`jhunnet-stock`) with dashboard `https://stock.jhunnet.com`, while this PC stays a debug machine.

**Architecture:** New Always Free VM in `ap-tokyo-1` (A1 + Docker preferred; Micro + systemd fallback). nginx + Cloudflare origin TLS. Bot and web share bind-mounted `config/` and `data/`. Process `TZ=Asia/Seoul`. Homepage VM `jhunnet-web` is unchanged.

**Tech Stack:** Python 3.12, FastAPI, Docker Compose, nginx, systemd, Cloudflare DNS, Kiwoom REST, PowerShell deploy script.

**Spec:** `docs/superpowers/specs/2026-08-27-oracle-server-trading-design.md`

## Global Constraints

- Do not change strategy, order, or chart logic.
- Do not modify the homepage VM (`193.123.160.126`) except reading it as a reference.
- Never commit `config/config.py`, `config/local_secrets.py`, or API keys.
- Production web: `web_host=127.0.0.1`, `web_port=8081`, `web_tunnel_enabled=False`.
- Compose publishes only `127.0.0.1:8081:8081`.
- Creating the OCI VM requires the Oracle console (or OCI CLI). Repo work must be complete even if the VM is created later.

---

### Task 1: Health and dashboard expose `runtime_host`

**Files:**
- Modify: `web/app.py`
- Modify: `trading/dashboard_data.py`
- Modify: `web/static/app.js`
- Test: `tests/test_web_runtime_host.py`

**Interfaces:**
- Produces: `runtime_host() -> str` using `socket.gethostname()`
- Health JSON includes `host` (same value)
- Dashboard snapshot includes `runtime_host`
- Meta line in UI includes the host name

- [ ] **Step 1: Write failing tests**

```python
# tests/test_web_runtime_host.py
from trading.dashboard_data import build_dashboard_snapshot
from web.app import health, runtime_host


def test_runtime_host_uses_gethostname(monkeypatch):
    monkeypatch.setattr("web.app.socket.gethostname", lambda: "jhunnet-stock")
    assert runtime_host() == "jhunnet-stock"


def test_health_includes_ok_and_host(monkeypatch):
    monkeypatch.setattr("web.app.socket.gethostname", lambda: "jhunnet-stock")
    body = health()
    assert body["ok"] is True
    assert body["host"] == "jhunnet-stock"


def test_dashboard_snapshot_includes_runtime_host(monkeypatch):
    monkeypatch.setattr(
        "trading.dashboard_data.socket.gethostname", lambda: "jhunnet-stock"
    )
    # Avoid live Kiwoom: inject a tiny strategy stub if tests already do;
    # prefer asserting key presence via monkeypatch of _resolve_strategy.
```

Prefer a unit test that does not call Kiwoom: add `runtime_host` in `web/app.py` `dashboard()` after `build_dashboard_snapshot()`, and test `health()` + `runtime_host()` plus a small helper test that the dashboard endpoint assignment uses `runtime_host()`. Testing `dashboard()` with TestClient may start the bot; do **not** use TestClient. Test:

```python
def test_dashboard_payload_sets_runtime_host(monkeypatch):
    monkeypatch.setattr("web.app.socket.gethostname", lambda: "jhunnet-stock")
    monkeypatch.setattr(
        "web.app.build_dashboard_snapshot",
        lambda: {"trade_mode_label": "모의투자"},
    )
    from web.app import dashboard

    data = dashboard(_user="admin")
    assert data["runtime_host"] == "jhunnet-stock"
```

`dashboard` has `Depends(require_user)` — calling it directly with `_user="admin"` works.

- [ ] **Step 2: Run tests, expect FAIL** because `runtime_host` is missing and health has no `host`.

- [ ] **Step 3: Implement** `runtime_host()` in `web/app.py`; add `"host": runtime_host()` to `health()`; set `data["runtime_host"] = runtime_host()` in `dashboard()`. In `app.js` `renderDashboard`, append ` · ${data.runtime_host}` to `meta-line` when present.

- [ ] **Step 4: Run tests, expect PASS.** Also `pytest tests/test_web_static.py tests/test_web_tunnel.py tests/test_web_runtime_host.py`.

---

### Task 2: Deploy file tests then Docker / nginx / systemd

**Files:**
- Create: `deploy/Dockerfile`
- Create: `deploy/docker-compose.yml`
- Create: `.dockerignore`
- Create: `deploy/nginx-stock.jhunnet.com.conf.example`
- Create: `deploy/ai-stock-bot.service`
- Create: `deploy/ai-stock-web.service`
- Test: `tests/test_oci_deploy_files.py`

- [ ] **Step 1: Write failing tests** that read those paths from repo root and assert:

- compose: `127.0.0.1:8081:8081`, `TZ=Asia/Seoul`, `python auto_trade.py`, `python run_web.py`, `restart: unless-stopped`
- Dockerfile: `python:3.12-slim`, `requirements.txt`
- nginx example: `stock.jhunnet.com`, `proxy_pass http://127.0.0.1:8081`, `ssl_certificate`
- systemd bot: `TZ=Asia/Seoul`, `auto_trade.py`, `Restart=always`
- systemd web: `TZ=Asia/Seoul`, `run_web.py`, `Restart=always`

- [ ] **Step 2: Run, expect FAIL** (files missing).

- [ ] **Step 3: Create files** matching spec:

Dockerfile (deps only; code via bind mount):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV TZ=Asia/Seoul PYTHONUNBUFFERED=1
```

`deploy/docker-compose.yml` build context `..`, dockerfile `deploy/Dockerfile`, volume `..:/app`, web ports `127.0.0.1:8081:8081`.

nginx copied from homepage pattern, `server_name stock.jhunnet.com`, proxy 8081, cert paths `/etc/ssl/cloudflare/stock.jhunnet.com.pem` and `.key` (operator may reuse wildcard `jhunnet.com` cert if SAN includes `stock`).

systemd `WorkingDirectory=/home/ubuntu/apps/ai_stock`, `ExecStart=.../.venv/bin/python ...`.

- [ ] **Step 4: Run tests PASS.**

---

### Task 3: Deploy script and operator docs

**Files:**
- Create: `scripts/deploy-oci.ps1`
- Create: `docs/OCI_PRODUCTION.md`
- Modify: `README.md`
- Modify: `docs/REMOTE_ACCESS.md`
- Modify: `config/config.example.py` (comment: server sets `web_tunnel_enabled = False`)

- [ ] **Step 1: Test** `scripts/deploy-oci.ps1` exists and contains `git pull`, `jhunnet-migrate`, `docker compose`, `ai-stock-bot` (file string test in `tests/test_oci_deploy_files.py`).

- [ ] **Step 2: Implement script** with params `-HostIp` (or env `OCI_STOCK_IP`), `-KeyPath` default `~\.ssh\jhunnet-migrate`, `-Runtime docker|systemd`. SSH `ubuntu@HostIp`, `git pull` in `/home/ubuntu/apps/ai_stock`, then compose up `--build` or `systemctl restart`.

- [ ] **Step 3: Write `docs/OCI_PRODUCTION.md`** with: console steps to create `jhunnet-stock` in `ap-tokyo-1` (A1 1 OCPU/6GB Ubuntu 22.04 50GB, reserved IP, same VCN, ports 22/80/443); fallback Micro; Python/Docker/nginx install; GitHub deploy key; copy secrets and `data/`; Kiwoom IP allow-list; Cloudflare A record `stock` → new IP, Full strict; cutover order (stop PC `auto_trade.py` and cloudflared **before** starting server bot); dual-run rule (`use_paper=True` on PC); health check URLs.

- [ ] **Step 4: README** table row pointing to `docs/OCI_PRODUCTION.md`. REMOTE_ACCESS: production is OCI + Cloudflare DNS; PC cloudflared is **dev only**.

---

### Task 4: Verification

- [ ] `pytest tests/test_web_runtime_host.py tests/test_oci_deploy_files.py tests/test_web_static.py tests/test_web_tunnel.py -q`
- [ ] Full `pytest -q` if time allows
- [ ] Do not create the OCI VM from this repo unless `oci` CLI is already authenticated; leave console steps in the runbook

OCI VM create, DNS cutover, and Kiwoom IP registration are **operator steps** after this code lands. They are specified in `docs/OCI_PRODUCTION.md`, not automated in v1.
