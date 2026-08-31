# OCI 실서비스 (jhunnet-stock)

이 PC는 디버그·기능 구현만 합니다. **자동매매와 `https://stock.jhunnet.com` 은 오라클 매매 VM**에서 돌립니다. 홈페이지 VM(`jhunnet-web`, `193.123.160.126`, `jhunnet.com`)은 건드리지 않습니다.

설계: [2026-08-27-oracle-server-trading-design.md](superpowers/specs/2026-08-27-oracle-server-trading-design.md)

## 기록 (VM 생성 후 기입)

| 항목 | 값 |
|------|-----|
| SSH | `ssh -i $env:USERPROFILE\.ssh\jhunnet-migrate ubuntu@168.110.39.205` |
| 공인 IP | `168.110.39.205` (생성 시 ephemeral. 콘솔에서 Reserved로 고정 권장) |
| Shape | `VM.Standard.E2.1.Micro` (A1 용량 없음 → 폴백). x86_64, RAM 1GB, Ubuntu 22.04, Python 3.10 venv + systemd |
| Origin 인증서 | `/etc/ssl/cloudflare/stock.jhunnet.com.pem` → homepage `*.jhunnet.com` 와일드카드 |
| 앱 경로 | `/home/ubuntu/apps/ai_stock` |
| 런타임 | systemd `ai-stock-web` · `ai-stock-bot` 둘 다 enable (2026-08-28 컷오버) |

배포:

```powershell
$env:OCI_STOCK_IP = "<STOCK_IP>"
.\scripts\deploy-oci.ps1
# Micro 폴백: .\scripts\deploy-oci.ps1 -Runtime systemd
```

## 1) Compute VM

콘솔: https://cloud.oracle.com → 리전 **Tokyo (`ap-tokyo-1`)** (홈페이지와 동일).

1. VCN: `jhunnet-web` 과 **같은 VCN·퍼블릭 서브넷**
2. 인스턴스 이름: `jhunnet-stock`
3. 이미지: **Ubuntu 22.04**
4. Shape **우선:** Always Free `VM.Standard.A1.Flex` — 1 OCPU, 6 GB RAM, 부트 50 GB  
   **A1 용량 없음:** 두 번째 Always Free `VM.Standard.E2.1.Micro`
5. SSH 키: 기존 `jhunnet-migrate` **공개키** (`C:\Users\Windows11\.ssh\jhunnet-migrate.pub`)
6. 퍼블릭 IPv4: **Reserved/Ephemeral 고정** (재부팅 후 IP가 바뀌면 키움 허용 IP가 깨짐)
7. Security List / NSG inbound: **22, 80, 443** (`0.0.0.0/0`). **8081은 열지 않음**

A1이 ARM이므로 Docker 공식 `python:3.12-slim` arm64를 씁니다. Micro는 x86입니다.

## 2) 서버 패키지

```bash
sudo apt-get update
sudo apt-get install -y git nginx
# A1 (Docker 경로)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
# 재로그인 후 docker 가 sudo 없이 되는지 확인
```

Micro 폴백 (Docker 없음):

```bash
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
```

호스트 시간대는 UTC로 둬도 됩니다. 앱은 `TZ=Asia/Seoul` 로 장 시간을 맞춥니다.

## 3) GitHub clone (deploy key)

1. GitHub `ecipeterch-collab/ai_stock` → Settings → Deploy keys → read-only 공개키 등록
2. 서버:

```bash
mkdir -p /home/ubuntu/apps
# deploy key 를 ~/.ssh/ai_stock_deploy 로 두고 github.com 용 IdentityFile 설정
git clone git@github.com:ecipeterch-collab/ai_stock.git /home/ubuntu/apps/ai_stock
```

HTTPS + PAT 도 가능하나 키를 서버에 오래 두지 마세요.

## 4) 비밀값·데이터 (PC → 서버, 최초 1회)

PC에서 PC의 `auto_trade.py` / cloudflared / `run_web.py` 를 **먼저 중지**한 뒤:

```powershell
$ip = "<STOCK_IP>"
$k = "$env:USERPROFILE\.ssh\jhunnet-migrate"
scp -i $k config\config.py config\local_secrets.py ubuntu@${ip}:/home/ubuntu/apps/ai_stock/config/
scp -i $k data\positions.json data\trade_journal.jsonl data\runtime_settings.json ubuntu@${ip}:/home/ubuntu/apps/ai_stock/data/
```

서버 `config/config.py` 에서 반드시:

```python
web_host = "127.0.0.1"
web_port = 8081
web_tunnel_enabled = False
web_public_url = "https://stock.jhunnet.com"
```

`use_paper` 는 컷오버 시점의 실서비스 의도를 그대로 복사합니다. 이후 **이 PC의 `config.py` 는 `use_paper = True`** 로 두고, 같은 실전 앱키로 `auto_trade.py` 를 켜지 않습니다.

## 5) 키움 허용 IP

키움 OpenAPI 콘솔에 **매매 VM 예약 공인 IP**를 등록한 뒤에야 서버에서 토큰이 발급됩니다. 확인:

```bash
cd /home/ubuntu/apps/ai_stock
# Docker: docker compose -f deploy/docker-compose.yml run --rm bot python main.py
# systemd: /home/ubuntu/apps/ai_stock/.venv/bin/python main.py
```

## 6) nginx + Cloudflare

```bash
sudo mkdir -p /etc/ssl/cloudflare
# Origin 인증서 설치 (stock.jhunnet.com 또는 SAN에 stock 이 있는 *.jhunnet.com)
sudo cp deploy/nginx-stock.jhunnet.com.conf.example /etc/nginx/sites-available/stock-jhunnet
sudo ln -s /etc/nginx/sites-available/stock-jhunnet /etc/nginx/sites-enabled/stock-jhunnet
sudo nginx -t && sudo systemctl reload nginx
```

Cloudflare DNS (존 `jhunnet.com`):

- `stock` A → 매매 VM IP, **프록시 ON**
- SSL: **Full (strict)** (`jhunnet.com` 과 동일)
- `jhunnet.com` / `www` 레코드는 변경하지 않음

PC의 named tunnel(`ai-stock`)은 DNS 전환 **전에 중지**합니다. 두 origin이 동시에 `stock.jhunnet.com` 을 받으면 안 됩니다.

## 7) 프로세스 기동

**A1 / Docker**

```bash
cd /home/ubuntu/apps/ai_stock
docker compose -f deploy/docker-compose.yml up -d --build
sudo systemctl enable nginx docker
```

**Micro / systemd**

```bash
cd /home/ubuntu/apps/ai_stock
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp deploy/ai-stock-bot.service /etc/systemd/system/
sudo cp deploy/ai-stock-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-stock-bot ai-stock-web nginx
```

## 8) 스모크

1. 컨테이너/서비스 안에서 시각이 KST인지
2. `python main.py` (또는 compose `run`) 예수금 조회
3. `curl -sS https://stock.jhunnet.com/api/health` → `"ok": true`, `"host"` 가 `jhunnet-stock`
4. 폰에서 로그인, 상단 메타에 호스트 이름
5. 텔레그램 `/status`
6. `/auto on` 후 한 사이클(서버 설정된 모의/실전)

홈페이지 회귀: `https://jhunnet.com` 이 그대로인지.

## 이중 실행

서버가 실전(또는 해당 앱키의) `auto_trade.py` **유일 프로세스**입니다. PC에서 같은 앱키로 봇을 켜면 키움 토큰이 충돌합니다. 비상으로 PC에서 돌리려면 **먼저 서버 봇을 중지**하세요.

## 롤백

서버에서 이전 커밋으로 `git checkout` 후 compose/systemd 재시작. 홈페이지 VM은 롤백 대상이 아닙니다.
