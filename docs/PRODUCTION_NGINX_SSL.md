# Nginx reverse proxy + TLS for THIRAMAI (production)

This guide puts **HTTPS** in front of the FastAPI stack (JARVIS / council `/chat`, billing, auth, `/docs`) when you run the API on **`127.0.0.1:8000`** via `docker-compose.production.yml`.

### Site file name (`thiramai` vs `thiramai-api`)

Use whatever filename you already symlink under `sites-enabled` (e.g. `/etc/nginx/sites-available/thiramai`). The important part is **`proxy_pass http://127.0.0.1:8000`** matching **`WEB_PORT`** in `.env.production` (default `8000`). If you use `WEB_PORT=18080`, use `proxy_pass http://127.0.0.1:18080;` instead.

**Invalid backslashes:** Nginx directives must not contain Windows-style line continuations or stray `\` before `proxy_set_header`. Each directive is a single line ending with `;`, for example:

```nginx
proxy_set_header X-Forwarded-Proto $scheme;
```

not `\proxy_set_header` or broken quoted strings.

## Prerequisites

- Ubuntu 22.04 LTS (or similar) with Docker Compose already running the stack.
- DNS **A record**: `api.yourdomain.com` → your server’s public IPv4 (and AAAA if you use IPv6).
- Ports **80** and **443** open to the world; **22** restricted where possible.

## 1. Install Nginx and Certbot

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

## 2. Point THIRAMAI at HTTPS origins

In `.env.production` (or your compose env file), set:

```env
THIRAMAI_CORS_ORIGINS=https://app.yourdomain.com,https://api.yourdomain.com
THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1
```

Recreate the web container after changing env:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d web
```

## 3. Nginx site (HTTP first — Certbot will upgrade to HTTPS)

Create `/etc/nginx/sites-available/thiramai-api`:

```nginx
# Upstream: Docker publishes the API on loopback only (see docker-compose.production.yml)
upstream thiramai_asgi {
    server 127.0.0.1:8000;
    keepalive 32;
}

# Redirect bare HTTP → HTTPS after certificates exist (Certbot adds this block too)
server {
    listen 80;
    listen [::]:80;
    server_name api.yourdomain.com;

    # Allow ACME challenge before TLS is enabled
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/html;
        allow all;
    }

    # WebSocket (Command Center: `WS /ws/dashboard`) — must upgrade HTTP → WebSocket
    location /ws/ {
        proxy_pass http://thiramai_asgi;
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

    location / {
        proxy_pass http://thiramai_asgi;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        # Large JSON / file uploads — tune as needed
        client_max_body_size 25m;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
```

Enable and test:

```bash
sudo ln -sf /etc/nginx/sites-available/thiramai-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 4. Obtain Let’s Encrypt certificates

```bash
sudo certbot --nginx -d api.yourdomain.com
```

Certbot will install a second `server` block for **443** with `ssl_certificate` / `ssl_certificate_key` and turn HTTP into a redirect if you choose that option.

**Renewal** is installed via cron/systemd automatically. Test with:

```bash
sudo certbot renew --dry-run
```

## 5. Security headers (recommended)

Inside the **443** `server` block (Certbot may create `thiramai-api` SSL server; edit that file), add:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

Reload: `sudo nginx -t && sudo systemctl reload nginx`.

## 6. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Do **not** expose Docker’s Postgres (`5432`) or Redis (`6379`) publicly. The production compose file keeps them off the host boundary.

## 7. Smoke test (JARVIS / API)

```bash
curl -fsS -H 'Accept: application/json' https://api.yourdomain.com/
```

Expect JSON liveness. For authenticated routes, use `Authorization: Bearer <JWT>` as usual.

## 8. App hostname (`app.thiramai.co.in`) — root URL must hit the API

The React **Command Center** is built to `static/command_center/` with `base: /static/command_center/`. **FastAPI** (this repo — not Django) should own **`GET /`**: it returns **302** to `/static/command_center/index.html#/personal` when the bundle exists, so `https://app.thiramai.co.in/` never serves legacy `static/index.html`.

**If the browser still shows the old UI:**

1. **Nginx must proxy `/` to the app**, not `alias` to a filesystem copy of `static/index.html`. Bad pattern:

   ```nginx
   # DO NOT serve an on-disk index for / — it bypasses the app and never updates with deploys.
   # location = / { alias /var/www/thiramai/static/index.html; }
   ```

2. **Prefer one source of truth** — either the **app** redirect (default after the code change above) **or** an Nginx redirect, not both with different targets.

   Optional Nginx-only redirect (only if you terminate HTML at Nginx and do not rely on FastAPI for `/`):

   ```nginx
   location = / {
       return 302 /static/command_center/index.html#/personal;
   }
   ```

   Then ensure **`/static/command_center/`** is still reachable (same `proxy_pass` upstream as other paths, unless you offload static files to Nginx with a **synced** tree from each deploy).

3. **Cache busting:** Command Center uses **Vite content hashes** only (`cc-app-[hash].js`, `cc-*-[hash].css`). There must be **no** legacy `cc-app.js` or `?v=` query cache-busting. The FastAPI app sets **`Cache-Control: no-store`** on `/static/command_center/*` (see `CommandCenterStaticNoStoreMiddleware` in `app.py`) and on `index.html`. **Nginx in front of the app should not cache this path** — duplicate the policy at the edge:

   ```nginx
   # Command Center: always fetch fresh index + hashed chunks (no stale bundles)
   location /static/command_center/ {
       proxy_pass http://127.0.0.1:8000;
       proxy_http_version 1.1;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_set_header Connection "";
       add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
       add_header Pragma "no-cache" always;
   }
   ```

   Adjust `proxy_pass` to match your upstream (same as `location /`). If you merge this with a broader `location /`, ensure **`/static/command_center/`** is either more specific (as above) or inherits **`no-store`** — do not add long-lived `expires` for this prefix.

4. **Deploy hygiene:** Before building, clear old artifacts: `rm -rf static/command_center/*` then `npm run build` in `web/command_center` (Dockerfile frontend stage already does this). **Never** serve a cached tree containing unhashed `cc-app.js`.

5. **Shell URL cache-bust:** Set **`THIRAMAI_COMMAND_CENTER_BUILD_ID`** (e.g. `GITHUB_SHA`) in `.env.production` / compose. The API then redirects to  
   `/static/command_center/index.html?v=<build>#/…` and exposes **`GET /api/system/command-center-build`** so legacy `static/index.html` can navigate with the same query. Remove or rotate the id when you no longer need to force clients off a bad cache.

6. **Nginx: one upstream, no duplicate static roots:** Do **not** add a second `location /static/command_center/` that uses `alias` to an old directory on disk while also `proxy_pass` to the app — browsers may get HTML from one path and mismatched ages. Prefer **only** `proxy_pass` to Gunicorn, or only Nginx `alias` to a directory that you **rsync** from each deploy (never mix). A `location /static/command_center/` block must not duplicate a broader `location /` that serves files from a different root.

## 9. Operational notes

| Topic | Guidance |
|--------|-----------|
| **WebSockets** | Use the `location /ws/` block above for `wss://api.yourdomain.com/ws/...`. See `docs/PRODUCTION_SAAS_FULLSTACK.md`. |
| **Long AI calls** | Gunicorn `--timeout 120` matches `proxy_read_timeout 120s`; raise both together if council runs are slower. |
| **Rate limits** | With `THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1`, the **first** `X-Forwarded-For` hop must be trustworthy (your Nginx only). |
| **Alternate TLS** | **Caddy** is a valid alternative (`reverse_proxy 127.0.0.1:8000` + automatic HTTPS). |

See also `docs/DEPLOYMENT.md` for schema order and `docker-compose.production.yml` for the full container set.
