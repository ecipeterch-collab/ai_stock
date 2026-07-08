# Caddy로 127.0.0.1:8080 을 HTTPS(443)로 노출
# 사용: .\scripts\caddy-serve.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Caddyfile = Join-Path $Root "deploy\Caddyfile"

if (-not (Test-Path $Caddyfile)) {
    $Example = Join-Path $Root "deploy\Caddyfile.example"
    if (Test-Path $Example) {
        Copy-Item $Example $Caddyfile
        Write-Host "deploy\Caddyfile 을 생성했습니다. 도메인을 수정한 뒤 다시 실행하세요." -ForegroundColor Yellow
        notepad $Caddyfile
        exit 1
    }
    Write-Host "deploy\Caddyfile 이 없습니다." -ForegroundColor Red
    exit 1
}

$caddy = Get-Command caddy -ErrorAction SilentlyContinue
if (-not $caddy) {
    Write-Host @"
Caddy가 설치되어 있지 않습니다.
  winget install CaddyServer.Caddy
  또는 https://caddyserver.com/download

"@ -ForegroundColor Yellow
    exit 1
}

$Port = if ($env:WEB_PORT) { [int]$env:WEB_PORT } else { 8081 }
Write-Host "Caddy 시작 (설정: $Caddyfile, 백엔드 127.0.0.1:$Port)" -ForegroundColor Cyan
Write-Host "웹 서버: python run_web.py 가 먼저 실행 중이어야 합니다.`n" -ForegroundColor Yellow

Push-Location (Join-Path $Root "deploy")
try {
    & caddy run --config Caddyfile
} finally {
    Pop-Location
}
