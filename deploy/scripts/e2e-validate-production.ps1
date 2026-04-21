# THIRAMAI production E2E smoke checks (PowerShell)
# Usage:
#   $env:BASE_URL = "https://app.thiramai.co.in"
#   .\e2e-validate-production.ps1
# Optional:
#   $env:JWT_ACCESS_TOKEN = "<access_token>"

$ErrorActionPreference = "Stop"
$BaseUrl = if ($env:BASE_URL) { $env:BASE_URL } else { "https://app.thiramai.co.in" }

function Test-Health {
    param([string]$Path)
    $u = "$BaseUrl$Path"
    $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 20
    if ($r.StatusCode -ne 200) { throw "$Path returned $($r.StatusCode)" }
    $j = $r.Content | ConvertFrom-Json
    if (-not $j.status) { throw "$Path JSON missing status" }
}

Write-Host "=== Step 2: Health ==="
Test-Health "/health/live"
Write-Host "OK: /health/live"
Test-Health "/health/ready"
Write-Host "OK: /health/ready"

Write-Host "=== Step 3: Frontend ==="
$root = Invoke-WebRequest -Uri $BaseUrl -UseBasicParsing -TimeoutSec 25 -MaximumRedirection 5
if ($root.StatusCode -ne 200) { throw "GET / returned $($root.StatusCode)" }
Write-Host "OK: GET / -> $($root.StatusCode)"

Write-Host "=== OpenAPI: POST /ai/goal ? ==="
$oa = Invoke-RestMethod -Uri "$BaseUrl/openapi.json" -TimeoutSec 60
$hasGoal = $null -ne $oa.paths.'/ai/goal'
if (-not $hasGoal) {
    Write-Warning "POST /ai/goal not in OpenAPI - redeploy API image from current Genesis repo."
} else {
    Write-Host "OK: OpenAPI contains /ai/goal"
}

if ($env:JWT_ACCESS_TOKEN -and $hasGoal) {
    Write-Host "=== Step 4: POST /ai/goal ==="
    $body = '{"goal":"Test system health check - e2e validate"}'
    $hdr = @{ Authorization = "Bearer $($env:JWT_ACCESS_TOKEN)"; "Content-Type" = "application/json" }
    try {
        $g = Invoke-WebRequest -Uri "$BaseUrl/ai/goal" -Method POST -Headers $hdr -Body $body -UseBasicParsing -TimeoutSec 60
        Write-Host "POST /ai/goal -> $($g.StatusCode)"
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -ne 200 -and $code -ne 409) { throw $_ }
        Write-Host "POST /ai/goal -> $code"
    }
} elseif (-not $env:JWT_ACCESS_TOKEN) {
    Write-Host "JWT_ACCESS_TOKEN not set - skipping POST /ai/goal"
} else {
    Write-Host "Skipping POST /ai/goal (route not in OpenAPI)."
}

Write-Host "=== Done ==="
