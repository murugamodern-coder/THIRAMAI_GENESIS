# PowerShell script syntax validator (AST parse; catches unterminated strings / braces).

param(
    [Parameter(Mandatory = $false)]
    [string]$ScriptPath = $(Join-Path $PSScriptRoot "reset_and_init.ps1")
)

$ErrorActionPreference = "Stop"

Write-Host "Validating PowerShell script syntax..." -ForegroundColor Cyan

if (-not [System.IO.Path]::IsPathRooted($ScriptPath)) {
    $ScriptPath = Join-Path (Get-Location) $ScriptPath
}
$resolved = Resolve-Path -LiteralPath $ScriptPath -ErrorAction SilentlyContinue
if (-not $resolved) {
    Write-Host "FAIL: Script not found: $ScriptPath" -ForegroundColor Red
    exit 1
}

$fullPath = $resolved.Path
Write-Host "Script: $fullPath" -ForegroundColor White
Write-Host ""

$tokens = $null
$errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($fullPath, [ref]$tokens, [ref]$errors)

if ($null -eq $errors -or $errors.Count -eq 0) {
    Write-Host "OK: No syntax errors found." -ForegroundColor Green
    Write-Host ""
    Write-Host "Run from repo root:" -ForegroundColor Cyan
    Write-Host "  .\scripts\reset_and_init.ps1" -ForegroundColor White
    exit 0
}

Write-Host "FAIL: Syntax errors:" -ForegroundColor Red
Write-Host ""
foreach ($err in $errors) {
    Write-Host ("Line {0}: {1}" -f $err.Extent.StartLineNumber, $err.Message) -ForegroundColor Yellow
    if ($err.Extent.Text) {
        Write-Host ("  {0}" -f $err.Extent.Text) -ForegroundColor White
    }
    Write-Host ""
}
exit 1
