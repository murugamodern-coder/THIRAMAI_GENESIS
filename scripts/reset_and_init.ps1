# THIRAMAI: complete Docker Compose reset (down -v), up --build, migrate, seed.
# Run from repo root:  .\scripts\reset_and_init.ps1
# Requires: Docker Desktop, PowerShell 5.1+ or 7+
# WARNING: Removes DB and Redis volumes - all data in those volumes is lost.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$composeFile = "docker-compose.production.yml"
$envFile = ".env.production"

function Assert-DockerExit {
    param(
        [string]$StepLabel
    )
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: $StepLabel (docker exit $LASTEXITCODE)" -ForegroundColor Red
        Write-Host "Check: docker compose -f $composeFile --env-file $envFile logs" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  THIRAMAI COMPLETE RESET & INITIALIZATION" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This runs: docker compose down -v (deletes DB + Redis volumes)." -ForegroundColor Yellow
Write-Host "Optional backup (Git Bash):  bash scripts/backup_before_reset.sh" -ForegroundColor Yellow
Write-Host ""
$confirm = Read-Host 'Type "yes" to continue'
if ($confirm -ne "yes") {
    Write-Host "Cancelled."
    exit 0
}

Write-Host ""
Write-Host ">> Step 1: down -v" -ForegroundColor Blue
Write-Host "Running: docker compose -f $composeFile --env-file $envFile down -v" -ForegroundColor DarkGray
& docker compose -f $composeFile --env-file $envFile down -v
Assert-DockerExit "docker compose down -v"

Write-Host ""
Write-Host ">> Step 2: verify .env.production" -ForegroundColor Blue
if (-not (Test-Path ".env.production")) {
    Write-Host "FAIL: .env.production not found" -ForegroundColor Red
    exit 1
}
$raw = Get-Content ".env.production" -Raw
if ($raw -notmatch "(?m)^POSTGRES_PASSWORD=") {
    Write-Host "FAIL: POSTGRES_PASSWORD missing" -ForegroundColor Red
    exit 1
}
if ($raw -notmatch "(?m)^DATABASE_URL=") {
    Write-Host "FAIL: DATABASE_URL missing" -ForegroundColor Red
    exit 1
}
Write-Host "OK: .env.production" -ForegroundColor Green

Write-Host ""
Write-Host ">> Step 3: up -d --build (may take several minutes)" -ForegroundColor Blue
Write-Host "Running: docker compose -f $composeFile --env-file $envFile up -d --build" -ForegroundColor DarkGray
& docker compose -f $composeFile --env-file $envFile up -d --build
Assert-DockerExit "docker compose up -d --build"

Write-Host ""
Write-Host ">> Step 4: waiting for Postgres..." -ForegroundColor Blue
Start-Sleep -Seconds 8
$pgUser = "thiramai"
$pgDb = "thiramai"
Get-Content ".env.production" | ForEach-Object {
    if ($_ -match '^\s*POSTGRES_USER=(.+)') { $pgUser = $Matches[1].Trim() }
    if ($_ -match '^\s*POSTGRES_DB=(.+)') { $pgDb = $Matches[1].Trim() }
}
$dbReady = $false
for ($i = 1; $i -le 24; $i++) {
    Write-Host "Running: docker compose ... exec -T db pg_isready -U $pgUser -d $pgDb" -ForegroundColor DarkGray
    & docker compose -f $composeFile --env-file $envFile exec -T db pg_isready -U $pgUser -d $pgDb
    if ($LASTEXITCODE -eq 0) { $dbReady = $true; break }
    Write-Host "  waiting db ... $i/24"
    Start-Sleep -Seconds 5
}
if (-not $dbReady) {
    Write-Host "FAIL: Postgres not ready" -ForegroundColor Red
    exit 1
}
Write-Host "OK: Postgres ready" -ForegroundColor Green

Write-Host ""
Write-Host ">> Step 5: alembic upgrade head" -ForegroundColor Blue
Write-Host "Running: docker compose ... exec -T web alembic upgrade head" -ForegroundColor DarkGray
& docker compose -f $composeFile --env-file $envFile exec -T web alembic upgrade head
Assert-DockerExit "alembic upgrade head"

Write-Host ""
Write-Host ">> Step 6: seed admin_king" -ForegroundColor Blue
Write-Host "Running: docker compose ... exec -T web python scripts/seed_admin_king.py" -ForegroundColor DarkGray
& docker compose -f $composeFile --env-file $envFile exec -T web python scripts/seed_admin_king.py
Assert-DockerExit "seed_admin_king"

Write-Host ""
Write-Host ">> Step 7: DB SELECT 1 in web" -ForegroundColor Blue
$dbCheck = "from sqlalchemy import text; from core.database import get_session_factory; f=get_session_factory(); s=f(); assert s.execute(text('SELECT 1')).scalar()==1; s.close(); print('OK')"
Write-Host "Running: docker compose ... exec -T web python -c ..." -ForegroundColor DarkGray
& docker compose -f $composeFile --env-file $envFile exec -T web python -c $dbCheck
Assert-DockerExit "DB SELECT 1 check"

Write-Host ""
Write-Host ">> Step 8: diagnose_auth (in web)" -ForegroundColor Blue
Write-Host "Running: docker compose ... exec -T -e THIRAMAI_DIAGNOSE_AUTH_URL=... web python scripts/diagnose_auth.py" -ForegroundColor DarkGray
& docker compose -f $composeFile --env-file $envFile exec -T -e "THIRAMAI_DIAGNOSE_AUTH_URL=http://127.0.0.1:8000" web python scripts/diagnose_auth.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: diagnose_auth exit $LASTEXITCODE - review output" -ForegroundColor Yellow
}

$webPort = "8000"
Get-Content ".env.production" | ForEach-Object {
    if ($_ -match '^\s*WEB_PORT=(.+)') { $webPort = $Matches[1].Trim() }
}
$baseUrl = "http://127.0.0.1:$webPort"
$pl = (& docker compose -f $composeFile --env-file $envFile port web 8000 2>$null | Select-Object -Last 1)
if ($pl -match '^(.+):(\d+)$') {
    $baseUrl = "http://$($Matches[1]):$($Matches[2])"
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "   RESET & INITIALIZATION COMPLETE" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Your system is now ready!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Login credentials:" -ForegroundColor Yellow
Write-Host "   Username: admin_king" -ForegroundColor White
Write-Host "   Password: thiramai_2026" -ForegroundColor White
Write-Host ""
Write-Host "   OR" -ForegroundColor White
Write-Host ""
Write-Host "   Email: admin@thiramai.local" -ForegroundColor White
Write-Host "   Password: thiramai_2026" -ForegroundColor White
Write-Host ""
Write-Host "Access UI:" -ForegroundColor Yellow
Write-Host "   $baseUrl/static/command_center/index.html#/login" -ForegroundColor White
Write-Host ""
Write-Host "API docs:  $baseUrl/docs" -ForegroundColor White
Write-Host ""
Write-Host 'User: admin_king (or admin@thiramai.local) Pass: thiramai_2026' -ForegroundColor Cyan
Write-Host ""
Write-Host "System ready. Use login above." -ForegroundColor Green
