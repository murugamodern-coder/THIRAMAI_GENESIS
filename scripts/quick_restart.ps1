# Quick restart without rebuild
# Reloads .env.production changes

Write-Host "Quick Restart - Reloading Environment" -ForegroundColor Cyan
Write-Host ""

$composeCmd = "docker compose -f docker-compose.production.yml --env-file .env.production"

# Stop services
Write-Host "Stopping services..." -ForegroundColor Yellow
Invoke-Expression "$composeCmd down"

# Start services
Write-Host ""
Write-Host "Starting services with new environment..." -ForegroundColor Yellow
Invoke-Expression "$composeCmd up -d"

# Wait for health
Write-Host ""
Write-Host "Waiting for services to be healthy (30 seconds)..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

# Check health
Write-Host ""
Write-Host "Checking health..." -ForegroundColor Cyan

try {
    $health = Invoke-RestMethod -Uri "http://localhost:8000/health/live"
    Write-Host "✅ /health/live: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "❌ /health/live failed" -ForegroundColor Red
}

try {
    $ready = Invoke-RestMethod -Uri "http://localhost:8000/health/ready"
    Write-Host "✅ /health/ready: $($ready.status)" -ForegroundColor Green
} catch {
    Write-Host "⚠️  /health/ready returned non-200, checking details..." -ForegroundColor Yellow

    # Get the error response
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health/ready" -ErrorAction SilentlyContinue
    } catch {
        $response = $_.Exception.Response
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        $body = $reader.ReadToEnd()

        Write-Host "Response:" -ForegroundColor Yellow
        Write-Host $body
    }
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Cyan
