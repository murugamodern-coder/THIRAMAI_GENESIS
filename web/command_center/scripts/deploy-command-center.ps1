# Production deploy: backup → build → health check → optional rollback + restart.
# From repo root: pwsh web/command_center/scripts/deploy-command-center.ps1
#
# Environment (optional):
#   CC_BASE_URL          — e.g. https://app.example.com (no trailing slash) for post-deploy GET /health/live
#   CC_SKIP_HEALTH       — 1 to skip HTTP health check after build
#   CC_RESTART_CMD       — command to restart app server after successful deploy
#   CC_GIT_SHA           — passed to npm run build (embedded in UI footer)
#   CC_BUILD_VERSION     — override package version string in UI

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$CcDir = Join-Path $Root "web\command_center"
$StaticOut = Join-Path $Root "static\command_center"
$BackupRoot = Join-Path $Root "static\command_center_backups"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = Join-Path $BackupRoot "cc-$Timestamp"

function Test-Health {
  param([string]$Base)
  if ($env:CC_SKIP_HEALTH -eq "1") {
    Write-Host "[deploy-cc] CC_SKIP_HEALTH=1 — skipping HTTP health check."
    return $true
  }
  if (-not $Base -or $Base.Trim() -eq "") {
    Write-Host "[deploy-cc] CC_BASE_URL not set — skipping remote health check (local build only)."
    return $true
  }
  $live = "$Base/health/live"
  try {
    $r = Invoke-WebRequest -Uri $live -UseBasicParsing -TimeoutSec 15
    if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
      Write-Host "[deploy-cc] Health OK: $live"
      return $true
    }
  } catch {
    Write-Warning "[deploy-cc] Health check failed: $live — $($_.Exception.Message)"
    return $false
  }
  return $false
}

New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

Set-Location $CcDir

Write-Host "[deploy-cc] Repo root: $Root"

if (Test-Path $StaticOut) {
  Write-Host "[deploy-cc] Backing up $StaticOut -> $BackupDir"
  New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
  Copy-Item -Path (Join-Path $StaticOut "*") -Destination $BackupDir -Recurse -Force
} else {
  Write-Host "[deploy-cc] No existing static output to backup."
}

if (-not $env:CC_GIT_SHA) {
  try {
    Push-Location $Root
    $env:CC_GIT_SHA = (git rev-parse --short HEAD 2>$null).Trim()
    if (-not $env:CC_GIT_SHA) { $env:CC_GIT_SHA = "unknown" }
  } catch {
    $env:CC_GIT_SHA = "unknown"
  } finally {
    Pop-Location
  }
}
Write-Host "[deploy-cc] CC_GIT_SHA=$($env:CC_GIT_SHA)"

Write-Host "[deploy-cc] Cleaning $StaticOut"
if (Test-Path $StaticOut) {
  Remove-Item -Recurse -Force $StaticOut
}

Write-Host "[deploy-cc] npm ci / npm install"
if (Test-Path (Join-Path $CcDir "package-lock.json")) {
  npm ci
} else {
  npm install
}

Write-Host "[deploy-cc] Lint + build + validate"
npm run build
if ($LASTEXITCODE -ne 0) {
  Write-Warning "[deploy-cc] Build failed — rolling back."
  if (Test-Path $BackupDir) {
    New-Item -ItemType Directory -Force -Path $StaticOut | Out-Null
    Copy-Item -Path (Join-Path $BackupDir "*") -Destination $StaticOut -Recurse -Force
    Write-Host "[deploy-cc] Restored from $BackupDir"
  }
  if ($env:CC_RESTART_CMD) {
    Invoke-Expression $env:CC_RESTART_CMD
  }
  exit 1
}

$baseUrl = $env:CC_BASE_URL
if (-not (Test-Health -Base $baseUrl)) {
  Write-Warning "[deploy-cc] Post-deploy health check failed — rolling back static assets."
  if (Test-Path $BackupDir) {
    if (Test-Path $StaticOut) { Remove-Item -Recurse -Force $StaticOut }
    New-Item -ItemType Directory -Force -Path $StaticOut | Out-Null
    Copy-Item -Path (Join-Path $BackupDir "*") -Destination $StaticOut -Recurse -Force
    Write-Host "[deploy-cc] Restored from $BackupDir"
  }
  if ($env:CC_RESTART_CMD) {
    Invoke-Expression $env:CC_RESTART_CMD
  }
  exit 1
}

if ($env:CC_RESTART_CMD) {
  Write-Host "[deploy-cc] CC_RESTART_CMD: $($env:CC_RESTART_CMD)"
  Invoke-Expression $env:CC_RESTART_CMD
} else {
  Write-Host "[deploy-cc] Set CC_RESTART_CMD to restart your server after deploy."
}

Write-Host "[deploy-cc] Done. Backup retained at $BackupDir"
