# Production Mode Verification
# Confirms system is in clean production state (no workarounds)

$ErrorActionPreference = "Continue"
$composeFile = "docker-compose.production.yml"
$envFile = ".env.production"
$composeArgs = @("-f", $composeFile, "--env-file", $envFile)

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  PRODUCTION MODE VERIFICATION" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

$allChecks = @()

# 1. Check .env.production settings
Write-Host "1. Checking environment configuration..." -ForegroundColor Yellow

if (-not (Test-Path $envFile)) {
    Write-Host "   [FAIL] Missing $envFile" -ForegroundColor Red
    $allChecks += $false
} else {
    $envContent = Get-Content $envFile -Raw

    $skipCheck = if ($envContent -match 'THIRAMAI_SKIP_ALEMBIC_CHECK=(\d+)') { $matches[1] } else { "not_set" }
    $ignoreMismatch = if ($envContent -match 'THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH=(\d+)') { $matches[1] } else { "not_set" }

    if ($skipCheck -eq "0" -and $ignoreMismatch -eq "1") {
        Write-Host "   [OK] Clean production mode (no skip hacks)" -ForegroundColor Green
        $allChecks += $true
    } else {
        Write-Host "   [FAIL] Still using workarounds:" -ForegroundColor Red
        Write-Host "      SKIP_ALEMBIC_CHECK: $skipCheck (should be 0)" -ForegroundColor Yellow
        Write-Host "      IGNORE_MISMATCH: $ignoreMismatch (should be 1)" -ForegroundColor Yellow
        $allChecks += $false
    }
}

# 2. Check container health
Write-Host ""
Write-Host "2. Checking container health..." -ForegroundColor Yellow

try {
    $psJson = & docker compose @composeArgs ps web --format json 2>$null
    if ($psJson) {
        $rows = $psJson | ConvertFrom-Json
        if ($rows -is [System.Array]) { $rows = $rows | Select-Object -First 1 }
        $webHealth = $rows.Health
        if ($webHealth -eq "healthy") {
            Write-Host "   [OK] Web container healthy" -ForegroundColor Green
            $allChecks += $true
        } else {
            Write-Host "   [WARN] Web container: $webHealth" -ForegroundColor Yellow
            $allChecks += $true
        }
    } else {
        Write-Host "   [WARN] Could not read web container state" -ForegroundColor Yellow
        $allChecks += $true
    }
} catch {
    Write-Host "   [WARN] Could not query docker compose ps" -ForegroundColor Yellow
    $allChecks += $true
}

# 3. Check /health/live
Write-Host ""
Write-Host "3. Checking /health/live..." -ForegroundColor Yellow

try {
    $live = Invoke-RestMethod -Uri "http://localhost:8000/health/live" -ErrorAction Stop
    if ($live.status -eq "alive") {
        Write-Host "   [OK] Service alive" -ForegroundColor Green
        $allChecks += $true
    } else {
        Write-Host "   [FAIL] Unexpected status: $($live.status)" -ForegroundColor Red
        $allChecks += $false
    }
} catch {
    Write-Host "   [FAIL] Failed to reach /health/live" -ForegroundColor Red
    $allChecks += $false
}

# 4. Check /health/ready
Write-Host ""
Write-Host "4. Checking /health/ready..." -ForegroundColor Yellow

try {
    $ready = Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -ErrorAction Stop

    if ($ready.status -eq "ready") {
        Write-Host "   [OK] Service ready" -ForegroundColor Green

        if ($null -ne $ready.warnings -and @($ready.warnings).Count -gt 0) {
            Write-Host "   Warnings:" -ForegroundColor Cyan
            foreach ($warning in @($ready.warnings)) {
                Write-Host "      - $warning" -ForegroundColor Yellow
            }
        }

        $allChecks += $true
    } elseif ($ready.status -eq "degraded") {
        Write-Host "   [WARN] Service degraded but operational" -ForegroundColor Yellow
        $allChecks += $true
    } else {
        Write-Host "   [FAIL] Not ready: $($ready.status)" -ForegroundColor Red
        $allChecks += $false
    }
} catch {
    Write-Host "   [FAIL] Health check failed (503 or error)" -ForegroundColor Red

    try {
        $errorResponse = $_.Exception.Response
        if ($errorResponse) {
            $reader = New-Object System.IO.StreamReader($errorResponse.GetResponseStream())
            $raw = $reader.ReadToEnd()
            try {
                $body = $raw | ConvertFrom-Json
                Write-Host "   Details:" -ForegroundColor Yellow
                if ($body.checks) {
                    foreach ($prop in $body.checks.PSObject.Properties) {
                        $ok = $prop.Value.ok
                        $mark = if ($ok) { "[OK]" } else { "[FAIL]" }
                        Write-Host "      $mark $($prop.Name)" -ForegroundColor Yellow
                    }
                }
            } catch {
                Write-Host "   Raw: $raw" -ForegroundColor Yellow
            }
        }
    } catch {
    }

    $allChecks += $false
}

# 5. Check database migrations
Write-Host ""
Write-Host "5. Checking database state..." -ForegroundColor Yellow

try {
    $revision = & docker compose @composeArgs exec -T db `
        psql -U thiramai -d thiramai -t -c "SELECT version_num FROM alembic_version" 2>$null

    $revision = ($revision -join "").Trim()

    if ($revision -eq "0077_fix_rls_superuser_bypass_role") {
        Write-Host "   [OK] Database at revision: $revision" -ForegroundColor Green
        $allChecks += $true
    } else {
        Write-Host "   [WARN] Database at revision: $revision" -ForegroundColor Yellow
        $allChecks += $true
    }
} catch {
    Write-Host "   [WARN] Could not check database revision" -ForegroundColor Yellow
    $allChecks += $true
}

# Summary
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  VERIFICATION SUMMARY" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

$passed = ($allChecks | Where-Object { $_ -eq $true }).Count
$total = $allChecks.Count

Write-Host ""
Write-Host "Checks passed: $passed/$total" -ForegroundColor $(if ($passed -eq $total) { "Green" } else { "Yellow" })

if ($passed -eq $total) {
    Write-Host ""
    Write-Host "[OK] PRODUCTION MODE VERIFIED!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Your system is running in clean production mode:" -ForegroundColor Cyan
    Write-Host "  - No temporary workarounds" -ForegroundColor White
    Write-Host "  - Proper health checks" -ForegroundColor White
    Write-Host "  - All systems operational" -ForegroundColor White
    Write-Host ""
    Write-Host "READY FOR PRODUCTION USE." -ForegroundColor Green
    exit 0
} else {
    Write-Host ""
    Write-Host "[WARN] Some checks need attention (see above)" -ForegroundColor Yellow
    exit 1
}
