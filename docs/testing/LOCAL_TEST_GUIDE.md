# Local live test guide

End-to-end check of Thiramai Genesis on your machine: Docker stack, health probes, PolicyEngine, auth, decision API, metrics, and `verify_live_system.py`.

**Stuck?** See [QUICK_FIX.md](QUICK_FIX.md) (environment, pytest, pip-audit).

## Prerequisites

- **Docker** and **Docker Compose** (v2)
- **Python 3.12+** (project default)
- **Bash** — Git Bash (Windows), or native bash (macOS/Linux)
- **curl** (required by the runner)
- **jq** (optional; `python -m json.tool` is used as fallback)

## Quick test (three commands)

Run from the **repository root**:

```bash
python scripts/check_ready_for_test.py
./scripts/run_local_live_test.sh
python scripts/analyze_test_results.py --file local_live_test_results.txt
```

On **Windows**, if `./scripts/run_local_live_test.sh` is not available in PowerShell:

```bash
bash scripts/run_local_live_test.sh
```

## Step 1 — Pre-test validation

```bash
python scripts/check_ready_for_test.py
```

**Expected:** ends with `✅ SYSTEM READY FOR LIVE TESTING!`

If it fails: restore missing files, ensure shell scripts are executable on Unix (`chmod +x` / `git update-index --chmod=+x`).

## Step 2 — Environment

```bash
cp .env.production.example .env.production
# Edit .env.production — set secrets and URLs
```

Important production-style settings (names may have aliases; see `core/settings.py`):

| Area | Notes |
|------|--------|
| `DATABASE_URL` | Must match your Postgres (inside Docker often `...@db:5432/...`) |
| `SECRET_KEY` / JWT | Required for real auth |
| `POSTGRES_PASSWORD` | Must match what the `db` service expects |
| A/B off | e.g. `THIRAMAI_DECISION_AB_TEST=false` |
| PolicyEngine 100% | e.g. `THIRAMAI_POLICY_ENGINE_PCT=100` |
| Pool | e.g. `POOL_SIZE=20`, `MAX_OVERFLOW=40` |

Ensure an admin-style user exists if you use the default live-test login (`admin_king` / `thiramai_2026`), e.g.:

```bash
python scripts/seed_admin_king.py
```

## Step 3 — Run the live test

```bash
./scripts/run_local_live_test.sh
```

**Duration:** roughly 2–3 minutes (build + 30s wait + API calls).

**Artifacts:**

- `local_live_test_results.txt` — full transcript (gitignored)
- `.cache/local_live_test/` — scratch JSON (gitignored)

**Base URL:** `WEB_PORT` in `.env.production`, or `THIRAMAI_GO_LIVE_BASE_URL`.

## Step 4 — Analyze results

```bash
python scripts/analyze_test_results.py --file local_live_test_results.txt
```

**Healthy run:** `✅✅✅ ALL CRITICAL CHECKS PASSED ✅✅✅` and no critical issues listed.

## Success criteria

| Area | What “good” looks like |
|------|-------------------------|
| Env | `.env.production` present and filled; template validated by `check_ready_for_test.py` |
| Compose | Services **running** (`web`, `db`, etc.) |
| Health | `/health/live`, `/health/ready`, `/health/system` return **HTTP 200** where the runner expects it |
| PolicyEngine | `checks.policy_engine.status` is **healthy** or **degraded** |
| Circuit | **closed** or **half_open** — **open** needs investigation |
| Auth | Login returns `access_token` |
| Decision | `/chat/decision` returns 200 with a `decision` object |
| Brain source | `decision.data.decision_brain_source` is **`policy_engine`** (ideal) or **`safe_fallback`** (degraded but governed) |

### AI brain source

| Value | Meaning |
|--------|---------|
| `policy_engine` | PolicyEngine path active |
| `safe_fallback` | Circuit / failure path; still acceptable for many smoke tests |

### Circuit breaker (from readiness JSON)

| State | Meaning |
|--------|---------|
| `closed` | Normal |
| `half_open` | Recovery probe |
| `open` | Short-circuiting — check logs and [policy engine runbook](../runbooks/policy-engine-failure.md) |

## Troubleshooting

### Docker / compose

```bash
docker compose -f docker-compose.production.yml --env-file .env.production ps
docker compose -f docker-compose.production.yml --env-file .env.production logs --tail 80 web
```

Bring the stack up:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
```

### Readiness not HTTP 200

Read the JSON body in `local_live_test_results.txt` (database, alembic, redis, workers, PolicyEngine). Common fixes: run migrations, fix `DATABASE_URL`, set required env.

### PolicyEngine unhealthy

```bash
curl -sS "http://127.0.0.1:8000/health/ready" | python -m json.tool
```

See: [docs/runbooks/policy-engine-failure.md](../runbooks/policy-engine-failure.md)

### Authentication failed

Confirm user exists and password matches; use `scripts/seed_admin_king.py` or your provisioning flow. Override test credentials with `THIRAMAI_LIVE_VERIFY_USER` / `THIRAMAI_LIVE_VERIFY_PASSWORD`.

### DB verification from the host

If `DATABASE_URL` uses hostname `db`, host-side tools may not connect. The live runner uses `docker compose exec` where possible; for `verify_live_system.py` see `THIRAMAI_LIVE_DB_URL` / `THIRAMAI_LIVE_VERIFY_RELAX_DB` in the deployment docs.

## Inspecting `local_live_test_results.txt`

```bash
grep "STEP 8" local_live_test_results.txt
grep "AI Brain Source" local_live_test_results.txt
grep -iE "error|fail" local_live_test_results.txt
```

## Security

`local_live_test_results.txt` may contain **tokens**, **PII**, or **config snippets**. Do **not** commit it (it is gitignored). **Redact** before sharing.

## More documentation

- [docs/deployment/QUICK_START.md](../deployment/QUICK_START.md)
- Runbooks: [docs/runbooks/](../runbooks/)
