# THIRAMAI — bind 0.0.0.0:8000 so other devices on the LAN can reach /dashboard/live.
# Run from repo root context:
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $py) {
    & $py -m uvicorn main:app --host 0.0.0.0 --port 8000
} else {
    python -m uvicorn main:app --host 0.0.0.0 --port 8000
}
