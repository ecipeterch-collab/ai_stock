# Cloudflare named tunnel → https://stock.jhunnet.com (재시작해도 URL 고정)
$ErrorActionPreference = "Stop"

$TunnelName = "ai-stock"
$PublicHost = "stock.jhunnet.com"
$Port = 8081
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ConfigOut = Join-Path $RepoRoot "config\cloudflared.yml"
$CertPath = Join-Path $env:USERPROFILE ".cloudflared\cert.pem"

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    throw "cloudflared 가 없습니다. winget install Cloudflare.cloudflared"
}

if (-not (Test-Path $CertPath)) {
    Write-Host "브라우저에서 Cloudflare 로그인 후 jhunnet.com 존을 선택하세요."
    cloudflared tunnel login
    if (-not (Test-Path $CertPath)) {
        throw "로그인 인증서($CertPath)가 없습니다. 브라우저에서 도메인 선택을 완료하세요."
    }
}

$existing = cloudflared tunnel list 2>&1 | Out-String
if ($existing -notmatch [regex]::Escape($TunnelName)) {
    Write-Host "터널 생성: $TunnelName"
    cloudflared tunnel create $TunnelName
} else {
    Write-Host "터널이 이미 있습니다: $TunnelName"
}

$cred = Get-ChildItem (Join-Path $env:USERPROFILE ".cloudflared\*.json") |
    Where-Object { $_.Name -ne "cert.pem" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $cred) {
    throw "터널 credentials JSON 을 찾지 못했습니다. ~/.cloudflared 를 확인하세요."
}

Set-Location $RepoRoot
python -c @"
from pathlib import Path
from web.tunnel import named_tunnel_config_text
text = named_tunnel_config_text(
    tunnel='$TunnelName',
    credentials_file=r'$($cred.FullName)',
    hostname='$PublicHost',
    port=$Port,
)
path = Path(r'$ConfigOut')
path.write_text(text, encoding='utf-8')
print(path)
"@

Write-Host "DNS 라우트: $PublicHost → $TunnelName"
cloudflared tunnel route dns $TunnelName $PublicHost

Write-Host ""
Write-Host "완료. 고정 URL: https://$PublicHost"
Write-Host "웹 서버를 재시작하세요: python run_web.py"
Write-Host "config.py 에 web_public_url / web_tunnel_name 이 설정돼 있어야 합니다."
