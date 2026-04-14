# THIRAMAI — verify Docker stack, Alembic, and /health/ready (one step at a time).
# Usage (from repo root): powershell -ExecutionPolicy Bypass -File scripts/verify_stack.ps1
# Uses docker compose exec -T to avoid TTY-related hangs.

param(
    [string]$EnvFile = ".env.production",
    [string]$ComposeFile = "docker-compose.production.yml",
    [int]$WebPort = 8000,
    [int]$ExecTimeoutSec = 120,
    [int]$CurlTimeoutSec = 15
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "=== $Message ===" -ForegroundColor Cyan
}

function Invoke-DockerCompose {
    param([string[]]$Args)
    $exe = "docker"
    $all = @("compose", "-f", $ComposeFile, "--env-file", $EnvFile) + $Args
    $out = Join-Path $env:TEMP "thiramai_verify_stdout.txt"
    $err = Join-Path $env:TEMP "thiramai_verify_stderr.txt"
    Remove-Item -Force -ErrorAction SilentlyContinue $out, $err
    $p = Start-Process -FilePath $exe -ArgumentList $all -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    if (-not $p.WaitForExit($ExecTimeoutSec * 1000)) {
        try { $p.Kill() } catch { }
        throw "Timeout (${ExecTimeoutSec}s): docker $($all -join ' ')"
    }
    if (Test-Path $out) { Get-Content $out -Raw | Write-Host }
    if (Test-Path $err) {
        $e = Get-Content $err -Raw
        if ($e.Trim().Length -gt 0) { Write-Host $e -ForegroundColor Yellow }
    }
    if ($p.ExitCode -ne 0) {
        Write-Host "(exit code $($p.ExitCode))" -ForegroundColor Red
    }
    return $p.ExitCode
}

if (-not (Test-Path $EnvFile)) {
    Write-Host "ERROR: Env file not found: $Root\$EnvFile" -ForegroundColor Red
    Write-Host "Copy .env.production.example to .env.production and set secrets." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $ComposeFile)) {
    Write-Host "ERROR: Compose file not found: $Root\$ComposeFile" -ForegroundColor Red
    exit 1
}

Write-Step "docker compose ps"
$null = Start-Process -FilePath "docker" -ArgumentList @("compose", "-f", $ComposeFile, "--env-file", $EnvFile, "ps") `
    -NoNewWindow -Wait

Write-Step "alembic current (exec -T, timeout ${ExecTimeoutSec}s)"
try {
    $code = Invoke-DockerCompose -Args @("exec", "-T", "web", "alembic", "current")
    if ($code -ne 0) {
        Write-Host "If exec failed, try: docker compose -f $ComposeFile --env-file $EnvFile logs web --tail 200" -ForegroundColor Yellow
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Fallback: docker compose -f $ComposeFile --env-file $EnvFile logs web --tail 200" -ForegroundColor Yellow
}

Write-Step "GET http://127.0.0.1:${WebPort}/health/ready (timeout ${CurlTimeoutSec}s)"
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:${WebPort}/health/ready" -UseBasicParsing -TimeoutSec $CurlTimeoutSec
    Write-Host "HTTP $($r.StatusCode)" -ForegroundColor Green
    Write-Host $r.Content
} catch {
    $resp = $_.Exception.Response
    if ($resp -and $resp.StatusCode) {
        Write-Host "HTTP $([int]$resp.StatusCode) (not ready or error)" -ForegroundColor Yellow
    }
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "Done. See docs/OPS_TERMINAL_AND_DOCKER.md for recovery and manual commands." -ForegroundColor Cyan
