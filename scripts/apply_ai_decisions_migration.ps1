# Apply ai_decisions migration (0078) and smoke-test decision API

$ErrorActionPreference = "Continue"
$composeFile = "docker-compose.production.yml"
$envFile = ".env.production"
$composeArgs = @("-f", $composeFile, "--env-file", $envFile)

Write-Host "Applying ai_decisions table migration..." -ForegroundColor Cyan
Write-Host ""

Write-Host "1. Checking current database revision..." -ForegroundColor Yellow
try {
    $currentRev = & docker compose @composeArgs exec -T db `
        psql -U thiramai -d thiramai -t -c "SELECT version_num FROM alembic_version" 2>$null
    $currentRev = ($currentRev | ForEach-Object { $_.Trim() }) -join ""
    Write-Host "   Current: $currentRev" -ForegroundColor Gray
} catch {
    Write-Host "   (Could not read alembic_version)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "2. Running alembic upgrade head..." -ForegroundColor Yellow
& docker compose @composeArgs exec -T web alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [FAIL] alembic upgrade failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

$afterRev = ""
try {
    $afterRev = (& docker compose @composeArgs exec -T db psql -U thiramai -d thiramai -t -c "SELECT version_num FROM alembic_version" 2>$null | ForEach-Object { $_.Trim() }) -join ""
} catch { }
if ($afterRev -and $afterRev -notmatch "0078") {
    Write-Host ""
    Write-Host "[WARN] DB revision is still '$afterRev'. The web image may not include 0078_add_ai_decisions_table.py." -ForegroundColor Yellow
    Write-Host "Rebuild web: docker compose @composeArgs build web && docker compose @composeArgs up -d web" -ForegroundColor Cyan
    Write-Host "Or run: alembic upgrade head from this repo on the host with DATABASE_URL set." -ForegroundColor Cyan
}

Write-Host ""
Write-Host "3. Verifying ai_decisions table..." -ForegroundColor Yellow
$tableCheck = & docker compose @composeArgs exec -T db psql -U thiramai -d thiramai -c "\d ai_decisions" 2>&1
if ("$tableCheck" -match "Column") {
    Write-Host "   [OK] ai_decisions exists" -ForegroundColor Green
    Write-Host ""
    Write-Host "Table structure:" -ForegroundColor Cyan
    Write-Host $tableCheck
} else {
    Write-Host "   [WARN] Could not describe ai_decisions" -ForegroundColor Yellow
    Write-Host $tableCheck
}

Write-Host ""
Write-Host "4. Testing decision API..." -ForegroundColor Yellow
Write-Host ""
& "$PSScriptRoot\test_decision_api.ps1"
