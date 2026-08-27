# Deploy ai_stock to the OCI production VM (jhunnet-stock).
# Does not copy secrets or data/.
param(
    [string]$HostIp = $env:OCI_STOCK_IP,
    [string]$KeyPath = (Join-Path $env:USERPROFILE ".ssh\jhunnet-migrate"),
    [ValidateSet("docker", "systemd")]
    [string]$Runtime = "docker",
    [string]$RemoteDir = "/home/ubuntu/apps/ai_stock"
)

$ErrorActionPreference = "Stop"

if (-not $HostIp) {
    throw "HostIp 가 없습니다. -HostIp x.x.x.x 또는 env OCI_STOCK_IP 를 지정하세요."
}
if (-not (Test-Path $KeyPath)) {
    throw "SSH 키가 없습니다: $KeyPath"
}

$sshTarget = "ubuntu@${HostIp}"

Write-Host "git pull on ${sshTarget}:${RemoteDir}"
ssh -i $KeyPath -o BatchMode=yes $sshTarget "set -e; cd '$RemoteDir'; git pull --ff-only origin main"

if ($Runtime -eq "docker") {
    Write-Host "docker compose up --build"
    ssh -i $KeyPath -o BatchMode=yes $sshTarget "set -e; cd '$RemoteDir'; docker compose -f deploy/docker-compose.yml up -d --build"
} else {
    Write-Host "systemctl restart ai-stock-bot ai-stock-web"
    ssh -i $KeyPath -o BatchMode=yes $sshTarget "sudo systemctl restart ai-stock-bot ai-stock-web"
}

Write-Host "done"
