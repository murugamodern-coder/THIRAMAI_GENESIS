# THIRAMAI Genesis — production deployment (Phase 5)

This guide gets the FastAPI app and PostgreSQL off your laptop and onto a URL you can share with pilot users. It assumes you use the Docker assets in this repository.

**Full-stack SaaS (domains, managed Postgres, Nginx/Vercel, WebSocket, schedulers):** see **`docs/PRODUCTION_SAAS_FULLSTACK.md`**.

## What you already have in the repo

| Asset | Purpose |
|--------|---------|
| `Dockerfile` | **Multi-stage** Python 3.12 image; **Gunicorn** + `uvicorn.workers.UvicornWorker` (`GUNICORN_WORKERS`, default 4) on port 8000 |
| `requirements-production.txt` | Adds **gunicorn** (installed in the image with `requirements.txt`) |
| `docker-compose.production.yml` | **SaaS production:** `web` (loopback bind) + `db` + `redis` + **`worker-jobs`** (`run_worker`) + **`worker-alerts`** (`alert_system`); `THIRAMAI_JOB_QUEUE=db` |
| `docker-compose.yml` | **Dev / LAN full stack:** published DB/Redis ports + `web` + **`worker-jobs`** + `worker` (alerts) |
| `docker-compose.prod-slim.yml` | **Minimal:** `web` + `db` only; enable `THIRAMAI_ENABLE_ALERT_SCHEDULER=1` on `web` for alerts |
| `docs/PRODUCTION_NGINX_SSL.md` | **Nginx + Let’s Encrypt** → HTTPS in front of the API (JARVIS `/chat`, `/docs`, billing) |
| `scripts/production_health_probe.sh` | Curl API + `compose exec` Redis/Postgres + service **Up** checks (Linux server) |
| `scripts/deploy_production.sh` | **Final deploy:** go-live checklist → Alembic → Compose → `/health/ready` → “Deployment Successful” |
| `.env.production.example` | Copy to `.env.production` on the server and fill secrets (file is gitignored when named `.env.production`) |

## Database schema — Alembic (recommended for production)

Versioned migrations live under `alembic/versions/`. The baseline revision **`0001`** applies the same ordered DDL as the historical `db/*.sql` bundle (see `core/migration_sql.SQL_BASELINE_FILES`).

```bash
export DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST:5432/DB
alembic upgrade head
```

**Existing database** already created from raw SQL files and **without** `alembic_version`: stamp once if the schema matches revision `0001`:

```bash
alembic stamp 0001
```

Then use forward-only migrations for new changes.

Production / CI: set **`ENV=production`** or **`THIRAMAI_DISABLE_CREATE_ALL=1`** so automatic `create_all` is **not** used as the schema driver (see `core/schema_mode.py` and `scripts/sre_health_check.py`).

---

## One-time: database schema (manual SQL, legacy)

Apply SQL in dependency order on **empty** Postgres (or migrate an existing DB). Typical order:

1. `db/db_schema.sql`
2. `db/auth_rbac.sql`
3. `db/approvals_table.sql`
4. `db/notifications_alerts.sql`
5. `db/learning_logs.sql`
6. `db/system_audit_logs.sql`
7. `db/bills_table.sql`
8. `db/departments.sql` (if not already in your main schema)
9. `db/inventory_gst_columns.sql` (Phase 4 GST column)
10. `db/perf_indexes_phase2.sql` (optional indexes)
11. `db/factory_os.sql` (Factory OS: `project_stages`, billing hold, staff assignments)

From a machine that can reach Postgres:

```bash
# Example: compose Postgres on localhost port 5432
export PGPASSWORD='your_db_password'
psql -h 127.0.0.1 -U thiramai -d thiramai -f db/db_schema.sql
# ... repeat for each file
```

Or `docker compose exec db psql -U thiramai -d thiramai -f - < db/db_schema.sql` if you mount the repo into the container.

## Path A — Single VPS (DigitalOcean Droplet, AWS EC2 / Lightsail, Hetzner, etc.)

Best balance of control and cost for early SaaS pilots.

### Steps

1. **Create a VM** (Ubuntu 22.04 LTS recommended), 2 GB RAM minimum for Postgres + API, 4 GB safer under load.
2. **Point DNS** — e.g. `api.yourdomain.com` → VM public IP (A record).
3. **Install Docker** — [Docker Engine + Compose plugin](https://docs.docker.com/engine/install/ubuntu/).
4. **Clone the repo** on the server (or `scp`/`rsync` a release tarball).
5. **Secrets** — `cp .env.production.example .env.production` and set:
   - `POSTGRES_PASSWORD`, matching `DATABASE_URL`
   - `SECRET_KEY` (long random string)
   - `GROQ_API_KEY`, `TAVILY_API_KEY`
   - `THIRAMAI_CORS_ORIGINS` = your real HTTPS front-end origins (comma-separated, no spaces unless quoted)
6. **TLS reverse proxy** (recommended) — install **Caddy** or **Nginx** on the host:
   - Listen 443 → proxy to `127.0.0.1:8000` (or only expose `8000` on localhost in compose and proxy to that).
   - Set `THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1` once you trust the proxy’s `X-Forwarded-For`.
7. **Start the stack**

   **Recommended SaaS (Gunicorn, Redis, DB job queue + alert worker):**

   ```bash
   docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
   ```

   Put **Nginx** (or Caddy) on the host for TLS → `127.0.0.1:8000` — see `docs/PRODUCTION_NGINX_SSL.md`.

   **Minimal (no Redis / no separate workers):**

   ```bash
   docker compose -f docker-compose.prod-slim.yml --env-file .env.production up -d --build
   ```

   **Dev-style full stack** (published Postgres/Redis ports, `worker-jobs` + alert `worker`):

   ```bash
   docker compose --env-file .env up -d --build
   ```

8. **Smoke test** — `curl -fsS -H 'Accept: application/json' https://api.yourdomain.com/` should return JSON liveness.
9. **Register first tenant** — `POST /auth/register` then exercise `/docs` as needed.

### Firewall

- Allow **22** (SSH, restrict to your IP if possible), **80/443** (HTTP/HTTPS).
- **Do not** expose Postgres (`5432`) to the public internet.

## Path B — Railway

Railway fits quick deploys; you add a **PostgreSQL** plugin and a **service** from this repo’s `Dockerfile`.

### Steps

1. Create a **new project** → **Deploy from GitHub** (or CLI).
2. Add **PostgreSQL**; copy the **public** or **internal** `DATABASE_URL` Railway provides. Map it to SQLAlchemy form if needed: `postgresql+psycopg2://...` (same user/pass/host/db as Railway shows).
3. Set **variables** in the web service: `SECRET_KEY`, `GROQ_API_KEY`, `TAVILY_API_KEY`, `THIRAMAI_CORS_ORIGINS`, `THIRAMAI_SAFE_ERRORS=1`, `THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1` (Railway’s edge sets forwarded headers).
4. **Build command** empty (Dockerfile default); **start** default `CMD` or override with workers if needed.
5. Run **schema** once: use Railway’s Postgres web console or a one-off job container with `psql` + your `db/*.sql` files.
6. **Custom domain** — attach in Railway UI; enable HTTPS (automatic on Railway).

**Note:** Railway may not run `docker-compose.yml` as-is; treat Compose as reference and map services to Railway primitives (one web service + Postgres; optional Redis later).

## Path C — AWS (high level)

- **ECS Fargate** + **RDS PostgreSQL** + **Application Load Balancer**: container from this `Dockerfile`; store secrets in **Secrets Manager** or SSM; inject as env vars. Apply DDL on RDS with a bastion or CI job.
- **Elastic Beanstalk** “Docker” platform: zip repo + Dockerfile; configure env vars in console; add RDS and security groups so only the app tier talks to Postgres on 5432.

Operational extras: **CloudWatch Logs** for container stdout; **alarms** on 5xx and CPU.

## Gunicorn / worker count (production image)

The default **Dockerfile** runs **Gunicorn** with **Uvicorn workers** (`-k uvicorn.workers.UvicornWorker`). Tune replicas with env:

```env
GUNICORN_WORKERS=4
```

Rule of thumb: start with **2–4** workers per vCPU for mixed I/O + CPU; watch memory (each worker loads the app). **JWT** state is client-side — no sticky sessions required. Use **one shared Postgres** for all `web` workers and **`worker-jobs`** processes.

For a **single uvicorn** process (e.g. local `--reload`), override the container command:

```yaml
command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

## Monitoring and logs (real time)

| Approach | When to use |
|----------|-------------|
| `docker compose logs -f web` | Fastest; no extra software |
| `scripts/tail_compose_logs.ps1` / `scripts/tail_compose_logs.sh` | Same as above with sensible defaults |
| [Dozzle](https://dozzle.dev/) | Lightweight web UI for Docker logs on the VPS (`docker run -p 8888:8080 -v /var/run/docker.sock:/var/run/docker.sock amir20/dozzle`) — protect with auth / VPN |
| **Grafana Loki** + Promtail | Centralized logs if you run multiple VMs |
| **Grafana Cloud** / **Datadog** / **Better Stack** | Managed log drain + alerts (paid tiers) |

Errors: with `THIRAMAI_SAFE_ERRORS=1`, clients see generic messages; full tracebacks go to **container stdout** — aggregate those streams in your chosen tool. Search for `orchestrator.`, `ERROR`, `Traceback` in logs.

## Final deployment sequence (scripted)

From the repo root on the server (bash), with `.env.production` filled and Docker running:

```bash
chmod +x scripts/deploy_production.sh
./scripts/deploy_production.sh
```

The script runs, in order:

1. **`python scripts/go_live_checklist.py`** — env vars, PostgreSQL + Alembic head (see `core/migration_head.py`, e.g. `0009_ai_ltm_hitl`), Redis PING, worker heartbeats (`job_worker` or `alert_worker`).
2. **`alembic upgrade head`** — ensures Phase 8 (and prior) migrations are applied.
3. **`docker compose -f docker-compose.production.yml --env-file .env.production up -d --build`**
4. **`curl`** against **`http://127.0.0.1:${WEB_PORT:-8000}/health/ready`** with retries until HTTP success.
5. Prints **`Deployment Successful`** and, on Linux, **`logger -t thiramai ...`** when `logger` is available.

**Cold start:** `go_live_checklist.py` expects workers to already be writing Redis heartbeats. For a **first** deploy on an empty host, either run Compose (and Alembic) once to start workers, then run the checklist, or bootstrap with:

```bash
export THIRAMAI_SKIP_GO_LIVE_CHECKLIST=1
./scripts/deploy_production.sh
unset THIRAMAI_SKIP_GO_LIVE_CHECKLIST
python scripts/go_live_checklist.py   # after workers are up
```

Equivalent manual steps (same order as the script when not skipping):

```bash
set -a && source .env.production && set +a
python scripts/go_live_checklist.py
alembic upgrade head
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
curl -sfS "http://127.0.0.1:${WEB_PORT:-8000}/health/ready"
echo "Deployment Successful"
```

## Rollback

```bash
docker compose -f docker-compose.prod-slim.yml --env-file .env.production pull   # if using a registry image
docker compose -f docker-compose.prod-slim.yml --env-file .env.production up -d --build
```

Tag images by git SHA in CI for predictable rollbacks.

## Checklist before inviting users

- [ ] `THIRAMAI_AUTH_DISABLED` is **not** `1`
- [ ] `SECRET_KEY` is unique and long; JWT expiry acceptable for your risk model
- [ ] `THIRAMAI_CORS_ORIGINS` lists only your real sites (HTTPS)
- [ ] Postgres not exposed publicly; backups enabled (snapshots or `pg_dump` cron)
- [ ] HTTPS termination in place
- [ ] DB migrations / DDL applied, including `inventory_gst_columns.sql` if using GST
- [ ] Smoke: `/` JSON liveness, `/docs`, `POST /auth/register`, one authenticated API call
