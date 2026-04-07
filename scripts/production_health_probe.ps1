# THIRAMAI — production API liveness (Windows / optional local check against a remote URL).
#
# Usage:
#   $env:THIRAMAI_BASE_URL = "https://api.yourdomain.com"
#   .\scripts\production_health_probe.ps1

$ErrorActionPreference = "Stop"
$base = if ($env:THIRAMAI_BASE_URL) { $env:THIRAMAI_BASE_URL.TrimEnd("/") } else { "http://127.0.0.1:8000" }

Write-Host "=== THIRAMAI production health probe ==="
Write-Host "API: $base"

try {
    $headers = @{ Accept = "application/json" }
    Invoke-RestMethod -Uri "$base/" -Headers $headers -Method Get -TimeoutSec 20 | Out-Null
    Write-Host "[OK]   API GET / (JSON)"
    Write-Host "=== Result: OK ==="
    exit 0
}
catch {
    Write-Host "[FAIL] API GET / : $_"
    Write-Host "=== Result: UNHEALTHY ==="
    exit 1
}
