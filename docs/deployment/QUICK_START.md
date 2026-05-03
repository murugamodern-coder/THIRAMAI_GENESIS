# Thiramai Genesis — Quick start (production)

## Prerequisites

- Docker Engine and Docker Compose v2
- `.env.production` filled out (start from [.env.production.example](../../.env.production.example))
- Admin user present (e.g. `admin_king`) if you plan to exercise auth probes

## Quick environment reload

If you change `.env.production` settings:

**PowerShell:**

```powershell
.\scripts\quick_restart.ps1
```

**Bash:**

```bash
./scripts/quick_restart.sh
```

This reloads environment variables without rebuilding containers.

Compose passes listed `environment:` keys into the `web` service only — values in `.env.production` must appear in `docker-compose.production.yml` (for example `THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH`, `THIRAMAI_SKIP_ALEMBIC_CHECK`) or they never reach the API process.

`THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH` requires the current `api/routes/health.py` in the running image. Older images only honor `THIRAMAI_SKIP_ALEMBIC_CHECK=1` for readiness (set both in `.env.production` until you rebuild `web`, then turn skip off if you want Alembic warnings in JSON).

**When to use:**

- Changed health check settings
- Updated API keys
- Modified feature flags

**When NOT to use (need full rebuild):**

- Changed Python code
- Modified requirements.txt
- Updated Dockerfile

## Go live (about five minutes)

### Option A — Automated script

```bash
chmod +x scripts/go_live.sh   # once, on Unix
./scripts/go_live.sh
```

The script:

1. Runs `scripts/pre_deployment_check.py`
2. Builds and starts `docker-compose.production.yml` with `--env-file .env.production`
3. Waits, probes `/health/ready`, checks PolicyEngine status (`healthy` or `degraded` allowed)
4. Runs `scripts/verify_deployment.py --skip-tls-verify` against your base URL

**Base URL:** by default the script uses `http://127.0.0.1:$WEB_PORT` where `WEB_PORT` is read from `.env.production` if set, otherwise `8000` (see `docker-compose.production.yml`). Override with:

- `THIRAMAI_GO_LIVE_BASE_URL=http://127.0.0.1:18080` or
- `THIRAMAI_GO_LIVE_PORT=18080`

**Non-interactive:** `GO_LIVE_CONFIRM=yes ./scripts/go_live.sh`

### Option B — Manual

```bash
python scripts/pre_deployment_check.py

docker compose -f docker-compose.production.yml --env-file .env.production up -d --build

sleep 30

python scripts/verify_deployment.py --url http://127.0.0.1:8000 --skip-tls-verify
```

Adjust host/port to match `WEB_PORT` bindings in compose.

## Verify live status

### Health (readiness)

```bash
curl -sS http://127.0.0.1:8000/health/ready | jq
```

**Expected:** top-level `"status": "ready"` and `checks.policy_engine.status` one of `healthy` or `degraded` (degraded may indicate circuit-breaker / safe-fallback path — inspect JSON and logs).

### Decision API

```bash
TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/auth/login \
  -d "username=admin_king" -d "password=thiramai_2026" \
  | jq -r '.access_token')

curl -sS -X POST http://127.0.0.1:8000/chat/decision \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Should I invest in gold now?"}' \
  | jq '.decision.data.decision_brain_source'
```

Typical production value: `"policy_engine"` (or `"safe_fallback"` when the circuit breaker has tripped but readiness still reports `degraded`).

### AI quality (authenticated)

```bash
curl -sS http://127.0.0.1:8000/monitoring/ai-quality \
  -H "Authorization: Bearer $TOKEN" | jq
```

### Logs

```bash
docker compose -f docker-compose.production.yml logs -f web
```

Look for successful PolicyEngine decisions and absence of repeated stack traces.

## Production-oriented settings

Illustrative `.env.production` knobs (names may have `THIRAMAI_*` aliases — see `core/settings.py`):

```bash
# AI / PolicyEngine
THIRAMAI_DECISION_AB_TEST=false
THIRAMAI_POLICY_ENGINE_PCT=100
THIRAMAI_POLICY_SAFE_FALLBACK=true
# THIRAMAI_DISABLE_LEGACY_FALLBACK=false

# Database pool (explicit values satisfy pre-deploy checks)
POOL_SIZE=20
MAX_OVERFLOW=40

# Readiness / observability
# THIRAMAI_HEALTH_REQUIRE_POLICY_ENGINE=1
# THIRAMAI_AI_QUALITY_TRACKING=1
```

## Pilot users

```bash
python scripts/setup_test_data.py \
  --email pilot1@company.com \
  --password 'SecurePass123!' \
  --org-name "Pilot Group"
```

## Monitoring

### Metrics

```bash
curl -sS http://127.0.0.1:8000/metrics | grep -E 'policy_engine|circuit|safe_fallback'
```

Useful gauges/counters include `thiramai_policy_engine_circuit_state`, `thiramai_policy_engine_failures_total`, and `thiramai_safe_fallback_decisions_total`.

### Baseline (after volume)

```bash
curl -sS -X POST http://127.0.0.1:8000/monitoring/ai-quality/baseline \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## Troubleshooting

- **PolicyEngine row in readiness** — `GET /health/ready` → `checks.policy_engine`. See [docs/runbooks/policy-engine-failure.md](../runbooks/policy-engine-failure.md).
- **Circuit breaker** — metrics + runbook above; safe fallback produces `decision_brain_source: safe_fallback`.
- **No rows in `ai_decisions`** — confirm tokens, route `/chat/decision`, and worker/DB connectivity.

## Rollback

```bash
docker compose -f docker-compose.production.yml --env-file .env.production down

git checkout <previous-tag>

./scripts/go_live.sh
```

## More documentation

- [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)
- [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)
- Runbooks: [docs/runbooks/](../runbooks/)
