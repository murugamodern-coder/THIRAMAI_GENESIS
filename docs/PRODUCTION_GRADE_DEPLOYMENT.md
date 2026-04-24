# Thiramai Production-Grade Deployment

## Production Architecture

- `nginx` (TLS termination, reverse proxy, websocket upgrade)
- `web` (FastAPI API + static SPA serving)
- `rq-worker` (async execution workers backed by Redis queue)
- `scheduler` (periodic scans/optimizations/rule evaluation loops)
- `redis` (queue + cache + rate limit coordination)
- `db` (PostgreSQL primary data store)
- `backup` (daily pg_dump rotation to mounted volume/object sync target)

Data flow:

1. Client -> `https://app.thiramai.ai` -> Nginx
2. Nginx -> `web:8000`
3. API enqueues long tasks to Redis RQ (`THIRAMAI_ASYNC_QUEUE_MODE=rq`)
4. `rq-worker` consumes async jobs (`mission_execute`, `automation_evaluate`, `opportunity_scan`, `learning_optimize`)
5. `scheduler` periodically enqueues recurring jobs
6. Governance + audit + health + metrics exposed from API

## docker-compose Final

Use `docker-compose.final.yml` with services:

- `db`
- `redis`
- `web`
- `rq-worker`
- `scheduler`
- `backup`
- `nginx`

Highlights:

- health checks on DB/Redis/Web/Nginx
- strict production flags in `web` env:
  - `ENV=production`
  - `THIRAMAI_DEBUG=0`
  - `THIRAMAI_ENFORCE_SECURE_COOKIES=1`
  - `THIRAMAI_DISABLE_AUTO_SCHEMA_CREATE=1`
- JWT hardening env:
  - `JWT_ACCESS_EXPIRE_MINUTES` (recommended 15-30)
  - `JWT_REFRESH_EXPIRE_DAYS` (recommended <= 30)
- queue mode:
  - `THIRAMAI_ASYNC_QUEUE_MODE=rq`

## Deployment Steps

1. **Provision host**
   - Ubuntu 22.04+, Docker + Compose plugin, UFW enabled.
2. **DNS**
   - Point `app.thiramai.ai` A/AAAA records to host.
3. **Prepare environment**
   - Copy `.env.production.example` to `.env.production`.
   - Set `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `THIRAMAI_CORS_ORIGINS`, `POSTGRES_PASSWORD`.
4. **Build + start infra**
   - `docker compose -f docker-compose.final.yml --env-file .env.production up -d --build`
5. **Run migrations**
   - `docker compose -f docker-compose.final.yml --env-file .env.production exec -T web alembic upgrade head`
6. **Issue TLS cert**
   - Run certbot against Nginx webroot for `app.thiramai.ai`.
   - Store under `deploy/nginx/certs`.
7. **Verify health**
   - `GET /health/live`
   - `GET /health/ready`
   - `GET /metrics`
8. **Enable observability**
   - Configure `SENTRY_DSN` and scrape `/metrics` from Prometheus.
9. **Backup validation**
   - Confirm `/backups/thiramai_*.sql.gz` is generated daily.
10. **Go-live checks**
    - Login, execute mission, automation run, opportunity scan, learning refresh.

## Security Checklist

- [ ] `ENV=production` and `THIRAMAI_ENV=production`
- [ ] `THIRAMAI_AUTH_DISABLED=0`
- [ ] `THIRAMAI_SAFE_ERRORS=1`
- [ ] `THIRAMAI_DEBUG=0`
- [ ] `THIRAMAI_ENFORCE_SECURE_COOKIES=1`
- [ ] `THIRAMAI_DISABLE_AUTO_SCHEMA_CREATE=1`
- [ ] `THIRAMAI_CORS_ORIGINS` explicit origins only (no wildcard)
- [ ] `THIRAMAI_ALLOWED_HOSTS` set (`app.thiramai.ai`)
- [ ] JWT access expiry <= 60 min
- [ ] Refresh token lifetime bounded (<= 45 days)
- [ ] Rate limiting configured (user + IP + org)
- [ ] Trusted proxy CIDRs configured (`THIRAMAI_TRUSTED_PROXY_IPS`)
- [ ] Governance guardrails configured (trade/email/loss limits)
- [ ] Kill switch tested
- [ ] Circuit breaker behavior validated
- [ ] Sentry/alerts configured
- [ ] Daily DB backups verified + restore drill tested
- [ ] Log rotation enabled (`deploy/logrotate/nginx-thiramai.conf`)
