# Production CD — GitHub Actions → DigitalOcean

This repo deploys with [`.github/workflows/deploy.yml`](./workflows/deploy.yml): **push to `main`** runs pytest, then SSH to your droplet, `git pull`, `docker compose` build/recreate, and a **`/health/ready`** check. Failures trigger a **git + image rollback** to the previous commit (see workflow comments for limits).

## One-time server setup (`/root/thiramai-app`)

1. **Clone (or move) the repo** to the deploy path and ensure `main` tracks `origin/main`:

   ```bash
   mkdir -p /root/thiramai-app && cd /root/thiramai-app
   git clone https://github.com/<OWNER>/THIRAMAI_GENESIS.git .
   # or: git remote add origin … && git fetch && git checkout main
   ```

2. **Create `.env.production`** (never commit it). Copy from `.env.production.example` and fill secrets. The workflow expects:

   - Path: `/root/thiramai-app/.env.production`
   - `WEB_PORT` if not `8000` (health check uses `http://127.0.0.1:${WEB_PORT}/health/ready`).

3. **Install GitHub Actions deploy key** (dedicated key pair, not your laptop’s daily key):

   On your **workstation**:

   ```bash
   ssh-keygen -t ed25519 -a 200 -C "github-actions-thiramai-deploy" -f ./gha-thiramai-ed25519 -N ""
   ```

   On the **server** (as the user that will run deploy, e.g. `root`):

   ```bash
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   cat >> ~/.ssh/authorized_keys << 'EOF'
   <paste contents of gha-thiramai-ed25519.pub here>
   EOF
   chmod 600 ~/.ssh/authorized_keys
   ```

   Harden SSH (recommended): disable password auth, allow only key auth, consider `AllowUsers` / `Match User` for the deploy user.

4. **Docker**: install Docker Engine + Compose plugin; ensure `docker compose version` works. The deploy user must be in the `docker` group **or** run as `root` (your current layout uses `/root/thiramai-app`).

5. **Git remote**: the server must be able to `git pull origin main` without a password (HTTPS with credential helper, or SSH deploy key with read access to the repo). Typical pattern:

   ```bash
   cd /root/thiramai-app
   git remote set-url origin git@github.com:<OWNER>/THIRAMAI_GENESIS.git
   # Add repo read-only deploy key to GitHub → repo Settings → Deploy keys
   ```

## GitHub repository secrets

Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

| Secret | Example / notes |
|--------|------------------|
| `PRODUCTION_SSH_KEY` | Full private key: `-----BEGIN OPENSSH PRIVATE KEY-----` … `-----END OPENSSH PRIVATE KEY-----` |
| `PRODUCTION_HOST` | Droplet hostname or IP (e.g. `app.thiramai.co.in` or `164.x.x.x`) |
| `PRODUCTION_USER` | `root` or dedicated `deploy` user |
| `PRODUCTION_DEPLOY_PATH` | `/root/thiramai-app` |

Optional:

| Secret | Purpose |
|--------|---------|
| `PRODUCTION_SSH_PORT` | SSH port if not `22` |
| `PRODUCTION_SSH_FINGERPRINT` | Host key SHA256 fingerprint (MITM protection); see below |
| `PRODUCTION_DOCKER_BUILD_NO_CACHE` | Set exactly to `true` to force `docker compose build --no-cache` |
| `PRODUCTION_DEPLOY_SERVICES` | Space-separated list (default: `web worker-jobs worker-alerts`) |
| `PRODUCTION_HEALTH_URL` | Full URL to probe instead of loopback `WEB_PORT` + `/health/ready` |

### Host fingerprint (`PRODUCTION_SSH_FINGERPRINT`)

From your workstation (replace host):

```bash
ssh-keygen -l -f <(ssh-keyscan -t ed25519 app.thiramai.co.in 2>/dev/null) | awk '{print $2}'
```

Paste the **SHA256:…** value into `PRODUCTION_SSH_FINGERPRINT` (see [appleboy/ssh-action](https://github.com/appleboy/ssh-action) `fingerprint` input).

## GitHub Environment (optional)

The workflow uses `environment: production`. In **Settings** → **Environments** → create **`production`**. You can add **required reviewers** so each deploy waits for approval. If you prefer no environment object, remove the `environment: production` line from the `deploy` job in `deploy.yml`.

## What gets deployed

- **Default services**: `web`, `worker-jobs`, `worker-alerts` (same image `build: .` as in `docker-compose.production.yml`). To match an older manual flow that only touched `web`, set secret `PRODUCTION_DEPLOY_SERVICES` to `web`.
- **Build cache**: no `--no-cache` unless you set `PRODUCTION_DOCKER_BUILD_NO_CACHE=true`.
- **Zero downtime**: Compose `up -d --force-recreate` replaces containers; expect a **short blip** on a single-node stack. True zero-downtime needs blue/green or multiple nodes behind a load balancer.

## Manual / emergency deploy

Actions tab → **Deploy production** → **Run workflow** → optionally enable **Skip pytest gate** (use only if CI is blocked and you accept risk).

## Staging

Push to **`develop`** can use [`.github/workflows/deploy-staging.yml`](./workflows/deploy-staging.yml) with `STAGING_*` secrets (separate path and host).

## Troubleshooting

- **SSH fails**: verify port, fingerprint, and that the private key in `PRODUCTION_SSH_KEY` matches the public line on the server.
- **Health check fails**: confirm `WEB_PORT` in `.env.production` matches the published `127.0.0.1:PORT` mapping in `docker-compose.production.yml` and that `/health/ready` responds on the host.
- **Rollback**: workflow resets `git` to pre-pull commit and rebuilds/recreates services; it does **not** reverse database migrations. Run Alembic manually if you need DB rollback.
