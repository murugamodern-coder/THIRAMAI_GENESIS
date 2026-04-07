# Local CD hook after kernel sandbox approval (Windows / THIRAMAI_CI_CD_MODE=local_script).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$payload = $env:THIRAMAI_KERNEL_PAYLOAD_JSON
if ([string]::IsNullOrEmpty($payload)) { $payload = "{}" }
$len = [Math]::Min(200, $payload.Length)
Write-Host "[ci_cd_after_kernel] payload (truncated): $($payload.Substring(0, $len))..."

$compose = if ($env:THIRAMAI_DEPLOY_COMPOSE_FILE) { $env:THIRAMAI_DEPLOY_COMPOSE_FILE } else { "docker-compose.production.yml" }
$envf = if ($env:THIRAMAI_DEPLOY_ENV_FILE) { $env:THIRAMAI_DEPLOY_ENV_FILE } else { ".env.production" }

if ((Test-Path $envf) -and (Test-Path $compose)) {
    docker compose -f $compose --env-file $envf up -d --build
    Write-Host "[ci_cd_after_kernel] docker compose up completed."
} else {
    Write-Host "[ci_cd_after_kernel] skip compose: missing $envf or $compose"
}
