# 폰·외부에서 웹 대시보드 접속 (Tailscale / HTTPS)

웹 대시보드(`run_web.py`)는 키움 API 키가 있는 PC에서 동작합니다. **인터넷에 포트만 열고 쓰지 마세요.** 아래 두 방법 중 하나를 권장합니다.

| 방법 | 난이도 | HTTPS | 적합한 경우 |
|------|--------|-------|-------------|
| **A. Tailscale Serve** | 쉬움 | 자동 (Tailscale 인증서) | 폰·노트북에서 개인 VPN으로만 접속 |
| **B. Caddy 역프록시** | 보통 | Let's Encrypt (도메인 필요) | 고정 도메인 + 공유기 포트포워딩 |

공통: `config/config.py`에서 `web_password`, `web_secret_key`를 반드시 강하게 설정하세요.

---

## 사전 준비

```powershell
cd C:\ai_stock
pip install -r requirements.txt
```

`config/config.py` 예시 (Tailscale/Caddy 사용 시 **로컬만** 바인딩):

```python
web_host = "127.0.0.1"   # 권장: Tailscale/Caddy가 앞단
web_port = 8080
web_username = "admin"
web_password = "강한비밀번호"
web_secret_key = "32자이상_임의문자열"
```

터미널 1 — 웹 서버:

```powershell
python run_web.py
```

`web_tunnel_enabled = True`(기본)이면 **cloudflared**로 외부 HTTPS URL이 자동 출력됩니다.
(재시작마다 `trycloudflare.com` 주소 변경 — ai_coin과 별도 터널)

설치: `winget install Cloudflare.cloudflared`

터널 끄기: `config/config.py` → `web_tunnel_enabled = False` 후 Tailscale/Caddy 사용

---

## A. Tailscale Serve (권장)

### 1) Tailscale 설치

1. https://tailscale.com/download/windows 에서 설치
2. Microsoft/Google 계정으로 로그인
3. 관리 콘솔 https://login.tailscale.com/admin/machines 에 PC가 보이는지 확인

### 2) HTTPS 노출 (자동 인증서)

**관리자 PowerShell**에서:

```powershell
cd C:\ai_stock
.\scripts\tailscale-serve.ps1
```

또는 수동:

```powershell
# MagicDNS·HTTPS 인증서: Admin 콘솔 → DNS → MagicDNS ON
# Admin 콘솔 → HTTPS → Enable HTTPS ON

tailscale serve --bg 8080
tailscale serve status
```

폰에서 Tailscale 앱 로그인 후 브라우저:

```text
https://<PC이름>.<tailnet>.ts.net/
```

(`tailscale status` 또는 `tailscale serve status`에 표시되는 URL)

### 3) 중지

```powershell
.\scripts\stop-tailscale-serve.ps1
# 또는
tailscale serve 8080 off
```

### 4) 보안 팁

- Admin → **Access controls** 에서 본인 계정만 접근 허용
- **Funnel(공개 인터넷 노출)은 사용하지 마세요** — Serve만 사용
- `web_host = "127.0.0.1"` 로 두면 LAN에서 8080 직접 접속 차단

### 5) 문제 해결

| 증상 | 조치 |
|------|------|
| 인증서/HTTPS 오류 | Admin → DNS → MagicDNS ON, HTTPS → Enable HTTPS ON |
| 502 / 연결 실패 | `python run_web.py` 가 127.0.0.1:8080 에 떠 있는지 확인 |
| 폰에서 안 열림 | 폰 Tailscale VPN 연결 상태 확인 |

---

## B. Caddy 역프록시 (도메인 + 공인 IP)

집에 **고정 도메인**(예: `stock.example.com`)이 있고 공유기에서 **443 → PC** 포트포워딩이 가능할 때 사용합니다.

### 1) Caddy 설치 (Windows)

```powershell
winget install CaddyServer.Caddy
# 또는 https://caddyserver.com/download
```

### 2) 설정

```powershell
copy deploy\Caddyfile.example deploy\Caddyfile
notepad deploy\Caddyfile
```

`deploy\Caddyfile` 에서 도메인을 본인 것으로 수정.

### 3) 실행

웹 서버(`python run_web.py`)가 **127.0.0.1:8080** 에 떠 있는 상태에서:

```powershell
.\scripts\caddy-serve.ps1
```

브라우저: `https://stock.example.com` (설정한 도메인)

### 4) 방화벽

Windows 방화벽에서 **TCP 443** 인바운드 허용 (Caddy).

공유기에서 **외부 443 → PC 내부 IP:443** 포트포워딩.

### 5) Tailscale vs Caddy

- **Tailscale**: 포트포워딩·도메인 불필요, 가장 안전
- **Caddy**: LTE에서 `https://도메인` 으로 접속 가능하지만 PC·공유기가 인터넷에 노출됨 → IP 제한·강한 비밀번호·fail2ban 등 추가 권장

---

## 동시에 쓰기

1. `web_host = "127.0.0.1"`
2. `python run_web.py`
3. Tailscale: `.\scripts\tailscale-serve.ps1` → `https://xxx.ts.net`
4. (선택) Caddy: `.\scripts\caddy-serve.ps1` → `https://yourdomain.com`

둘 다 같은 `127.0.0.1:8080` 을 바라봅니다.

**ai_coin(코인봇)과 함께 쓸 때** → [MULTI_APP.md](MULTI_APP.md) 참고 (포트 8081 분리 또는 Caddy 게이트웨이).

---

## 체크리스트

- [ ] `web_password`, `web_secret_key` 변경
- [ ] `web_host = "127.0.0.1"` (Tailscale/Caddy 사용 시)
- [ ] `python run_web.py` 실행
- [ ] Tailscale Serve 또는 Caddy 실행
- [ ] 폰에서 HTTPS URL 로그인 확인
- [ ] Tailscale Funnel **비활성**
