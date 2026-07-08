# 코인+주식 통합 Caddy 게이트웨이 (:8080)
# 사용: .\scripts\gateway-serve.ps1
# 사전: ai_coin WEB_PORT=8082, ai_stock web_port=8081, deploy\Caddyfile.multi 준비

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Caddyfile = Join-Path $Root "deploy\Caddyfile.multi"
$Example = Join-Path $Root "deploy\Caddyfile.multi.example"

if (-not (Test-Path $Caddyfile)) {
    if (Test-Path $Example) {
        Copy-Item $Example $Caddyfile
        Write-Host "deploy\Caddyfile.multi 생성됨." -ForegroundColor Yellow
    } else {
        Write-Host "deploy\Caddyfile.multi.example 없음" -ForegroundColor Red
        exit 1
    }
}

$caddy = Get-Command caddy -ErrorAction SilentlyContinue
if (-not $caddy) {
    Write-Host "Caddy 미설치: winget install CaddyServer.Caddy" -ForegroundColor Yellow
    exit 1
}

Write-Host @"

통합 게이트웨이 시작 (:8080)
  코인  -> 127.0.0.1:8082  (ai_coin WEB_PORT=8082, TUNNEL_ENABLED=false)
  주식  -> 127.0.0.1:8081  (ai_stock web_port=8081)
  코인 UI:  http://127.0.0.1:8080/
  주식 UI:  http://127.0.0.1:8080/stock
  외부 터널: cloudflared tunnel --url http://127.0.0.1:8080

"@ -ForegroundColor Cyan

Push-Location (Join-Path $Root "deploy")
try {
    & caddy run --config Caddyfile.multi
} finally {
    Pop-Location
}
