# Tailscale Serve 중지
$Port = if ($env:WEB_PORT) { [int]$env:WEB_PORT } else { 8080 }

if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    Write-Host "tailscale 명령을 찾을 수 없습니다." -ForegroundColor Red
    exit 1
}

Write-Host "Tailscale Serve 중지 (포트 $Port) ..." -ForegroundColor Cyan
& tailscale serve $Port off
& tailscale serve status
Write-Host "완료." -ForegroundColor Green
