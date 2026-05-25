# GitHub 백업 푸시 스크립트 (PowerShell)
# 사용법: cd c:\ai_stock; .\scripts\push-github-backup.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "=== ai_stock GitHub 백업 ===" -ForegroundColor Cyan

# gh 로그인 확인
$ghOk = $false
try {
    gh auth status 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ghOk = $true }
} catch { }

if (-not $ghOk) {
    Write-Host "GitHub 로그인이 필요합니다. 아래 명령을 실행한 뒤 브라우저에서 승인하세요:" -ForegroundColor Yellow
    Write-Host "  gh auth login" -ForegroundColor White
    exit 1
}

# 변경사항 커밋
$status = git status --porcelain
if ($status) {
    git add -A
    $msg = "Backup $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    $env:GIT_AUTHOR_NAME = "ai_stock"
    $env:GIT_AUTHOR_EMAIL = "ai_stock@users.noreply.github.com"
    $env:GIT_COMMITTER_NAME = $env:GIT_AUTHOR_NAME
    $env:GIT_COMMITTER_EMAIL = $env:GIT_AUTHOR_EMAIL
    git commit -m $msg
    Write-Host "커밋 완료: $msg" -ForegroundColor Green
} else {
    Write-Host "커밋할 변경 없음 (이미 최신)" -ForegroundColor Gray
}

# 원격 저장소 없거나 push 실패 시 새 private 저장소 생성
$pushOk = $false
try {
    git push -u origin main 2>$null
    if ($LASTEXITCODE -eq 0) { $pushOk = $true }
} catch { }

if (-not $pushOk) {
    Write-Host "원격 push 실패 — GitHub에 private 저장소를 만들고 푸시합니다..." -ForegroundColor Yellow
    git remote remove origin 2>$null
    gh repo create ai-stock --private --source=. --remote=origin --push
    if ($LASTEXITCODE -ne 0) {
        Write-Host "실패. 수동: gh repo create ai-stock --private --source=. --remote=origin --push" -ForegroundColor Red
        exit 1
    }
}

$url = gh repo view --json url -q .url 2>$null
Write-Host "백업 완료: $url" -ForegroundColor Green
