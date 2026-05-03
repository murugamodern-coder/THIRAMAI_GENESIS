# Test Decision API — login, then POST /chat/decision

$ErrorActionPreference = "Stop"
$baseUrl = "http://localhost:8000"

Write-Host "Testing Decision API..." -ForegroundColor Cyan
Write-Host ""

# Step 1: Login
Write-Host "1. Logging in..." -ForegroundColor Yellow

try {
    $login = Invoke-RestMethod `
        -Uri "$baseUrl/auth/login" `
        -Method POST `
        -ContentType "application/x-www-form-urlencoded" `
        -Body "username=admin_king&password=thiramai_2026"

    Write-Host "   [OK] Login successful" -ForegroundColor Green
    $token = $login.access_token
    if ($token.Length -gt 50) {
        Write-Host "   Token: $($token.Substring(0, 50))..." -ForegroundColor Gray
    } else {
        Write-Host "   Token received ($($token.Length) chars)" -ForegroundColor Gray
    }
} catch {
    Write-Host "   [FAIL] Login failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Step 2: Decision endpoint
Write-Host ""
Write-Host "2. Testing decision endpoint..." -ForegroundColor Yellow

try {
    $decision = Invoke-RestMethod `
        -Uri "$baseUrl/chat/decision" `
        -Method POST `
        -Headers @{ Authorization = "Bearer $token" } `
        -ContentType "application/json" `
        -Body '{"message":"Should I invest in gold?"}'

    Write-Host "   [OK] Decision API responded" -ForegroundColor Green
    Write-Host ""
    Write-Host "Response:" -ForegroundColor Cyan
    $decision | ConvertTo-Json -Depth 8 | Write-Host

    $src = $decision.decision.data.decision_brain_source
    if ($src) {
        Write-Host ""
        Write-Host "Decision Source: $src" -ForegroundColor Cyan
        if ($src -eq "policy_engine") {
            Write-Host "   [OK] Using PolicyEngine" -ForegroundColor Green
        } elseif ($src -eq "safe_fallback") {
            Write-Host "   [WARN] Using safe fallback (verify AI keys and PolicyEngine)" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "   [FAIL] Decision API failed" -ForegroundColor Red
    Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Yellow

    if ($_.Exception.Message -match "internal error") {
        Write-Host ""
        Write-Host "With THIRAMAI_SAFE_ERRORS=1, the API hides the real error. Check:" -ForegroundColor Yellow
        Write-Host "  docker compose -f docker-compose.production.yml logs web --tail 80" -ForegroundColor Cyan
        Write-Host "Common causes: missing/invalid AI keys, or DB error (e.g. missing ai_decisions table / run migrations)." -ForegroundColor Yellow
        Write-Host "Keys: docs/setup/AI_KEYS.md" -ForegroundColor Cyan
    }

    exit 1
}

Write-Host ""
Write-Host "[OK] All tests passed!" -ForegroundColor Green
