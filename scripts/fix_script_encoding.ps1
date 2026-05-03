# Normalize line endings and UTF-8 (no BOM). Remove zero-width / BOM quirks from OneDrive sync.
# Optional: -StripNonAscii strips all non-ASCII (breaks emoji/box-drawing in scripts; use only if needed).

param(
    [Parameter(Mandatory = $false)]
    [string]$ScriptPath = $(Join-Path $PSScriptRoot "reset_and_init.ps1"),

    [switch]$StripNonAscii
)

$ErrorActionPreference = "Stop"

Write-Host "Fixing script encoding..." -ForegroundColor Cyan

if (-not [System.IO.Path]::IsPathRooted($ScriptPath)) {
    $ScriptPath = Join-Path (Get-Location) $ScriptPath
}
if (-not (Test-Path -LiteralPath $ScriptPath)) {
    Write-Host "FAIL: Script not found: $ScriptPath" -ForegroundColor Red
    exit 1
}

$content = [System.IO.File]::ReadAllText($ScriptPath)

# Zero-width / BOM-like characters that break parsers
$content = $content -replace "\uFEFF", ""
$content = $content -replace "[\u200B-\u200D\u2060]", ""

if ($StripNonAscii) {
    $content = $content -replace "[^\x00-\x7F]", ""
}

$content = $content -replace "`r`n", "`n"
$content = $content -replace "`r", "`n"

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($ScriptPath, $content, $utf8NoBom)

Write-Host "OK: Encoding normalized (UTF-8, no BOM)." -ForegroundColor Green
Write-Host ""
Write-Host "Validate:" -ForegroundColor Cyan
Write-Host "  .\scripts\validate_powershell.ps1 -ScriptPath `"$ScriptPath`"" -ForegroundColor White
