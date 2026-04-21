# THIRAMAI production deployment (Phases 70–76)

This directory contains **only** deployment configuration: Nginx, TLS, process supervision notes, env templates, health checks, and log rotation. **Application code is unchanged.**

**End-to-end release validation:** see **`deploy/E2E-VALIDATION-RUNBOOK.md`** and **`deploy/scripts/e2e-validate-production.ps1`** / **`.sh`**.

**Missing `/ai/goal` on production:** see **`deploy/PRODUCTION-API-REBUILD.md`** — the production stack must **`build`** the **`web`** image from git (Compose now defines **`build:`** for **`web`**).

## Topology

```text
Internet ──► Nginx (TLS, gzip, static SPA, WebSocket-aware proxy) ──► FastAPI :8000 (loopback)
                                              └──► Docker: Postgres, Redis, workers (optional goal worker)
```

**Domain target:** `https://app.thiramai.co.in` → React static files from `client/build`, API on the **same origin** (set `REACT_APP_API_URL` empty at build time so the browser calls `/ai`, `/api`, `/auth` relatively).

---

## Phase 70 — Nginx

| File | Purpose |
|------|---------|
| `nginx/conf.d/10-thiramai-production.conf` | **`limit_req_zone`** for `/ai`, **`log_format thiramai_combined`** (effective IP + `X-Forwarded-For`), **`limit_req_status 429`** |
| `nginx/sites-available/app.thiramai.co.in.conf` | HTTP→HTTPS, security headers, gzip+`gzip_vary`, **`/ai` rate limit + WebSocket upgrade**, API paths, static SPA, `/metrics` IP lockdown |
| `nginx/snippets/proxy-thiramai-api.conf` | Shared proxy headers (forwards **`X-Forwarded-For`** / **`X-Real-IP`** to FastAPI), long timeouts |
| `nginx/snippets/thiramai-real-ip-from-upstream.conf.example` | Optional **real client IP** when this Nginx sits **behind** another LB (do not enable on the public Internet edge unless you trust the upstream) |
| `nginx/nginx-http-map-websocket.conf` | **`$connection_upgrade` map** — paste once into `/etc/nginx/nginx.conf` inside `http { }` |
| `nginx/WEBSOCKET-CHECKLIST.md` | WebSocket header / upgrade validation notes |

**Install (order matters: `conf.d` before `sites-enabled` on Debian/Ubuntu):**

```bash
sudo cp deploy/nginx/conf.d/10-thiramai-production.conf /etc/nginx/conf.d/
sudo cp deploy/nginx/snippets/proxy-thiramai-api.conf /etc/nginx/snippets/
sudo cp deploy/nginx/sites-available/app.thiramai.co.in.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/app.thiramai.co.in.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Adjust `root` in the site file if your deployed build path differs from `/var/www/thiramai/client/build`.

---

## Phase 71 — HTTPS (Let’s Encrypt)

See **`deploy/certbot/README.md`**. Renewal is normally via **certbot’s systemd timer**; use a **reload nginx** deploy hook after renew.

---

## Phase 72 — Process management (Docker preferred)

Existing repo compose files:

- `docker-compose.production.yml` — API (`web`), Postgres, Redis, `worker-jobs`, `worker-alerts`; **`restart: unless-stopped`**; **`stop_grace_period`** on `web` / workers for clean SIGTERM drains; JSON log rotation via `logging.options`.
- `docker-compose.goal-worker.yml` — optional THIRAMAI goal worker + shared volume.

Publish the API **only on localhost** from the host perspective:

```yaml
ports:
  - "127.0.0.1:${WEB_PORT:-8000}:8000"
```

(**Already aligned** in `docker-compose.production.yml`.)

Optional **systemd** wrapper: `systemd/thiramai-docker-stack.service.example`.

---

## Phase 73 — Environment

- Start from **`.env.production.example`** at repo root.
- Merge edge-focused flags from **`deploy/env/production.edge.example`** (`THIRAMAI_CORS_ORIGINS`, `THIRAMAI_ALLOWED_HOSTS`, `THIRAMAI_SAFE_MODE=0`, etc.).
- Keep **secrets out of git**; inject via CI or host `EnvironmentFile`.

---

## Phase 74 — Domain routing

- DNS **A/AAAA** for `app.thiramai.co.in` → server.
- Nginx serves the SPA and proxies API paths so **one hostname** serves UI + backend.
- Build client with **same-origin** API:

```bash
cd client
# Windows PowerShell:
$env:REACT_APP_API_URL=""; npm run build
# Unix:
REACT_APP_API_URL= npm run build
```

Deploy `client/build/*` to the directory set in `root` in the Nginx site config.

---

## Phase 75 — Health monitoring

- **`deploy/scripts/healthcheck-api.sh`** — curls `/health/live`; logs via `logger`; optional **`ALERT_WEBHOOK_URL`** (Slack-compatible JSON) using **Python 3** if available.
- **`deploy/scripts/cron-example.txt`** — sample cron line.

---

## Phase 76 — Log management

- **Nginx:** `deploy/logrotate/nginx-thiramai.conf`
- **Docker JSON files:** prefer **`max-size` / `max-file`** in compose (already on `web`/`db`/`redis`); optional `docker-containers-json.conf` for file aggregates.
- **Verify:** `deploy/scripts/verify-logrotate.sh` (runs `logrotate -d` on the installed stanza).

---

## Production hardening (summary)

| Area | What was added |
|------|----------------|
| Security headers | HSTS preload, X-Frame-Options SAMEORIGIN, XCTO nosniff, Referrer-Policy, Permissions-Policy |
| `/ai` rate limit | **30 r/s per IP**, **burst 80** (`limit_req` in `location ^~ /ai`) — tune `10-thiramai-production.conf` if legitimate traffic hits 429 |
| Client IP logging | **`log_format thiramai_combined`**: logs **`$remote_addr`** (effective after optional `real_ip`) and **`$http_x_forwarded_for`** |
| Backup retention | **`deploy/scripts/backup-cleanup.sh`** + **`deploy/scripts/cron-backup-cleanup.example.txt`** |
| WebSockets | **`Upgrade`** / **`Connection $connection_upgrade`** retained on `/ai`; see **`deploy/nginx/WEBSOCKET-CHECKLIST.md`** |
| Docker restarts | **`restart: unless-stopped`** unchanged; **`stop_grace_period`** added for graceful shutdown |

---

## Operational checklist

1. Postgres backups + restore drill; schedule **`backup-cleanup.sh`** for old dumps  
2. Rotate `SECRET_KEY`, DB password, API keys on a schedule  
3. Restrict `/metrics` and `/docs` on public IPs (already stubbed for `/metrics`)  
4. Confirm **`THIRAMAI_PROXY_TRUSTED_HOSTS`** matches your edge (see `.env.production.example`)  
5. After editing Nginx: **`sudo nginx -t`** then **`reload`**  
6. Confirm **`/etc/nginx/conf.d/10-thiramai-production.conf`** is installed (required for `thiramai_combined` log format and `/ai` zone)  
7. Dry-run logrotate: **`sudo deploy/scripts/verify-logrotate.sh`**  
8. **`docker compose … up -d`** then **`docker compose ps`** — all services **running**, **`Up`** after simulated **`compose restart`**
