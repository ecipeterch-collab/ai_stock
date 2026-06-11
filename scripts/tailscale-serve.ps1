# Tailscale Serve: 로컬 8080 웹 대시보드를 tailnet HTTPS로 노출
# 사용: 관리자 PowerShell → .\scripts\tailscale-serve.ps1

$ErrorActionPreference = "Stop"
$Port = if ($env:WEB_PORT) { [int]$env:WEB_PORT } else { 8080 }

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command "tailscale")) {
    Write-Host @"

Tailscale이 설치되어 있지 않습니다.
  1. https://tailscale.com/download/windows 에서 설치
  2. 로그인 후 이 스크립트를 다시 실행하세요.

"@ -ForegroundColor Yellow
    exit 1
}

Write-Host "=== Tailscale 상태 ===" -ForegroundColor Cyan
& tailscale status

Write-Host "`n=== 기존 Serve 설정 ===" -ForegroundColor Cyan
& tailscale serve status 2>$null

Write-Host "`n로컬 웹 서버가 127.0.0.1:${Port} 에서 실행 중인지 확인하세요:" -ForegroundColor Yellow
Write-Host "  python run_web.py" -ForegroundColor White
Write-Host "  config.py: web_host = '127.0.0.1', web_port = $Port`n" -ForegroundColor White

try {
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
    if (-not $tcp.TcpTestSucceeded) {
        Write-Host "경고: 127.0.0.1:${Port} 에 연결되지 않습니다. run_web.py 를 먼저 실행하세요.`n" -ForegroundColor Red
    }
} catch {
    # Test-NetConnection 미지원 환경은 무시
}

Write-Host "Tailscale Serve 시작 (HTTPS → http://127.0.0.1:${Port}) ..." -ForegroundColor Cyan
& tailscale serve --bg $Port
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n실패 시 Admin 콘솔에서 MagicDNS·Enable HTTPS 를 켜고 다시 시도하세요." -ForegroundColor Yellow
    Write-Host "  https://login.tailscale.com/admin/dns" -ForegroundColor Gray
    exit $LASTEXITCODE
}

Write-Host "`n=== Serve URL ===" -ForegroundColor Green
& tailscale serve status

Write-Host @"

폰에서:
  1. Tailscale 앱 설치 후 같은 계정 로그인
  2. 위 HTTPS URL 로 접속 → 웹 로그인

중지: .\scripts\stop-tailscale-serve.ps1

"@ -ForegroundColor Green
