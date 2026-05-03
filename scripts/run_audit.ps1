# THIRAMAI GENESIS - CTO-Level System Audit
# Runs static + live checks against the local production stack and prints a pass/fail summary.
# Read-only: this script does not modify code or config.

$ErrorActionPreference = "Continue"
$composeFile = "docker-compose.production.yml"
$envFile = ".env.production"
$composeArgs = @("-f", $composeFile, "--env-file", $envFile)
$results = @()

function Add-Check {
    param([string]$Section, [string]$Name, [bool]$Pass, [string]$Detail)
    $script:results += [pscustomobject]@{
        Section = $Section
        Name    = $Name
        Pass    = $Pass
        Detail  = $Detail
    }
    $color = if ($Pass) { "Green" } else { "Red" }
    $mark = if ($Pass) { "[OK]" } else { "[FAIL]" }
    Write-Host "   $mark $Name" -ForegroundColor $color
    if ($Detail) { Write-Host "        $Detail" -ForegroundColor DarkGray }
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  THIRAMAI GENESIS - CTO-LEVEL AUDIT" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (UTC$([System.TimeZoneInfo]::Local.BaseUtcOffset.Hours))" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ----------------------------------------------------------------------------
# 1) Repo / configuration sanity
# ----------------------------------------------------------------------------
Write-Host "1. Configuration & repo" -ForegroundColor Yellow

$envExists = Test-Path $envFile
Add-Check "config" ".env.production present" $envExists ""

$composeExists = Test-Path $composeFile
Add-Check "config" "docker-compose.production.yml present" $composeExists ""

$dockerExists = Test-Path "Dockerfile"
Add-Check "config" "Dockerfile present" $dockerExists ""

$migHead = ""
if (Test-Path "core/migration_head.py") {
    $line = Select-String -Path "core/migration_head.py" -Pattern 'EXPECTED_ALEMBIC_REVISION\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($line) { $migHead = $line.Matches[0].Groups[1].Value }
}
Add-Check "config" "Alembic head pinned in core/migration_head.py" ([bool]$migHead) "head=$migHead"

if ($envExists) {
    $envContent = Get-Content $envFile -Raw
    $skip = if ($envContent -match 'THIRAMAI_SKIP_ALEMBIC_CHECK=(\d+)') { $matches[1] } else { "?" }
    $ignore = if ($envContent -match 'THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH=(\d+)') { $matches[1] } else { "?" }
    Add-Check "config" "Alembic check enabled (SKIP=0)" ($skip -eq "0") "SKIP_ALEMBIC_CHECK=$skip"
    Add-Check "config" "Alembic mismatch ignore set (1)" ($ignore -eq "1") "IGNORE_ALEMBIC_MISMATCH=$ignore"
}

# ----------------------------------------------------------------------------
# 2) Live containers
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "2. Containers" -ForegroundColor Yellow

try {
    $psJson = & docker compose @composeArgs ps --format json 2>$null
    $rows = @()
    if ($psJson) {
        try { $rows = $psJson | ConvertFrom-Json } catch { $rows = @() }
        if ($rows -isnot [System.Array]) { $rows = @($rows) }
    }
    $expected = @("db", "redis", "web", "worker-jobs", "worker-alerts")
    foreach ($svc in $expected) {
        $row = $rows | Where-Object { $_.Service -eq $svc -or $_.Name -match "$svc" } | Select-Object -First 1
        $health = $row.Health
        $state = $row.State
        $ok = ($state -eq "running") -and ($health -eq "healthy" -or $health -eq "" -or $null -eq $health)
        Add-Check "containers" "$svc state/health" $ok "state=$state health=$health"
    }
} catch {
    Add-Check "containers" "docker compose ps reachable" $false "$_"
}

# ----------------------------------------------------------------------------
# 3) Health endpoints
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "3. Health endpoints" -ForegroundColor Yellow

function Probe-Json($url) {
    try { return Invoke-RestMethod -Uri $url -ErrorAction Stop }
    catch { return $null }
}

$live = Probe-Json "http://localhost:8000/health/live"
Add-Check "health" "/health/live alive" ([bool]($live -and $live.status -eq "alive")) ""

$ready = Probe-Json "http://localhost:8000/health/ready"
$readyOk = ($ready -and ($ready.status -eq "ready" -or $ready.status -eq "degraded"))
Add-Check "health" "/health/ready 200 ready/degraded" $readyOk "status=$($ready.status)"

if ($ready) {
    $ai = $ready.checks.ai
    $aiKeys = $ai -and $ai.groq_configured -and $ai.tavily_configured
    Add-Check "health" "AI keys configured (GROQ + TAVILY)" $aiKeys "groq=$($ai.groq_configured) tavily=$($ai.tavily_configured)"

    $alembic = $ready.checks.alembic
    $alembicOk = $alembic -and $alembic.ok -and $alembic.detail -notlike "skipped*"
    Add-Check "health" "Alembic check active (not skipped)" $alembicOk "detail=$($alembic.detail)"

    $pe = $ready.checks.policy_engine
    Add-Check "health" "PolicyEngine healthy/degraded" ([bool]($pe -and ($pe.status -eq "healthy" -or $pe.status -eq "degraded"))) "status=$($pe.status)"
}

# ----------------------------------------------------------------------------
# 4) Decision API
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "4. Decision API end-to-end" -ForegroundColor Yellow

$token = $null
try {
    $login = Invoke-RestMethod -Uri "http://localhost:8000/auth/login" -Method POST `
        -ContentType "application/x-www-form-urlencoded" `
        -Body "username=admin_king&password=thiramai_2026" -ErrorAction Stop
    $token = $login.access_token
    Add-Check "decision" "Login -> JWT" ([bool]$token) "token len=$($token.Length)"
} catch {
    Add-Check "decision" "Login -> JWT" $false "$_"
}

if ($token) {
    try {
        $dec = Invoke-RestMethod -Uri "http://localhost:8000/chat/decision" -Method POST `
            -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" `
            -Body '{"message":"Audit probe: should I rebalance?"}' -ErrorAction Stop
        Add-Check "decision" "/chat/decision returns 200" ([bool]$dec) ""
        $src = $dec.decision.data.decision_brain_source
        Add-Check "decision" "decision_brain_source set" ([bool]$src) "source=$src"
        Add-Check "decision" "Persisted decision_id present" ([bool]$dec.decision_id) "decision_id=$($dec.decision_id)"
    } catch {
        Add-Check "decision" "/chat/decision returns 200" $false "$_"
    }
}

# ----------------------------------------------------------------------------
# 5) Database & RLS
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "5. Database & RLS" -ForegroundColor Yellow

try {
    $dbRev = (& docker compose @composeArgs exec -T db psql -U thiramai -d thiramai -t -c "SELECT version_num FROM alembic_version" 2>$null | ForEach-Object { $_.Trim() }) -join ""
    Add-Check "db" "alembic_version readable" ([bool]$dbRev) "rev=$dbRev"
    Add-Check "db" "DB at expected revision" ($dbRev -eq $migHead) "db=$dbRev expected=$migHead"
} catch {
    Add-Check "db" "alembic_version readable" $false "$_"
}

try {
    $rs = (& docker compose @composeArgs exec -T db psql -U thiramai -d thiramai -t -c "SHOW row_security" 2>$null | ForEach-Object { $_.Trim() }) -join ""
    Add-Check "db" "row_security default = on" ($rs -eq "on") "row_security=$rs"
} catch {
    Add-Check "db" "row_security check" $false "$_"
}

# Look for the known P0: 'force' usage in core/database.py
$rlsForce = $false
if (Test-Path "core/database.py") {
    $rlsForce = (Select-String -Path "core/database.py" -Pattern "row_security\s*=\s*force" -Quiet)
}
Add-Check "db" "core/database.py uses valid row_security value (not 'force')" (-not $rlsForce) "If true, this is a P0 - 'force' is rejected by PostgreSQL"

# Connection role used by the running web container
try {
    $dbUrl = (& docker exec thiramai_genesis-web-1 printenv DATABASE_URL 2>$null) -join ""
    $usingThiramaiRole = $dbUrl -match "://thiramai:"
    Add-Check "db" "Web NOT connecting as the bypass role 'thiramai'" (-not $usingThiramaiRole) "DATABASE_URL role=$($dbUrl -replace ':[^:@]*@', ':***@')"
} catch {
    Add-Check "db" "DATABASE_URL inspection" $false "$_"
}

# ----------------------------------------------------------------------------
# 6) Auth hardening signals
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "6. Auth hardening (static checks)" -ForegroundColor Yellow

$tvEnforced = $false
if (Test-Path "core/auth.py") {
    $authText = Get-Content "core/auth.py" -Raw
    if ($authText -match "claims\.get\(['""]tv['""]\)" -or $authText -match "_token_version\(" ) {
        # presence isn't enough — needs to be in decode path; rough heuristic
        $tvEnforced = $authText -match 'decode_access_token[\s\S]+tv'
    }
}
Add-Check "auth" "JWT 'tv' enforced on decode" $tvEnforced "Heuristic: looks for 'tv' inside decode_access_token"

$lockoutPresent = $false
$lockoutPath = "api/routes/auth.py"
if (Test-Path $lockoutPath) {
    $lockoutPresent = (Select-String -Path $lockoutPath -Pattern "lockout|too many|attempts" -Quiet)
}
Add-Check "auth" "Login lockout / progressive backoff present" $lockoutPresent ""

$fernetSafe = $false
if (Test-Path "services/integration_crypto.py") {
    $fernetSafe = -not (Select-String -Path "services/integration_crypto.py" -Pattern "dev-unsafe-thiramai-integration" -Quiet)
}
Add-Check "auth" "Integration Fernet has no dev-unsafe fallback" $fernetSafe "If false: refuse startup when key is empty in prod"

# ----------------------------------------------------------------------------
# 7) Tests / coverage
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "7. Tests & coverage" -ForegroundColor Yellow

$testCount = 0
if (Test-Path "tests") {
    $testCount = (Get-ChildItem -Path "tests" -Filter "test_*.py" -Recurse | Measure-Object).Count
}
Add-Check "tests" "Backend test files >= 50" ($testCount -ge 50) "count=$testCount"

$integrationCount = 0
if (Test-Path "tests/integration") {
    $integrationCount = (Get-ChildItem -Path "tests/integration" -Filter "test_*.py" | Measure-Object).Count
}
Add-Check "tests" "Has at least one integration test" ($integrationCount -ge 1) "count=$integrationCount"

$covPath = "coverage.json"
$covPresent = Test-Path $covPath
Add-Check "tests" "coverage.json present" $covPresent "Run pytest --cov to generate"

# ----------------------------------------------------------------------------
# 8) Documentation
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "8. Documentation" -ForegroundColor Yellow

$mustHave = @(
    "README.md",
    "docs/deployment/QUICK_START.md",
    "docs/deployment/HEALTH_CHECKS.md",
    "docs/deployment/PRODUCTION_MODE.md",
    "docs/deployment/TROUBLESHOOTING.md",
    "docs/setup/AI_KEYS.md",
    "docs/runbooks/README.md",
    "docs/operations/secrets-management.md"
)
foreach ($p in $mustHave) {
    Add-Check "docs" "$p exists" (Test-Path $p) ""
}

# ----------------------------------------------------------------------------
# 9) CI workflows
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "9. CI / workflows" -ForegroundColor Yellow

$ciFiles = @("ci.yml","test-coverage.yml","rotate-secrets.yml","dependency-audit.yml","deploy.yml")
foreach ($f in $ciFiles) {
    Add-Check "ci" ".github/workflows/$f exists" (Test-Path ".github/workflows/$f") ""
}

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  AUDIT SUMMARY" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

$total = $results.Count
$passed = ($results | Where-Object { $_.Pass }).Count
$failed = $total - $passed

Write-Host ""
Write-Host "Checks run: $total   Passed: $passed   Failed: $failed" -ForegroundColor Cyan

if ($failed -gt 0) {
    Write-Host ""
    Write-Host "Failures:" -ForegroundColor Red
    $results | Where-Object { -not $_.Pass } | ForEach-Object {
        Write-Host "  - [$($_.Section)] $($_.Name)  $($_.Detail)" -ForegroundColor Yellow
    }
}

# Save JSON report
$report = [pscustomobject]@{
    timestamp     = (Get-Date).ToString("o")
    total         = $total
    passed        = $passed
    failed        = $failed
    alembic_head  = $migHead
    results       = $results
}
$null = New-Item -ItemType Directory -Force -Path "reports" 2>$null
$reportPath = "reports/audit-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss")
$report | ConvertTo-Json -Depth 5 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ""
Write-Host "Report written: $reportPath" -ForegroundColor Cyan
Write-Host "Full CTO-level report: docs/audit/CTO_AUDIT_2026_05.md" -ForegroundColor Cyan

if ($failed -gt 0) { exit 1 } else { exit 0 }
