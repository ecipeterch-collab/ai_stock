# 코인봇 + AI Stock 동시 운영 (API 분리)

같은 PC에서 **ai_coin**(업비트)과 **ai_stock**(키움) 웹을 함께 쓰려면 **8080 포트를 두 프로세스가 동시에 쓰면 안 됩니다.**

| 앱 | 경로 | 기본 포트 | 주요 API |
|----|------|-----------|----------|
| **AI Coin** | `C:\ai_coin` | 8080 | `/api/status`, `/api/chart/KRW-*`, `/api/start` … |
| **AI Stock** | `C:\ai_stock` | 8080 → **8081 권장** | `/api/dashboard`, `/api/journal/*`, `/api/account/*` |

터널 URL 하나에 코인 UI를 붙여 두고, 주식만 404 나는 경우 → 터널이 **코인 서버가 아닌 주식 서버**(또는 그 반대)만 가리키고 있을 때 발생합니다.

---

## 방법 A — 포트 분리 (가장 간단, 권장)

각 앱을 **다른 포트**로 띄우고, 접속 URL만 나눕니다.

### 1) AI Coin — 8080 유지

`C:\ai_coin\.env`:

```env
WEB_PORT=8080
WEB_HOST=0.0.0.0
TUNNEL_ENABLED=true
```

```powershell
cd C:\ai_coin
python main.py web
```

→ 코인 UI: `http://127.0.0.1:8080`  
→ 외부: 터미널에 출력되는 `https://xxxx.trycloudflare.com`

### 2) AI Stock — 8081로 변경

`C:\ai_stock\config\config.py`:

```python
web_host = "127.0.0.1"
web_port = 8081
```

```powershell
cd C:\ai_stock
python run_web.py
```

→ 주식 UI: `http://127.0.0.1:8081`

### 3) 외부 접속 (주식)

- **Tailscale** (권장): `tailscale serve --bg 8081` → `https://<PC>.ts.net`
- 또는 **별도 cloudflared**: `cloudflared tunnel --url http://127.0.0.1:8081`

| 용도 | URL |
|------|-----|
| 코인 (LTE) | coin 터널 URL (`trycloudflare.com`) |
| 주식 (LTE) | 주식용 터널 / Tailscale URL |
| 둘 다 LAN | `:8080` / `:8081` |

**장점:** 코드 수정 없음, 충돌 없음  
**단점:** 북마크·터널 URL 두 개

---

## 방법 B — Caddy 게이트웨이 (URL 하나, 경로 분리)

역프록시 **한 곳(8080)** 에서 경로로 나눕니다.

```
[폰/LTE] → cloudflared → Caddy :8080
                              ├─ /              → 코인 :8082
                              ├─ /api/status …  → 코인 :8082
                              ├─ /stock/*       → 주식 :8081
                              ├─ /api/dashboard → 주식 :8081
                              └─ /static/*      → 주식 :8081
```

### 설정

**ai_coin** `C:\ai_coin\.env`:

```env
WEB_PORT=8082
WEB_HOST=127.0.0.1
TUNNEL_ENABLED=false
```

**ai_stock** `config/config.py`:

```python
web_host = "127.0.0.1"
web_port = 8081
```

**Caddy** — `deploy/Caddyfile.multi` (예시는 `deploy/Caddyfile.multi.example` 복사):

```powershell
copy deploy\Caddyfile.multi.example deploy\Caddyfile.multi
```

### 실행 순서

터미널 1~3:

```powershell
cd C:\ai_coin; python main.py web
cd C:\ai_stock; python run_web.py
cd C:\ai_stock; .\scripts\gateway-serve.ps1
```

터미널 4 — **게이트웨이**에만 터널:

```powershell
cloudflared tunnel --url http://127.0.0.1:8080
```

| URL | 화면 |
|-----|------|
| `https://터널/` | 코인 대시보드 |
| `https://터널/stock` | AI Stock 대시보드 |

**장점:** 터널 URL 하나  
**주의:** 코인 내장 터널(`TUNNEL_ENABLED`)은 끄고, **8080은 Caddy만** 사용

---

## 방법 C — Tailscale 경로 분리

Tailscale Serve로 같은 HTTPS 호스트에 경로를 나눕니다.

```powershell
# 코인 8080, 주식 8081 먼저 실행
tailscale serve --bg --https=443 http://127.0.0.1:8080
tailscale serve --bg --https=443 /stock http://127.0.0.1:8081
```

| URL | 앱 |
|-----|-----|
| `https://<PC>.ts.net/` | 코인 |
| `https://<PC>.ts.net/stock` | 주식 (API는 `/api/dashboard` 등 그대로 — Caddy와 동일하게 API 라우팅 필요 시 방법 B 사용) |

Tailscale만으로는 `/api/*` 분기가 안 되므로, **주식을 `/stock` 아래에 두려면 방법 B(Caddy)가 더 안전**합니다.

---

## API 경로 참고 (충돌 여부)

두 앱의 `/api/*` 경로는 **겹치지 않습니다.** (게이트웨이 라우팅 가능)

| 코인 (→ 8082) | 주식 (→ 8081) |
|---------------|---------------|
| `/api/status` | `/api/dashboard` |
| `/api/chart/{ticker}` | `/api/journal/*` |
| `/api/charts/positions` | `/api/account/*` |
| `/api/start`, `/stop`, `/scan` … | `/api/auth/login` |

UI 루트 `/` 는 **둘 다 사용** → 게이트웨이 없이 한 포트에 두 앱을 동시에 둘 수 없습니다.

---

## 문제 해결

| 증상 | 원인 | 조치 |
|------|------|------|
| `/api/status` 404 on ai_stock | 코인 API를 주식 서버에 요청 | 코인은 `:8080`, 주식은 `:8081` 분리 |
| `/api/dashboard` 404 on coin | 주식 API를 코인 서버에 요청 | URL·터널 대상 확인 |
| 포트 already in use | 8080 중복 | 한쪽 `web_port`/`WEB_PORT` 변경 |
| 터널 URL 바뀜 | trycloudflare 임시 터널 | 재시작마다 로그 확인 또는 named tunnel |

---

## 권장 조합 (실사용)

1. **코인**: `8080` + `TUNNEL_ENABLED=true` (기존 그대로)
2. **주식**: `8081` + Tailscale Serve 또는 별도 터널
3. LTE에서 URL 하나로 통합이 필요하면 → **방법 B (Caddy 게이트웨이)**

체크리스트:

- [ ] ai_stock `web_port = 8081`
- [ ] 두 `python` 프로세스 동시 실행 확인
- [ ] 터널이 **Caddy 8080** 또는 **각 앱 포트**를 올바르게 가리키는지 확인
- [ ] 코인·주식 **비밀번호/PIN** 각각 강하게 설정
