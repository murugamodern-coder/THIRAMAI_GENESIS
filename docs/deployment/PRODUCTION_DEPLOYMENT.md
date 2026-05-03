# Production deployment guide

This document is the operator checklist for shipping THIRAMAI Genesis to production. It aligns with the repository layout (FastAPI app, Docker Compose production files, health routes, and `scripts/verify_deployment.py`).

## Pre-deployment checklist

### Code quality

- [ ] All tests pass: `pytest tests/ -q`
- [ ] Coverage gates (optional job): see [../development/testing-coverage.md](../development/testing-coverage.md)
- [ ] Security scan: `bandit -r core/ services/ api/ workers/ -ll` (or CI SAST job)
- [ ] Dependency review on changed pins
- [ ] Code review and release notes

### Infrastructure

- [ ] Database backups tested (restore drill)
- [ ] Alembic migrations applied in staging, plan for production
- [ ] TLS certificates valid (not expiring within 30 days)
- [ ] DNS and reverse proxy (same-origin SPA + WebSocket if used) — see `deploy/README.md`
- [ ] Redis and worker processes if using full production compose

### Configuration

- [ ] `.env.production` created from [.env.production.example](../../.env.production.example)
- [ ] Secrets via `core/secrets_manager` policy (prefer AWS/GCP/Vault in prod); see [../operations/secrets-management.md](../operations/secrets-management.md)
- [ ] `DATABASE_URL` and `REDIS_URL` verified from the deployment network
- [ ] `THIRAMAI_CORS_ORIGINS` matches real HTTPS front-end origins
- [ ] `SECRET_KEY` / JWT secret strong and rotated appropriately
- [ ] `THIRAMAI_RLS_BYPASS=0` on tenant-facing API
- [ ] `THIRAMAI_SAFE_ERRORS=1` behind a reverse proxy in production

### Security

- [ ] `THIRAMAI_AUTH_DISABLED=0`
- [ ] Rate limits appropriate (`THIRAMAI_RL_*`)
- [ ] No wildcard CORS in production with credential flows

### Monitoring

- [ ] Prometheus scrape of `/metrics` (plus any `/metrics/thiramai` if enabled)
- [ ] Alerts wired (error rate, latency, DB pool) — see [../SLO.md](../SLO.md) and [../operations/slo-management.md](../operations/slo-management.md)
- [ ] Runbooks accessible: [../runbooks/README.md](../runbooks/README.md)

## Deployment steps

### 1. Verify staging

```bash
git checkout main
git pull origin main

# Example: production compose (adjust file and env path)
# docker compose -f docker-compose.production.yml --env-file .env.production up -d --build

python scripts/verify_deployment.py --url https://staging.example.com
```

Use `--skip-tls-verify` only on local trust-bypass. Use `--skip-cors` if your edge strips CORS on automated OPTIONS probes.

### 2. Tag and promote

Tagging strategy is team-specific; many teams use `vX.Y.Z` and let CI build/push images.

### 3. Monitor the rollout

- GitHub Actions: CI and image build pipelines
- Application logs (JSON access lines when `THIRAMAI_LOG_JSON=1`)
- `GET /health/ready` should return HTTP **200** with `"status":"ready"` when dependencies are satisfied

### 4. Post-deploy verification

```bash
python scripts/verify_deployment.py --url https://app.thiramai.co.in
```

Manual spot checks:

```bash
curl -fsS https://app.thiramai.co.in/health/live
curl -fsS https://app.thiramai.co.in/health/ready
curl -fsS https://app.thiramai.co.in/metrics | head -20
```

### 5. Authentication smoke

The API uses **OAuth2 form** login at `POST /auth/login` (`username` = email or `users.username`, `password` = password). Example (form body, not JSON):

```bash
curl -sS -X POST https://app.thiramai.co.in/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=SECRET"
```

Protected routes should return **401** without `Authorization: Bearer …`.

## Rollback

- **Application:** redeploy previous image / `docker compose` image digest; use platform rollback (`kubectl rollout undo`, PaaS version pin, etc.).
- **Database:** avoid destructive rollback; prefer forward-fix migrations. If you must revert schema, use Alembic downgrade only after backup and with explicit approval.

## Post-deploy (first 24 hours)

- Watch error rate and p95 latency
- Confirm DB pool utilization stays below policy (see readiness `checks.database_pool`)
- Confirm backup jobs completed
- Record any incidents per [../INCIDENT_PLAYBOOK.md](../INCIDENT_PLAYBOOK.md)

## Production URLs (reference)

| Surface | URL |
|---------|-----|
| Command Center (SPA) | https://app.thiramai.co.in |
| Public site | https://thiramai.co.in |
| API (same host or dedicated) | Configure `THIRAMAI_CORS_ORIGINS` to match |

Update this table if your tenant uses a custom domain.

## Related documentation

- [../DEPLOYMENT.md](../DEPLOYMENT.md)
- [../PRODUCTION_GRADE_DEPLOYMENT.md](../PRODUCTION_GRADE_DEPLOYMENT.md)
- [../operations/secrets-management.md](../operations/secrets-management.md)
- [../runbooks/complete-outage.md](../runbooks/complete-outage.md)
