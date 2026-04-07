# THIRAMAI — full-stack SaaS production (VPS / AWS / Railway + Nginx / Vercel)

This document ties together **API**, **PostgreSQL**, **Command Center (React/Vite)**, **HTTPS**, **CORS**, **WebSockets**, and **background schedulers** for a public SaaS deployment.

For Docker-first steps, schema, and scripts, start with **`docs/DEPLOYMENT.md`**. For TLS-only Nginx on the API host, see **`docs/PRODUCTION_NGINX_SSL.md`**.

---

## 1. Recommended topology

| Piece | Role | Typical choice |
|--------|------|----------------|
| **API** | FastAPI (Gunicorn + Uvicorn workers in Docker) | Subdomain `api.example.com` |
| **App UI** | Static files from `npm run build` | Subdomain `app.example.com` (Nginx) **or** Vercel |
| **Database** | PostgreSQL | **Supabase**, **RDS**, **Neon**, or Postgres in Docker (VPS only) |
| **TLS** | HTTPS | **Let’s Encrypt** (Certbot) via Nginx or Caddy |
| **Redis** (optional) | Caching / queues | ElastiCache, Upstash, or Redis in Compose |

**DNS**

- `A` / `AAAA`: `api.example.com` → API server (or load balancer).
- `A` / `AAAA`: `app.example.com` → same host (Nginx serves static) **or** Vercel / CloudFront.

---

## 2. Environment variables (production)

Copy **`.env.production.example`** → **`.env.production`** on the server and set at least:

### Required

```env
ENV=production
THIRAMAI_ENV=production

# Managed Postgres (Supabase / RDS / Neon) — use the provider’s connection string.
# SQLAlchemy form (psycopg2):
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require

SECRET_KEY=<long random string; min 32 bytes recommended>
```

### CORS (mandatory in production)

Production **does not** use `allow_origins=["*"]`. List **exact HTTPS origins** of your web app (comma-separated, no spaces unless quoted):

```env
THIRAMAI_CORS_ORIGINS=https://app.example.com
```

If the API is called from the same browser origin only (e.g. Nginx serves the SPA and proxies `/auth`, `/dashboard`, … to the API on loopback), you still set the **public app origin** here (e.g. `https://app.example.com`). If you also open Swagger from `https://api.example.com`, include it:

```env
THIRAMAI_CORS_ORIGINS=https://app.example.com,https://api.example.com
```

### Reverse proxy / client IP (behind Nginx, ALB, Railway)

```env
THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1
THIRAMAI_PROXY_TRUSTED_HOSTS=*
THIRAMAI_SAFE_ERRORS=1
THIRAMAI_LOG_JSON=1
```

### Schedulers (alerts + autonomy)

Alerts and autonomy run **inside the API process** when enabled (see `app.py` startup + `workers/alert_system.py`):

```env
THIRAMAI_ENABLE_ALERT_SCHEDULER=1
THIRAMAI_ALERT_INTERVAL_MINUTES=15

THIRAMAI_ENABLE_AUTONOMY_ENGINE=1
THIRAMAI_AUTONOMY_INTERVAL_MINUTES=15
```

Tune intervals for cost vs responsiveness. For **multiple API replicas**, only one process should run schedulers (use a dedicated “worker” service or external cron calling an internal endpoint — future hardening).

### Auth must stay on

```env
THIRAMAI_AUTH_DISABLED=0
```

### AI keys (if you use Groq / Tavily)

Set `GROQ_API_KEY`, `TAVILY_API_KEY` as in `.env.production.example`.

---

## 3. Database: Supabase / RDS / Neon

1. Create a **PostgreSQL** instance and allow access **only** from your API (security group / IP allowlist / private network).
2. Set `DATABASE_URL` with **`sslmode=require`** (or provider-specific SSL params).
3. Run migrations once per release:

   ```bash
   export DATABASE_URL=postgresql+psycopg2://...
   alembic upgrade head
   ```

See **`docs/DEPLOYMENT.md`** for Alembic notes and `core/migration_head.py`.

---

## 4. Backend deployment

### Option A — VPS + Docker (recommended for control)

Use **`docker-compose.production.yml`** as in **`docs/DEPLOYMENT.md`**:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
```

Point **Nginx** on the host to `127.0.0.1:8000` (or the published port in compose). See **`docs/PRODUCTION_NGINX_SSL.md`** and **section 6** below for **WebSockets**.

### Option B — Railway / Render / Fly.io

- Deploy from this repo’s **`Dockerfile`** (or buildpack).
- Add **PostgreSQL** plugin; map `DATABASE_URL` to `postgresql+psycopg2://...` if needed.
- Set the same env vars as above; **`THIRAMAI_CORS_ORIGINS`** must be your real `https://app...` URL.
- Railway provides HTTPS at the edge — enable **`THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1`**.

### Option C — AWS (ECS + RDS + ALB)

- Container from **`Dockerfile`**; **RDS PostgreSQL** in a private subnet; ALB terminates TLS.
- Inject secrets via **Secrets Manager** / SSM → task env.
- Set **`THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1`** and ensure the ALB sends `X-Forwarded-For` / `X-Forwarded-Proto`.

---

## 5. Frontend: build and host

### Build

From repo root:

```bash
cd web/command_center
npm ci
npm run build
```

Artifacts land under **`static/command_center/`** (see `vite.config.js`: `base: "/static/command_center/"`).

### Option A — Nginx serves static (same or separate VM)

- Copy `static/command_center/` to e.g. `/var/www/thiramai-app/`.
- `server_name app.example.com;`
- `root /var/www/thiramai-app;`
- `try_files $uri $uri/ /index.html;` for SPA routing **if** you use client-side routes under that host.
- Users open: **`https://app.example.com/static/command_center/`** (matches current `base` path), **or** add a redirect `/` → `/static/command_center/`.

### Option B — Vercel

- Connect the repo; set **root directory** to `web/command_center`.
- **Important:** production build output is configured for **`/static/command_center/`**. Either:
  - Deploy behind a path on a custom domain and set Vercel rewrites so `/static/command_center/*` serves the build, **or**
  - For root `https://app.example.com/`, set `base: "/"` in `vite.config.js` for a dedicated production build and rebuild (coordinate with API CORS).

### API URL in the browser

The dev server uses a **Vite proxy** to the API. In production, the SPA is typically served from **`https://app.example.com`** while the API is **`https://api.example.com`**. That is **cross-origin**; you must:

1. Set **`THIRAMAI_CORS_ORIGINS=https://app.example.com`**.
2. Ensure the frontend’s axios `baseURL` points at the API origin **or** use Nginx on `app.example.com` to **reverse-proxy** `/auth`, `/dashboard`, `/chat`, `/ws`, … to `api.example.com` (same-origin to the SPA, no CORS preflight for simple cases).

---

## 6. WebSockets (`/ws/dashboard`)

The Command Center WebSocket is mounted at **`WS /ws/dashboard`** (router prefix `/ws` + route `/dashboard`).

- Browsers use **`wss://`** when the page is **`https://`**.
- Nginx must forward **Upgrade** and **Connection** for WebSocket locations. Example:

```nginx
location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

If the SPA talks to **`wss://api.example.com/ws/dashboard`**, this block belongs on **`api.example.com`**. If you proxy `/ws` from **`app.example.com`** to the API, put the same `location /ws/` on the app vhost.

Auth: clients must follow the API contract (send JWT in the first WebSocket message as JSON — see **`api/routes/dashboard_ws.py`** and OpenAPI description).

---

## 7. HTTPS (Let’s Encrypt)

On Ubuntu + Nginx:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.example.com -d app.example.com
```

Use **HTTP-01** on port 80 or DNS validation if 80 is closed. Renewals: `sudo certbot renew --dry-run`.

---

## 8. Go-live checklist (SaaS)

- [ ] `ENV=production` / `THIRAMAI_ENV=production`
- [ ] `DATABASE_URL` points to managed Postgres with TLS
- [ ] `alembic upgrade head` applied
- [ ] `THIRAMAI_CORS_ORIGINS` = real `https://app...` (and `api...` if needed)
- [ ] `THIRAMAI_AUTH_DISABLED=0`
- [ ] `SECRET_KEY` set; JWT expiry acceptable
- [ ] `THIRAMAI_ENABLE_ALERT_SCHEDULER` / autonomy flags set as needed
- [ ] Nginx: **WebSocket** `location /ws/` if dashboard live updates are used
- [ ] Smoke: `GET https://api.example.com/health/ready`, register + login, load Command Center

---

## 9. Related files

| File | Purpose |
|------|---------|
| `docs/DEPLOYMENT.md` | Docker Compose, Alembic, scripts |
| `docs/PRODUCTION_NGINX_SSL.md` | Nginx + Certbot for API |
| `.env.production.example` | Env template |
| `docker-compose.production.yml` | Full SaaS stack |
| `web/command_center/vite.config.js` | `base` path and `outDir` for `npm run build` |
