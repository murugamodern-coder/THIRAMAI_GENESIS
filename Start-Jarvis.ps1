<#
.SYNOPSIS
  Start THIRAMAI Genesis (Executive Cockpit) — FastAPI + Uvicorn on all interfaces.

.DESCRIPTION
  - Activates ``.venv`` in the repo root (creates it if missing).
  - Sets ``PYTHONPATH`` to the project root.
  - Runs ``uvicorn main:app`` on ``0.0.0.0:8000`` (override with ``THIRAMAI_HOST`` / ``THIRAMAI_PORT``).
  - Prints LAN URLs (including a fixed hint for mobile: ``192.168.29.228`` when applicable).

  Frontend (Vite command center): ``cd web\command_center && npm install && npm run build``
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Activate = Join-Path $VenvDir "Scripts\Activate.ps1"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[Start-Jarvis] Creating Python virtual environment at .venv ..."
    python -m venv $VenvDir
}

if (Test-Path $Activate) {
    . $Activate
} else {
    Write-Warning "Activate.ps1 not found; using python from PATH."
}

$env:PYTHONPATH = $Root
$env:PYTHONUNBUFFERED = "1"

Write-Host "[Start-Jarvis] Installing / updating dependencies (requirements + core ASGI stack) ..."
python -m pip install --upgrade pip
python -m pip install -r (Join-Path $Root "requirements.txt")
python -m pip install "uvicorn[standard]>=0.32.0" "fastapi>=0.115.0" "psycopg2-binary>=2.9.9"

$ccWeb = Join-Path $Root "web\command_center"
if (Test-Path $ccWeb) {
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCmd) {
        Write-Host "[Start-Jarvis] npm install (Vite command center) ..."
        Push-Location $ccWeb
        try { npm install } finally { Pop-Location }
    } else {
        Write-Host "[Start-Jarvis] npm not in PATH — skipped web\command_center. Install Node.js LTS, then: cd web\command_center && npm install && npm run build" -ForegroundColor DarkYellow
    }
}

Write-Host "[Start-Jarvis] Applying database migrations ..."
python -m alembic upgrade head

Write-Host ""
Write-Host "=== Executive Cockpit — bind addresses ===" -ForegroundColor Cyan
Write-Host ("  Local:    http://127.0.0.1:8000")
Write-Host ("  All NICs: http://0.0.0.0:8000   (use your PC LAN IP below on phone/tablet)")

$PreferredLan = "192.168.29.228"
Write-Host ("  Mobile (your saved LAN): http://{0}:8000" -f $PreferredLan) -ForegroundColor Green

try {
    $addrs = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Select-Object -ExpandProperty IPAddress -Unique
    foreach ($a in $addrs) {
        if ($a -and $a -ne $PreferredLan) {
            Write-Host ("  Detected:  http://{0}:8000" -f $a)
        }
    }
} catch {
    Write-Host "  (Could not enumerate additional IPv4 addresses.)"
}

Write-Host ""
Write-Host "[Start-Jarvis] Starting Uvicorn (Ctrl+C to stop) ..." -ForegroundColor Yellow
python -m uvicorn main:app --host 0.0.0.0 --port 8000
