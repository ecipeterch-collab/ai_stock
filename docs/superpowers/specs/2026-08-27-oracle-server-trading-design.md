# Oracle Server Production Trading Design

Date: 2026-08-27  
Status: Approved

## Goal

Run live AI Stock (Kiwoom REST auto-trading + web dashboard) on a dedicated Oracle Cloud VM so the Windows PC can stay off except for debugging and feature work. `https://stock.jhunnet.com` stays the public dashboard URL.

## Decisions (locked)

- Development: this PC only. Production: Oracle VM only.
- Homepage VM `jhunnet-web` (`193.123.160.126`, `jhunnet.com`) is untouched.
- New Always Free VM in `ap-tokyo-1`, name `jhunnet-stock`.
- Prefer Ampere A1 + Docker Compose. If A1 capacity is missing, second AMD Micro + systemd.
- Dashboard: Cloudflare proxy to the new VM (no cloudflared on the server).
- Same Kiwoom app key must not run `auto_trade.py` on PC and server at the same time.

## Current state

| Item | Value |
|------|--------|
| Trading app | Kiwoom REST (`https://api.kiwoom.com`), Python 3.10+, Telegram bot + FastAPI web |
| Dev/prod today | Both on the Windows PC (`auto_trade.py`, `run_web.py`) |
| Dashboard URL | `https://stock.jhunnet.com` via cloudflared named tunnel from the PC |
| Git | `https://github.com/ecipeterch-collab/ai_stock.git` (`main`) |
| Homepage OCI | `ap-tokyo-1`, `VM.Standard.E2.1.Micro`, Ubuntu 20.04, nginx + Docker app on `:3002` |
| Homepage SSH | `ubuntu@193.123.160.126`, key `C:\Users\Windows11\.ssh\jhunnet-migrate` |
| Homepage TZ | UTC |
| Market clock in code | `datetime.now()` (naive). Production must run with `TZ=Asia/Seoul`. |

## Architecture

```text
Dev PC  --git push-->  GitHub main  --git pull-->  jhunnet-stock VM

Phone / browser
  -> Cloudflare HTTPS  stock.jhunnet.com
    -> nginx :443 (Origin Certificate) on jhunnet-stock
      -> 127.0.0.1:8081  ai-stock-web (run_web.py)

ai-stock-bot (auto_trade.py)
  -> Kiwoom REST, Telegram API, Google News RSS
  -> ./data  (positions, journal, runtime_settings)
```

`jhunnet-web` continues to serve only `jhunnet.com`. It does not run the trading bot.

## VM

Primary (try first):

- Region: `ap-tokyo-1` (same tenancy/compartment as `jhunnet-web`)
- Shape: `VM.Standard.A1.Flex`, 1 OCPU, 6 GB RAM
- Image: Ubuntu 22.04
- Boot volume: 50 GB
- Display name / hostname: `jhunnet-stock`
- SSH: reuse `jhunnet-migrate` public key, user `ubuntu`
- Networking: same VCN as `jhunnet-web`, public subnet, **reserved** public IPv4
- Security list / NSG inbound: 22, 80, 443 from `0.0.0.0/0` (same pattern as `jhunnet-web`). No public 8081.
- Outbound: default allow (Kiwoom, Telegram, GitHub, news RSS, apt/docker)

Fallback if A1 is out of capacity:

- Shape: second Always Free `VM.Standard.E2.1.Micro` (1 GB RAM, x86_64)
- Same Ubuntu 22.04, reserved IP, nginx, Cloudflare
- Process manager: systemd + Python 3.12 venv instead of Docker (avoids Docker daemon RAM)
- Same app paths, ports, and env (`TZ=Asia/Seoul`)

Do not resize or replace `jhunnet-web`.

## Processes

| Name | Command | Bind | Restart |
|------|---------|------|---------|
| `ai-stock-bot` | `python auto_trade.py` | none (outbound + Telegram long-poll) | always |
| `ai-stock-web` | `python run_web.py` | `127.0.0.1:8081` | always |

Shared files on the VM (not overwritten by deploy):

- `config/config.py`
- `config/local_secrets.py`
- `data/positions.json`
- `data/trade_journal.jsonl`
- `data/runtime_settings.json`
- `data/news_sentiment.jsonl`

Production config (server `config.py`, distinct from PC):

- `web_host = "127.0.0.1"`
- `web_port = 8081`
- `web_tunnel_enabled = False`
- `web_public_url = "https://stock.jhunnet.com"`
- `TZ=Asia/Seoul` in the process environment (do not rely on host timezone; homepage host stays UTC)

`use_paper` on the server is copied from the PC’s live intent at cutover. After cutover the PC must use `use_paper = True` for any local `auto_trade.py` run.

Python: 3.12 everywhere. A1 uses image `python:3.12-slim`. Micro fallback installs 3.12 with the deadsnakes PPA into a venv. Host Python 3.8 on `jhunnet-web` is unused.

## Docker (A1 path)

Repo files:

- `deploy/docker-compose.yml` — services `bot` and `web`, `restart: unless-stopped`, env `TZ=Asia/Seoul`, bind-mount repo root read-write for `config/` and `data/`
- `deploy/Dockerfile` — install `requirements.txt`, `WORKDIR` repo root, run as root in v1 so bind-mounted `config/` and `data/` owned by `ubuntu` stay writable
- `.dockerignore` — exclude `.git`, `__pycache__`, `.venv`, `tests/`

Compose publishes only `127.0.0.1:8081:8081`. nginx on the host proxies to that address. Do not use `network_mode: host`.

## nginx + Cloudflare

On `jhunnet-stock`:

- nginx site `stock-jhunnet` listens 80 (redirect to 443) and 443 with Cloudflare Origin Certificate for `stock.jhunnet.com` (or `*.jhunnet.com`)
- `proxy_pass http://127.0.0.1:8081`
- Standard proxy headers (`Host`, `X-Forwarded-For`, `X-Forwarded-Proto`)

Cloudflare DNS (same zone as `jhunnet.com`):

- `stock` A record → reserved IP of `jhunnet-stock`, proxy enabled (orange cloud)
- SSL/TLS: Full (strict), matching homepage
- Do not change `jhunnet.com` / `www` records

Cutover of the name: stop the PC cloudflared named tunnel **before** or at the same time as pointing DNS, so two origins do not compete.

## Deploy

GitHub is the code source of truth. Secrets are not in git.

1. Install a read-only GitHub deploy key on `jhunnet-stock` for `ecipeterch-collab/ai_stock`.
2. Clone to `/home/ubuntu/apps/ai_stock`.
3. Copy `config/config.py` and `config/local_secrets.py` once via SCP from the PC; then edit server copies as above.
4. At cutover, copy `data/` from the PC once so positions and journal continue.

PC script `scripts/deploy-oci.ps1`:

- SSH with `jhunnet-migrate` to `ubuntu@<STOCK_VM_IP>`
- `git fetch && git checkout main && git pull`
- A1: `docker compose -f deploy/docker-compose.yml up -d --build`
- Micro fallback: `sudo systemctl restart ai-stock-bot ai-stock-web`
- Does not copy `config/local_secrets.py` or `data/`

Prefer deploy after market close (`15:30` KST). Intraday deploy is allowed; the bot process restarts and restores auto-trading from `runtime_settings.json`.

Document SSH host alias and IP in `docs/OCI_PRODUCTION.md` (operator runbook). Do not commit private keys.

## Dual-run prevention

Production `auto_trade.py` exists only on `jhunnet-stock`.

- PC default after cutover: `use_paper = True`. Real-key auto trading on the PC is an emergency-only, documented exception and requires stopping the server bot first.
- Dashboard payload includes `runtime_host` (`socket.gethostname()`) so the phone UI shows `jhunnet-stock` vs the PC name.
- README + `docs/OCI_PRODUCTION.md` state: never start PC `auto_trade.py` with the production app key while the server bot is up (Kiwoom token conflict).

## Data flow

1. Bot loop (swing: `auto_interval_sec`, default 90s) calls Kiwoom REST, writes `data/`, sends Telegram on trade events only.
2. Web reads the same `data/` and Kiwoom for the dashboard.
3. Unauthenticated `GET /api/health` returns `{"ok": true, "host": "<hostname>"}` with no secrets (Cloudflare/nginx can probe this).
4. Authenticated dashboard keeps existing JWT login (`web_username` / `web_password`).

## Failure handling

| Event | Response |
|-------|----------|
| Bot or web crash | Docker/systemd restarts the process. Bot restores auto loop if `auto_trading_enabled` is true. |
| Kiwoom/network errors | Existing Telegram notify + cooldown. No new retry policy. |
| VM reboot | Services enabled at boot. Bot comes back before next market open if reboot is overnight. |
| Public IP change | Must not happen: use reserved IP. If it does, update Kiwoom allow-list and Cloudflare A record. |
| A1 unavailable at create | Create Micro in the same VCN, use systemd path, same nginx/DNS steps. |
| Bad deploy | `git checkout <previous-sha>` on the VM and restart. Homepage VM is not part of rollback. |
| Server down (no Telegram) | Operator checks `https://stock.jhunnet.com/api/health` and SSH. No extra watchdog in v1. |

## Kiwoom IP allow-list

Register the **reserved public IPv4** of `jhunnet-stock` in the Kiwoom OpenAPI console before expecting token issue from the VM. Remove or keep the home PC IP only if local paper/debug against that key is still required.

## Code changes in this project (small)

Strategy, orders, and chart logic stay unchanged.

Allowed changes:

- `GET /api/health` (no auth)
- Dashboard/status field `runtime_host`
- Leave `run_web.py` port-busy PID lookup Windows-only (`netstat`). Linux uses the existing bind error message.
- Deploy files: `deploy/Dockerfile`, `deploy/docker-compose.yml`, `deploy/nginx-stock.jhunnet.com.conf.example`, `deploy/ai-stock-bot.service`, `deploy/ai-stock-web.service`
- Scripts: `scripts/deploy-oci.ps1`
- Docs: `docs/OCI_PRODUCTION.md`; update `docs/REMOTE_ACCESS.md` and README so production is the OCI VM, PC tunnel is dev-only
- Tests for health endpoint, `runtime_host`, compose/nginx port assertions, systemd unit names

## Testing

Local (PC):

- Existing pytest suite must pass with no strategy changes.
- New tests: `/api/health` shape; dashboard includes `runtime_host`; `web_tunnel_enabled=False` does not start cloudflared (existing tunnel tests).

Server smoke (no live order required for 1–4):

1. Container/service env is KST (`date` inside process or a log line).
2. Token + deposit via `python main.py` on the VM after Kiwoom IP registration.
3. `curl -sI https://stock.jhunnet.com` → 200 and login page; `GET /api/health` → `ok` and host `jhunnet-stock`.
4. Telegram `/status` replies from the server bot.
5. Paper (or the server’s configured mode) one auto cycle with `/auto on` and event notify.

Homepage regression: `https://jhunnet.com` still healthy after stock VM work.

## Success criteria

- PC powered off during a Korean cash-session day: bot still trades and Telegram events still arrive.
- Phone login at `https://stock.jhunnet.com` shows dashboard with `runtime_host` of the stock VM.
- `https://jhunnet.com` unchanged on `jhunnet-web`.
- Reboot of `jhunnet-stock` brings bot and web back without manual SSH.

## Out of scope

- Moving or merging the homepage onto the stock VM
- Changing strategy, sizing, or sell rules
- Windows Kiwoom OpenAPI / COM
- Running the PC as a hot standby trader
- Cloudflare Access / Tailscale as the production path
- Combining bot and web into one process
- Timezone refactor of all `datetime.now()` call sites (KST via process env is the v1 fix)

## Operator runbook

Implementation adds `docs/OCI_PRODUCTION.md` with SSH command, deploy command, Kiwoom IP steps, Cloudflare DNS steps, and cutover order (stop PC tunnel and PC `auto_trade.py` before starting the server bot). After the VM is created, that file records the reserved public IP, shape actually used (A1 or Micro), and origin-cert path. Those three values are unknown until console create succeeds; they are not required to start the implementation plan.
