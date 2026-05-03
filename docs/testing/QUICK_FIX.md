# Quick fix guide — tests and local live deploy

## 1. Environment (`.env.production`)

**Automated (recommended):**

```bash
bash scripts/setup_production_env.sh
```

Then edit `.env.production`: set `POSTGRES_PASSWORD`, match `DATABASE_URL`, set `THIRAMAI_CORS_ORIGINS`, API keys as needed.

**Manual:**

```bash
cp .env.production.example .env.production
# Generate secrets
openssl rand -base64 32   # SECRET_KEY
openssl rand -base64 32   # JWT_SECRET_KEY
```

**Verify critical keys:**

```bash
grep -E "THIRAMAI_DECISION_AB_TEST|POOL_SIZE|MAX_OVERFLOW|JWT_SECRET_KEY|DATABASE_URL" .env.production
```

`DATABASE_URL` must use `postgresql+psycopg2://...` for this app unless you standardize on another driver. The database name must match `POSTGRES_DB` in compose (default `thiramai`).

## 2. Pytest failures

```bash
python scripts/fix_test_issues.py
```

Verbose single file:

```bash
python scripts/fix_test_issues.py tests/test_something.py -vv --tb=long
```

If the DB is required:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d db
```

## 3. pip-audit / Python 3.14

Pre-deploy treats many `pip-audit` toolchain errors as **non-blocking** (message: skipped).

To skip audit explicitly:

```bash
python scripts/pre_deployment_check.py --skip-security
```

Prefer **Python 3.12** for full dev parity:

```bash
pyenv install 3.12 && pyenv local 3.12
python -m pip install -r requirements-base.txt
```

## 4. End-to-end local flow

```bash
python scripts/check_ready_for_test.py
bash scripts/setup_production_env.sh    # if .env missing
python scripts/fix_test_issues.py
bash scripts/run_local_live_test.sh
python scripts/analyze_test_results.py --file local_live_test_results.txt
```

## 5. Security

Never commit `.env.production`. Redact tokens in `local_live_test_results.txt` before sharing.

## 6. TRUSTED_PROXY_IPS / `trusted_proxy_ips` (web container restart loop)

**Symptom:**

```text
SettingsError: error parsing value for field "trusted_proxy_ips"
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Cause:** `THIRAMAI_TRUSTED_PROXY_IPS` was empty (`KEY=`) or otherwise not parseable. `pydantic-settings` JSON-decodes list-typed env vars before validators run, so an empty value can break startup.

**Fix in `.env.production`:**

```bash
# Empty allowlist (no trusted proxies as JSON array)
THIRAMAI_TRUSTED_PROXY_IPS=[]
```

Or comma-separated CIDRs (no spaces):

```bash
THIRAMAI_TRUSTED_PROXY_IPS=10.0.0.0/8,172.16.0.0/12
```

**Verify and restart:**

```bash
python scripts/validate_env.py --file .env.production

docker compose -f docker-compose.production.yml --env-file .env.production restart web
# or full stack: docker compose ... up -d

docker compose -f docker-compose.production.yml --env-file .env.production ps web
```

**Expected:** `web` shows `Up (healthy)` and `curl` to `/health/live` returns 200.

## 7. Login fails with "Internal error" / HTTP 500 on `/auth/login`

**Symptom:** UI loads but sign-in returns a generic error — often a **server exception** (migration gap, missing seed, JWT secret, no org membership).

**Diagnose (prefer inside web so `DATABASE_URL` with host `db` works):**

```bash
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web python scripts/diagnose_auth.py
```

From repo root, if your host `DATABASE_URL` points at Postgres on `localhost`:

```bash
python scripts/diagnose_auth.py
```

**Quick fix (migrations + seed + re-check):**

```bash
chmod +x scripts/fix_auth.sh
./scripts/fix_auth.sh
```

**Manual:**

```bash
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic upgrade head
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web python scripts/seed_admin_king.py
```

**Check users in DB:**

```bash
docker compose -f docker-compose.production.yml --env-file .env.production exec -T db \
  psql -U thiramai -d thiramai -c "SELECT id, email, username, is_active FROM users LIMIT 10;"
```

**Login API (form body):**

```bash
curl -sS -X POST "http://127.0.0.1:8000/auth/login" \
  -d "username=admin_king" \
  -d "password=thiramai_2026"
```

Use your published `WEB_PORT` if not 8000.

**Common causes:** missing `alembic_version` / tables, no `seed_admin_king` user or org, **`SECRET_KEY` / `JWT_SECRET_KEY` unset** (JWT creation raises), no active `UserOrganizationMembership`, missing `Role` row.

## Fix 8: Complete database reset (password mismatch)

**Error:** `password authentication failed for user "thiramai"` (or web cannot connect after changing `POSTGRES_PASSWORD`).

**Cause:** Postgres volume still initialized with an **old** password; `.env.production` no longer matches.

**WARNING:** This **deletes all data** in Compose volumes (`thiramai_pgdata`, `thiramai_redis`). Development / disposable stacks only.

### Optional backup (while stack is running)

```bash
bash scripts/backup_before_reset.sh
```

### Automated reset

**Git Bash / Linux / macOS:**

```bash
chmod +x scripts/reset_and_init.sh
./scripts/reset_and_init.sh
```

**PowerShell (Windows):**

```powershell
.\scripts\reset_and_init.ps1
```

Ensures `POSTGRES_PASSWORD` in `.env.production` matches the password inside `DATABASE_URL` for user `@db:5432`, then runs `down -v`, `up -d --build`, `alembic upgrade head`, `seed_admin_king.py`, and auth diagnostics.

### Manual sequence

```bash
docker compose -f docker-compose.production.yml --env-file .env.production down -v
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
# wait for db healthy (~30–60s)
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic upgrade head
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web python scripts/seed_admin_king.py
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web python scripts/diagnose_auth.py
```

### Verify login

Use your published `WEB_PORT` (and `docker compose port web 8000` if unsure):

```bash
curl -sS -X POST "http://127.0.0.1:8000/auth/login" \
  -d "username=admin_king" \
  -d "password=thiramai_2026"
```

Expect JSON with `access_token`.

## PowerShell script errors

### Error: The string is missing the terminator

**Cause:** File encoding corruption or stray invisible characters (sometimes seen with OneDrive sync).

**Fix:**

```powershell
# Option 1: Normalize encoding (recommended)
.\scripts\fix_script_encoding.ps1

# Option 2: Re-checkout the file from git
# git checkout -- scripts/reset_and_init.ps1

# Validate
.\scripts\validate_powershell.ps1

# Then run
.\scripts\reset_and_init.ps1
```

### Error: Execution policy

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\reset_and_init.ps1
```
