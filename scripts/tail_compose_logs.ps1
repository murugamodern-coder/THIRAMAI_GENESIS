# Follow Docker Compose logs for THIRAMAI (web + db).
# Usage (from repo root):
#   .\scripts\tail_compose_logs.ps1
# Optional:
#   $env:COMPOSE_FILE = "docker-compose.yml"; $env:ENV_FILE = ".env"; .\scripts\tail_compose_logs.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$composeFile = if ($env:COMPOSE_FILE) { $env:COMPOSE_FILE } else { "docker-compose.prod-slim.yml" }
$envFile = if ($env:ENV_FILE) { $env:ENV_FILE } else { ".env.production" }

if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Error "Env file not found: $envFile (copy .env.production.example to .env.production)"
}

docker compose -f $composeFile --env-file $envFile logs -f web db
