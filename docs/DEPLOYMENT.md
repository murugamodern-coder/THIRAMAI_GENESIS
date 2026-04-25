# Thiramai Deployment Guide

## Standard Deploy Command
```bash
cd /root/thiramai-app
git pull origin main
docker compose -f docker-compose.production.yml --env-file .env.production up -d --force-recreate --build web
sleep 30
docker exec thiramai-app-web-1 alembic upgrade head
bash scripts/post_deploy_check.sh
```

## Environment Variables Required
| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | SQLAlchemy connection string for production Postgres. |
| `REDIS_URL` | Yes | Redis URL used for cache/rate-limit/job coordination. |
| `SECRET_KEY` | Yes | App secret used by core security paths. |
| `JWT_SECRET_KEY` | Yes | JWT signing key used by auth token generation/validation. |
| `THIRAMAI_CORS_ORIGINS` | Yes | Comma-separated allowed frontend origins (HTTPS domains). |
| `EXPECTED_ALEMBIC_REVISION` | Yes | Expected migration revision for readiness checks (default `0071_security_audit_logs`). |
| `POSTGRES_USER` | Yes | Postgres username for DB container bootstrap. |
| `POSTGRES_PASSWORD` | Yes | Postgres password for DB container bootstrap. |
| `POSTGRES_DB` | Yes | Default DB name for DB container bootstrap. |
| `ENVIRONMENT` | Recommended | Set to `production` for production-safe behavior. |
| `ENV` | Recommended | Set to `production` for route and docs protections. |
| `THIRAMAI_ENV` | Recommended | Set to `production` for internal environment checks. |
| `THIRAMAI_ENFORCE_SECURE_COOKIES` | Recommended | Set `1` to force secure cookie policy in production. |
| `THIRAMAI_DISABLE_AUTO_SCHEMA_CREATE` | Recommended | Set `1` to prevent implicit schema creation at runtime. |
| `THIRAMAI_DISABLE_CREATE_ALL` | Recommended | Set `1` to enforce migration-driven schema changes only. |
| `THIRAMAI_SAFE_ERRORS` | Recommended | Set `1` to avoid exposing internal stack traces in API responses. |
| `THIRAMAI_LOG_JSON` | Optional | Set `1` for structured JSON logs in production. |
| `THIRAMAI_RL_TRUST_X_FORWARDED_FOR` | Optional | Set `1` behind trusted reverse proxy/load balancer. |
| `THIRAMAI_TRUSTED_PROXY_IPS` | Optional | Explicit trusted proxy IP allowlist. |
| `THIRAMAI_PROXY_TRUSTED_HOSTS` | Optional | Host trust rules for proxy-aware deployments. |
| `THIRAMAI_AUTH_DISABLED` | Optional | Keep `0` in production; only `1` for controlled debug scenarios. |
| `GUNICORN_WORKERS` | Optional | Number of Gunicorn workers (default `4`). |
| `GROQ_API_KEY` | Optional | API key for Groq-backed AI capabilities. |
| `TAVILY_API_KEY` | Optional | API key for Tavily web research integrations. |

## First Time Setup
1. Provision Ubuntu server with Docker Engine + Compose plugin.
2. Clone repo to `/root/thiramai-app`.
3. Copy env template and populate secrets:
   - `cp .env.production.example .env.production`
4. Confirm `docker-compose.production.yml` contains production safety vars:
   - `THIRAMAI_ENFORCE_SECURE_COOKIES=1`
   - `THIRAMAI_DISABLE_AUTO_SCHEMA_CREATE=1`
   - `THIRAMAI_DISABLE_CREATE_ALL=1`
   - `EXPECTED_ALEMBIC_REVISION=0071_security_audit_logs` (or override if upgraded)
5. Start core stack:
   - `docker compose -f docker-compose.production.yml --env-file .env.production up -d --build`
6. Run migrations:
   - `docker exec thiramai-app-web-1 alembic upgrade head`
7. Make script executable:
   - `chmod +x scripts/post_deploy_check.sh`
8. Run post deploy checklist:
   - `bash scripts/post_deploy_check.sh`
9. Confirm readiness endpoint reports alembic `ok=true`.

## Troubleshooting
- `health/live` fails:
  - Check web container logs: `docker logs --tail 200 thiramai-app-web-1`.
  - Verify container is up: `docker ps`.
- Migration check shows not ready:
  - Run `docker exec thiramai-app-web-1 alembic current` and `alembic upgrade head`.
  - Ensure `EXPECTED_ALEMBIC_REVISION` matches `core/migration_head.py`.
- Auth/login issues after deploy:
  - Confirm `JWT_SECRET_KEY` is set and non-empty in `.env.production`.
  - Restart web after env change: `docker compose ... up -d --force-recreate web`.
- 403/permission issues for admin workflows:
  - Run demo seed role fix: `python scripts/seed_demo_data.py`.
  - Validate membership in `user_organization_memberships`.
- CORS blocked in browser:
  - Recheck `THIRAMAI_CORS_ORIGINS` value and include exact HTTPS origins.
  - Recreate web container after changes.
- Slow or unstable response:
  - Increase `GUNICORN_WORKERS` based on CPU/RAM.
  - Verify DB/Redis latency and container resource pressure.
