# Production deployment checklist

Operator checklist for shipping THIRAMAI Genesis API + workers. Adapt commands to your stack (**Docker Compose** vs **Kubernetes**). This repo defaults to Compose (`docker-compose.production.yml` in repo root).

## Pre-deploy

### Infrastructure

- [ ] PostgreSQL backups automated and restore-drilled
- [ ] `DATABASE_URL` / pool tuning documented ([`.env.production.example`](../.env.production.example))
- [ ] Redis (if used) reachable from `web` + workers
- [ ] TLS termination + cert validity (>30 days)
- [ ] DNS / reverse proxy → `web` health routes

### Security

- [ ] Secrets not committed; production `.env` on host only
- [ ] `THIRAMAI_ENFORCE_SECURE_COOKIES=1`, `THIRAMAI_CORS_ORIGINS` explicit (not `*`)
- [ ] `THIRAMAI_RLS_BYPASS=0` on **web**; only workers that need bypass have `1`
- [ ] Rate limits acceptable for launch traffic (`THIRAMAI_RL_*`)

### AI / decisions

- [ ] `THIRAMAI_DECISION_AB_TEST=false` (100% PolicyEngine path) when cut over
- [ ] `THIRAMAI_POLICY_SAFE_FALLBACK=true` for graceful degradation (or strict per policy)
- [ ] Circuit breaker envs reviewed (`THIRAMAI_POLICY_CB_*`)
- [ ] `GET /health/ready` → `checks.policy_engine` acceptable

### Quality & observability

- [ ] Prometheus scrapes `/metrics`
- [ ] Grafana dashboards imported (`monitoring/grafana/dashboards/`, see [README](../../monitoring/grafana/dashboards/README.md))
- [ ] Alert rules loaded (`monitoring/prometheus/alert-rules.yml`)
- [ ] Runbooks linked from [docs/runbooks/README.md](../runbooks/README.md)

### Tests / CI

- [ ] `pytest` green on release SHA
- [ ] `python scripts/check_critical_coverage.py` (if enforced in your pipeline)
- [ ] `python scripts/verify_deployment.py --url <https://your-host>` post-deploy

## Deploy (Docker Compose)

```bash
git pull
docker compose -f docker-compose.production.yml --env-file .env.production build web
docker compose -f docker-compose.production.yml --env-file .env.production up -d
docker compose -f docker-compose.production.yml --env-file .env.production ps
```

## Post-deploy smoke

```bash
curl -fsS https://YOUR_HOST/health/live
curl -fsS https://YOUR_HOST/health/ready | jq '.checks.policy_engine'
curl -fsS https://YOUR_HOST/metrics | head
```

Decision path (authenticated):

```bash
# OAuth2 form login → Bearer → POST /chat/decision
```

## AI quality API (tenant admin)

- `GET /monitoring/ai-quality` — requires **`ai.admin`** (owner/admin/superadmin).
- `POST /monitoring/ai-quality/baseline` — requires **`tenant.admin`**.
- `POST /monitoring/ai-quality/reset-anomalies` — **`tenant.admin`**.

After stable traffic, establish baseline (default needs ≥100 samples in window; tune `THIRAMAI_AI_QUALITY_MIN_BASELINE`).

## Rollback (Compose)

**Semi-automated:** keep previous image tag / `DEPLOY_TAG` and re-up:

```bash
export DEPLOY_TAG=previous
docker compose -f docker-compose.production.yml --env-file .env.production up -d web
```

**Immediate:** `docker compose … up -d` with last known-good compose + image digest.

For DB: only run `alembic downgrade` if a **bad migration** shipped (test downgrades in staging first).

## First hour watchlist

- [ ] 5xx rate and `/health/ready` status
- [ ] `thiramai_policy_engine_circuit_state`, `thiramai_safe_fallback_decisions_total`
- [ ] `thiramai_ai_quality_anomalies_total` (if quality tracker enabled)
- [ ] DB pool / Redis errors in logs

## Sign-off

Record approver, time, version/git SHA, and any overrides in your ticket system.
