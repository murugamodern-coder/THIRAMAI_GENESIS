# Thiramai Sovereign OS
> AI-Native Business Operating System for Indian SMBs

[![CI](https://github.com/murugamodern-coder/THIRAMAI_GENESIS/actions/workflows/ci.yml/badge.svg)](https://github.com/murugamodern-coder/THIRAMAI_GENESIS/actions/workflows/ci.yml)
[![Test Coverage](https://github.com/murugamodern-coder/THIRAMAI_GENESIS/actions/workflows/test-coverage.yml/badge.svg)](https://github.com/murugamodern-coder/THIRAMAI_GENESIS/actions/workflows/test-coverage.yml)
[![codecov](https://codecov.io/gh/murugamodern-coder/THIRAMAI_GENESIS/branch/main/graph/badge.svg)](https://codecov.io/gh/murugamodern-coder/THIRAMAI_GENESIS)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[![Status](https://img.shields.io/badge/status-live-brightgreen)]()
[![Version](https://img.shields.io/badge/version-1.0.0-blue)]()
[![Security](https://img.shields.io/badge/security-hardened-orange)]()

## 🚀 ONE-COMMAND DEPLOY

```bash
chmod +x scripts/full_go_live.sh scripts/go_live.sh
./scripts/full_go_live.sh
```

This will:

1. Check `.env.production` (and copy from `.env.production.example` once if missing)
2. Run pre-deployment checks (`--skip-security --skip-coverage` for speed)
3. Run `scripts/go_live.sh` (full pre-deploy, build, health, `verify_deployment.py`) — set `GO_LIVE_CONFIRM=no` to get the interactive prompt
4. Run `scripts/verify_live_system.py` against your API base URL (`WEB_PORT` / `THIRAMAI_GO_LIVE_BASE_URL`)

**Details:** [docs/deployment/QUICK_START.md](docs/deployment/QUICK_START.md)

If Postgres in `DATABASE_URL` uses the Docker hostname `db`, host-side DB checks may need `THIRAMAI_LIVE_VERIFY_RELAX_DB=1` or `THIRAMAI_LIVE_DB_URL` pointing at a mapped port.

## ✅ Ready to test?

```bash
python scripts/check_ready_for_test.py
./scripts/run_local_live_test.sh
python scripts/analyze_test_results.py --file local_live_test_results.txt
```

**Guide:** [docs/testing/LOCAL_TEST_GUIDE.md](docs/testing/LOCAL_TEST_GUIDE.md) · **Troubleshooting:** [docs/testing/QUICK_FIX.md](docs/testing/QUICK_FIX.md)

### Security note: P0 fixes applied

Two critical findings from the [CTO audit](docs/audit/CTO_AUDIT_2026_05.md) have been remediated:

1. **RLS enforcement** — `core/database.py` now uses the valid `SET LOCAL row_security = on` syntax (PostgreSQL rejected the previous `= force`) and the `after_begin` listener raises on failure instead of swallowing it.
2. **App role separation** — migration `0079_create_app_role_fix_rls` creates the `thiramai_app` role (`NOSUPERUSER NOBYPASSRLS`). The web service connects as `thiramai_app`; only the migration role retains `superuser_bypass`. RLS `tenant_isolation` is genuinely enforced for every API request.

See [docs/deployment/P0_FIXES.md](docs/deployment/P0_FIXES.md) for the manual deployment steps and verification checklist.

### Configure AI API Keys

The platform expects **GROQ** and **Tavily** keys for AI chat and related flows (see [docs/setup/AI_KEYS.md](docs/setup/AI_KEYS.md)).

```bash
# Add to .env.production
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key
```

**Get keys:** [Groq Console](https://console.groq.com/) · [Tavily](https://tavily.com/)

**Apply after editing:**

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d --force-recreate web
```

## Final Go-Live Steps

After `docker compose … up` / build finishes and containers are healthy:

### 1. Verify Docker services

```bash
python scripts/check_docker_status.py

# Or wait for services to become healthy (default timeout 300s)
python scripts/check_docker_status.py --wait --timeout 300
```

### 2. Quick health check

```bash
chmod +x scripts/quick_health_check.sh
./scripts/quick_health_check.sh
```

Resolves **`THIRAMAI_GO_LIVE_BASE_URL`**, then **`WEB_PORT`** from `.env.production`, then the published **`docker compose … port web 8000`** mapping (same idea as `run_local_live_test.sh`).

### 3. Full live test and analysis

```bash
./scripts/run_local_live_test.sh
python scripts/analyze_test_results.py --file local_live_test_results.txt
```

### 4. Checklist and sign-off

Follow **[docs/deployment/GO_LIVE_CHECKLIST.md](docs/deployment/GO_LIVE_CHECKLIST.md)**.

**Expected:** Docker all healthy, quick health OK, analyzer reports no critical issues, PolicyEngine **healthy** or **degraded**, circuit **closed** (or briefly **half_open**), decision brain source as configured.

When all of the above pass, the stack is ready to treat as **live** for your environment.

## Troubleshooting

### Tests failing?

```bash
python scripts/fix_test_issues.py
```

### Environment missing or incomplete?

```bash
bash scripts/setup_production_env.sh
```

### pip-audit or bandit blocking pre-deploy?

```bash
python scripts/pre_deployment_check.py --skip-security
```

### Need the full checklist?

See [docs/testing/QUICK_FIX.md](docs/testing/QUICK_FIX.md).

### Web container failing to start (`trusted_proxy_ips`)?

**Error:** `error parsing value for field "trusted_proxy_ips"` / `JSONDecodeError` on startup.

```bash
python scripts/validate_env.py --file .env.production
```

Set a valid allowlist in `.env.production` (empty JSON array is fine):

```bash
THIRAMAI_TRUSTED_PROXY_IPS=[]
```

Then restart:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production restart web
```

See [docs/testing/QUICK_FIX.md](docs/testing/QUICK_FIX.md) section 6.

### Login fails with "Internal error"?

```bash
# DB + JWT checks (run inside web if DATABASE_URL uses hostname `db`)
docker compose -f docker-compose.production.yml --env-file .env.production exec -T web python scripts/diagnose_auth.py

# Or from host if DATABASE_URL is reachable locally:
python scripts/diagnose_auth.py

# Migrations + seed admin (inside stack)
chmod +x scripts/fix_auth.sh
./scripts/fix_auth.sh
```

**Details:** [docs/testing/QUICK_FIX.md](docs/testing/QUICK_FIX.md) (section 7).

### Database password mismatch / stale Postgres volume?

**Error:** `password authentication failed for user "thiramai"` — often after changing `.env.production` without recreating the DB volume.

**Destructive fix (dev only — deletes DB + Redis data):**

```bash
./scripts/reset_and_init.sh
```

**PowerShell:**

```powershell
.\scripts\reset_and_init.ps1
```

**See:** [Complete reset guide](docs/testing/QUICK_FIX.md#fix-8-complete-database-reset-password-mismatch).

### PowerShell script issues?

```powershell
# Fix encoding (stray Unicode / line endings)
.\scripts\fix_script_encoding.ps1

# Validate syntax
.\scripts\validate_powershell.ps1

# Execution policy (current process only)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Run reset
.\scripts\reset_and_init.ps1
```

## 🧪 Local Live Testing

### Run Complete Test Suite

```bash
chmod +x scripts/run_local_live_test.sh
./scripts/run_local_live_test.sh
```

Captures output to **`local_live_test_results.txt`** (and scratch JSON under **`.cache/local_live_test/`**).

Use **`THIRAMAI_GO_LIVE_BASE_URL`**, **`WEB_PORT`** in `.env.production`, or **`THIRAMAI_LIVE_VERIFY_*`** env vars as for other deploy scripts.

### Analyze Results

```bash
python scripts/analyze_test_results.py --file local_live_test_results.txt
```

### What Gets Tested

- Environment snapshot (non-secret keys)
- Docker Compose service table
- Pre-deployment checks (fast path: skip security & coverage)
- `docker compose … up -d --build`
- Health: `/health/live`, `/health/ready`, `/health/system`
- PolicyEngine + circuit breaker (from ready JSON)
- Login → `/chat/decision` → brain source
- `/monitoring/ai-quality`
- `/metrics` sample lines
- Web container logs (tail)
- `verify_live_system.py`

### Share Results

Share **`local_live_test_results.txt`** for analysis (avoid posting tokens).

---

## Production status

| Item | Detail |
|------|--------|
| **Release** | v1.0.0 (see git tags / CI) |
| **Readiness** | Hardening tracks: DB pool, secrets, SLOs, runbooks, critical-path coverage CI |
| **Live app** | [https://app.thiramai.co.in](https://app.thiramai.co.in) |
| **Public site** | [https://thiramai.co.in](https://thiramai.co.in) |
| **Deployment guide** | [docs/deployment/PRODUCTION_DEPLOYMENT.md](docs/deployment/PRODUCTION_DEPLOYMENT.md) |
| **Production checklist** | [docs/deployment/PRODUCTION_CHECKLIST.md](docs/deployment/PRODUCTION_CHECKLIST.md) |
| **Go-live checklist (final)** | [docs/deployment/GO_LIVE_CHECKLIST.md](docs/deployment/GO_LIVE_CHECKLIST.md) |
| **Go-live automation** | `bash scripts/go_live.sh` or **`./scripts/full_go_live.sh`** (see [QUICK_START](docs/deployment/QUICK_START.md)) |
| **Deploy tag helper** | `bash scripts/deploy_production.sh` |
| **Post-deploy checks** | `python scripts/verify_deployment.py --url https://app.thiramai.co.in` |
| **Env template** | [.env.production.example](.env.production.example) |

## 🚀 Quick Start (Production)

### Deploy in a few minutes

```bash
chmod +x scripts/go_live.sh
./scripts/go_live.sh
```

This runs pre-deployment verification, builds and starts the production compose stack, probes `/health/ready`, checks PolicyEngine status, and runs `scripts/verify_deployment.py`.

**Details:** [docs/deployment/QUICK_START.md](docs/deployment/QUICK_START.md)

### Verify locally

```bash
curl -sS http://127.0.0.1:8000/health/ready
curl -sS -X POST http://127.0.0.1:8000/chat/decision \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"test"}'
```

Use the host/port you exposed (default `WEB_PORT` in `docker-compose.production.yml` is `8000`).

### Monitor

- Health: `/health/ready`
- Metrics: `/metrics`
- AI quality: `/monitoring/ai-quality` (authenticated)

## AI decision path (PolicyEngine)

- **Routing:** `DecisionBrainV2` (`services/decision_brain_v2.py`) uses PolicyEngine when `THIRAMAI_DECISION_AB_TEST` / `DECISION_AB_TEST` is not truthy; with A/B on, `THIRAMAI_POLICY_ENGINE_PCT` / `POLICY_ENGINE_PCT` / `POLICY_ENGINE_PERCENTAGE` controls the traffic split.
- **Production defaults:** `.env.production.example` and `docker-compose.production.yml` set A/B **off** and percentage **100**.
- **Strict mode:** `THIRAMAI_DISABLE_LEGACY_FALLBACK` / `DISABLE_LEGACY_FALLBACK` re-raises on PolicyEngine errors (no in-process `safe_fallback`, no Groq in `api/routes/ai_chat.py` when the V2 bundle is missing).
- **Readiness:** `GET /health/ready` includes `checks.policy_engine`; set `THIRAMAI_HEALTH_REQUIRE_POLICY_ENGINE=1` to fail the probe when the engine check fails.
- **Circuit breaker:** `services/policy_engine_wrapper.py` wraps `PolicyEngine.decide` (per-process). Metrics: `thiramai_policy_engine_circuit_state`, `thiramai_safe_fallback_decisions_total`, `thiramai_policy_engine_wrapped_success_total`.
- **Degraded path:** With `THIRAMAI_POLICY_SAFE_FALLBACK=true` (default), PolicyEngine failures emit **`safe_fallback`** (`decision.data.decision_brain_source` = `safe_fallback`) before Groq legacy. Set `THIRAMAI_POLICY_SAFE_FALLBACK=false` to skip that and use legacy only (when fallback is allowed).
- **Breaker tuning:** `THIRAMAI_POLICY_CB_FAILURE_THRESHOLD`, `THIRAMAI_POLICY_CB_SUCCESS_THRESHOLD`, `THIRAMAI_POLICY_CB_TIMEOUT_SECONDS` (aliases `CIRCUIT_BREAKER_*`).
- **Runbook:** [docs/runbooks/policy-engine-failure.md](docs/runbooks/policy-engine-failure.md)  
- **Quality (in-process):** `GET /monitoring/ai-quality` (`ai.admin`), baseline `POST /monitoring/ai-quality/baseline` (`tenant.admin`). Tuning: `THIRAMAI_AI_QUALITY_WINDOW`, `THIRAMAI_AI_QUALITY_MIN_BASELINE`, `THIRAMAI_AI_QUALITY_TRACKING`. Prometheus: `thiramai_ai_quality_anomalies_total`.
- **Alerts:** `monitoring/prometheus/alert-rules.yml` → `policy_engine_alerts` (circuit + safe fallback rate).

**Historical handover note:** Client handover score 96/100 (April 2026 audit). Treat operational readiness as the combination of tests, monitoring, and runbooks above—not a single static number.

## 🎯 What is Thiramai?
Thiramai Sovereign OS is an AI-first operating system that unifies business operations, personal execution, and decision intelligence into one command-driven platform. It helps founders and teams run inventory, billing, planning, and daily execution with governance, auditability, and production-grade security built in.

## ✨ Key Features
- Command Center — AI-powered business command interface
- Business OS — Inventory, Billing, Production management
- Personal OS — Health, Finance, Daily briefing
- Control Center — Governance and decision intelligence
- Research Engine — Market intelligence and opportunity detection

## 🚀 Live Demo
https://app.thiramai.co.in

## 🏗️ Architecture
```text
                        +-----------------------------+
                        |  React + Vite Frontend      |
                        |  Command Center UI          |
                        +--------------+--------------+
                                       |
                                       v
                      +----------------+----------------+
                      | FastAPI Backend (Thiramai API) |
                      | Auth, RBAC, Brain, Business OS |
                      +----+----------------------+-----+
                           |                      |
                           v                      v
                +----------+----------+   +------+------+
                | PostgreSQL 16       |   | Redis       |
                | Business + Audit DB |   | Cache/Queue |
                +----------+----------+   +------+------+
                           |                      |
                           +----------+-----------+
                                      |
                                      v
                          +-----------+-----------+
                          | Workers / Schedulers  |
                          | Alerts, Jobs, Autonomy|
                          +-----------+-----------+
                                      |
                                      v
                          +-----------+-----------+
                          | AI Providers          |
                          | Groq + Tavily         |
                          +-----------------------+
```

## 📊 Feature Status
| Feature | Status | Expected |
|---------|--------|----------|
| Command Center | ✅ Live | - |
| Control Center | ✅ Live | - |
| Inventory | ✅ Live | - |
| Billing | ✅ Live | - |
| Production | ✅ Live | - |
| Personal OS | ✅ Live | - |
| Stock Watchlist | ✅ Live | - |
| Research | ✅ Live | - |
| Analytics | 🔜 Coming | Q2 2026 |
| GST Filing | 🔜 Coming | Q3 2026 |
| Payroll | 🔜 Coming | Q3 2026 |
| Reports | 🔜 Coming | Q2 2026 |
| Settings | 🔜 Coming | Q2 2026 |

## 🔒 Security
- JWT authentication
- Role-based access control (RBAC)
- Tiered rate limiting + IP violation controls
- Security audit logging
- Dangerous endpoint blocking in production

## 🛠️ Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Python 3.12 |
| Database | PostgreSQL 16 |
| Cache | Redis |
| Frontend | React + Vite |
| AI | Groq (Llama) + Tavily |
| Deploy | Docker + Nginx |
| Server | DigitalOcean Ubuntu 24 |

## 🧠 Decision Brain — PolicyEngine A/B Migration (Week 2)

Thiramai is migrating decision-making from a Groq-only LLM brain to a contextual-bandit `PolicyEngine`. The migration is gated by an A/B test so the cutover is reversible.

| Module | Purpose |
|--------|---------|
| `services/policy_engine.py` | Central decision engine: LinUCB contextual bandit on top of `services/world_model/bayesian_world_model.py`. |
| `services/decision_brain_v2.py` | Async wrapper that A/B-routes between PolicyEngine and the legacy `services/decision_brain.run_decision_engine_sync`. |
| `services/observability/ab_test_metrics.py` | Read-only reporter over `learning_logs` rows tagged `source_type='policy_engine' \| 'legacy_brain'`. |
| `scripts/migrate_decision_brain.py` | Operator runbook: print A/B report, gated phase ramp, dotenv writer. |
| `tests/test_policy_engine.py`, `tests/test_decision_brain_v2.py` | Engine + migration tests (run via the standard `pytest tests/`). |

A/B traffic is controlled by two env vars (documented in `.env.example`):

```env
THIRAMAI_DECISION_AB_TEST=true   # alias: DECISION_AB_TEST
THIRAMAI_POLICY_ENGINE_PCT=50    # alias: POLICY_ENGINE_PCT
```

Operator runbook (run on the production host inside the deployed container):

```bash
# Inspect the last 7 days of A/B metrics
python scripts/migrate_decision_brain.py --check-metrics --days 7

# Phase 1 — enable 50/50 routing and write the values into the prod env file
python scripts/migrate_decision_brain.py --phase1 --apply-env-file .env.production

# Phase 2 — ramp PolicyEngine to 75% (gated on >=100 samples/variant + lift)
python scripts/migrate_decision_brain.py --phase2 --apply-env-file .env.production

# Phase 3 — full cutover, A/B disabled
python scripts/migrate_decision_brain.py --phase3 --apply-env-file .env.production
```

Production deploy itself remains unchanged — `.github/workflows/deploy.yml` builds an immutable image, pushes to GHCR, and SSHes into the host to run `scripts/pre_deploy_check.sh` → `scripts/deploy_production.sh` → `scripts/rollback.sh` on failure. After applying a phase change, restart the API + workers so the new env values take effect.

## 📦 Quick Deploy
```bash
cd /root/thiramai-app
git pull origin main
docker compose -f docker-compose.production.yml --env-file .env.production up -d --force-recreate --build web
sleep 30
docker exec thiramai-app-web-1 alembic upgrade head
bash scripts/post_deploy_check.sh
```

For full deployment and operations guidance, see `docs/DEPLOYMENT.md` and API details in `docs/API_REFERENCE.md`.
