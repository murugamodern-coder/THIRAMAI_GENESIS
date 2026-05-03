# THIRAMAI GENESIS — CTO-LEVEL AUDIT REPORT

- **Date:** May 03, 2026
- **Auditor:** AI code analysis, with live verification against the running stack on this machine
- **Scope:** Full backend (FastAPI + SQLAlchemy + Alembic + Postgres + Redis), frontend (`web/command_center` Vite/React), tests, security, infrastructure, AI / autonomy, documentation
- **Method:** Static analysis with file/line citations, plus runtime probes against the production compose stack (`/health/*`, login, `/chat/decision`, Postgres, container env)

---

## EXECUTIVE SUMMARY

**Overall verdict: CONDITIONALLY READY for staged production rollout to a single-tenant or pilot deployment. NOT READY as advertised for a multi-tenant SaaS until the RLS / connection-role issue is fixed.**

The platform is **substantially built** — modern Python 3.12 stack, FastAPI 0.135, SQLAlchemy 2.x typed models, Alembic migrations with RLS policies, structured logging, security middleware, JWT + refresh tokens, RBAC, a proper PolicyEngine wrapped with a circuit breaker, in-process AI quality drift tracking, Prometheus metrics, runbooks, CI with security scans (Bandit/Trivy/Semgrep + pip-audit), and a Vite-built React Command Center.

End-to-end live verification on this machine shows: `/health/ready` returns **200 `ready`** at Alembic head **`0078_add_ai_decisions_table`**; login → `POST /chat/decision` succeeds end-to-end and persists to `ai_decisions` with **`decision_brain_source: policy_engine`**. The decision pipeline is functioning.

**Critical issues that block "Fortune 500 multi-tenant SaaS" framing today:**
1. **RLS tenant isolation is effectively disabled in the running web container.** The web service connects as the **`thiramai`** Postgres role, which the migrations grant `superuser_bypass USING (true)`. Combined with a separate bug (`SET LOCAL row_security = force` is rejected by PostgreSQL — `force` is not a valid boolean) whose exception is silently swallowed in `core/database.py`, the database-enforced multi-tenant guarantee is **in name only**. App-level `WHERE organization_id = …` is the actual barrier.
2. **Auth has no account lockout / progressive backoff.** Token version (`tv`) claim is issued but **not enforced on decode**; refresh-token revocation works but JWT revocation does not.
3. **Coverage gate** is split off from main CI (`test-coverage.yml`); main `ci.yml` does not enforce overall coverage. Critical paths like `services/execution_decision_engine.py` carry an explicit minimum of **7%**.
4. **Documentation is broad but fragmented.** `CHANGELOG.md` has only a single 1.0.0 entry; no `CONTRIBUTING.md`; ERD/schema doc absent; some deployment docs (e.g. `TROUBLESHOOTING.md`) are short.
5. **Frontend has no TypeScript and a single Node-test file** — production-grade UI quality bars (a11y, focus traps, axe CI, Prettier, broader unit/E2E) are not met.

**Strengths that exceed typical SMB-grade work:**
- Clean SQLAlchemy 2.x model surface, Alembic discipline (78 revisions, `core/migration_head.py` pinned), RLS scaffolding present, server-side correlation IDs.
- Real circuit breaker and safe-fallback path around the PolicyEngine; AI quality tracker; Prometheus instrumentation.
- 17 categorized runbooks, Grafana dashboards, alert + recording rules, secrets-manager abstraction with rotation workflow.
- Phase-3 `ai_decisions` (HITL approval) wired end-to-end, Phase-4 self-evolution scaffolding (architecture proposals, Bayesian world model, self-coder) is not orphan code — services and APIs reference it.

---

## 1. ARCHITECTURE QUALITY
**Score: 78 / 100**

### Strengths
- **Clear-ish layering:** `api/routes/*` → `services/*` → `core/db/models.py` (SQLAlchemy) → Alembic (`alembic/versions/`).
- **Centralized config** in `core/settings.py` using **Pydantic Settings** (`AliasChoices`, `field_validator`, computed `trusted_proxy_ips`).
- **Connection pooling** wired from settings to engine factory (`core/database.py:196` onward — `POOL_SIZE`, `MAX_OVERFLOW`, `POOL_TIMEOUT`, `POOL_RECYCLE`, `POOL_PRE_PING`).
- **Tenant-scope hooks**: contextvar `set_current_org_id` + per-session `_apply_session_rls_context` (`core/database.py:45-64`), even if the `force` value is wrong (see §8).
- **Circuit breaker** around PolicyEngine: `services/policy_engine_wrapper.py:62-193`.
- **Health probes** are detailed and correctly differentiate liveness/readiness/metrics: `api/routes/health.py:285-489`.
- **78 Alembic migrations** with explicit head pinning in `core/migration_head.py`.

### Issues
- **`app.py` god-module.** Middleware stack, exception handlers, Sentry init, schedulers, RBAC seeding, `/metrics` mount, static SPA mount, deep-health endpoints, auto-deploy hooks all live in one file (`app.py:129-602`). Hard to test, hard to review.
- **`core/db/models.py` is monolithic** at ~5,017 lines and ~100 mapped tables. SQLAlchemy 2.x typed style is fine; size is the problem.
- **Mixed config sources:** JWT secrets/TTL still read via `os.getenv` in `core/auth.py` while everything else is in `ThiramaiSettings`. This bypasses the secrets-manager bridge in `get_secret_or_env`.
- **Legacy lifecycle:** uses `@app.on_event("startup")` / `"shutdown"` rather than a single `lifespan` context manager. FastAPI deprecation path.
- **Service layer god-files:** `services/dashboard_command_executor.py` (~1,200+ lines).
- **Two fetch paths in frontend:** axios for most calls plus a raw `fetch` in `VoiceButton.jsx` — minor inconsistency.

### Recommendations
1. Split `app.py` into `app_factory.py` (FastAPI build), `middleware.py`, `exception_handlers.py`, `lifecycle.py`.
2. Split `core/db/models.py` into `core/db/models/{auth,inventory,billing,ai,...}.py` — Alembic auto-detection unaffected.
3. Move JWT secret/TTL reads into `ThiramaiSettings` and route through `get_secret_or_env`.
4. Migrate to FastAPI `lifespan`.

---

## 2. CODE QUALITY
**Score: 76 / 100**

### Standards Compliance
- **PEP 8 / Ruff / Bandit:** CI enforces **Bandit** with a `gate_bandit.py` script and **Semgrep** rules (`.github/workflows/ci.yml`). PEP 8 is not formally gated (no flake8/ruff config in CI here), but code generally follows it.
- **Type hints:** Settings, routes, services use type hints heavily. SQLAlchemy 2.x `Mapped[]` / `mapped_column` throughout `core/db/models.py:33-74`.
- **Documentation:** Reasonable module/function docstrings on the surfaces audited (e.g. `services/approval_service.py`, `core/auth.py`, `services/policy_engine_wrapper.py`).
- **Code complexity:** Several modules are oversized (see §1).

### Security analysis
- **SQL injection:** Mostly safe — ORM-first, parameterized `text()` with bind params (`core/database.py:61-63`). Migrations use f-strings for **identifier** interpolation from a controlled list (`alembic/versions/0047_add_rls_tenant_isolation.py:95-112`) — acceptable.
- **XSS:** Backend serves JSON; React (`web/command_center`) uses framework defaults. CSP set by `core/security_middleware.py:66-115`.
- **Authentication:** **Strong baseline** — `bcrypt` passwords (`core/auth.py`), HS256 JWT with optional `iss`/`aud`, opaque refresh tokens hashed at rest (`services/refresh_token_service.py`).
- **Authorization:** **Implemented** — `require_permission`, `require_roles`, `require_staff`, `core/decision_rbac.py` for AI actions. `~40+ require_permission` references in `api/routes/`.

### Performance
- **Database:** `POOL_SIZE=20`, `MAX_OVERFLOW=40` defaults; pool checkout/checkin instrumentation (`core/database.py:98-161`).
- **API response times:** Live `/health/ready` round-trip under ~50 ms locally; `/chat/decision` round-trip ~400-800 ms with PolicyEngine on warm path (locally).
- **Caching:** Redis used for distributed rate-limit (`core/distributed_rate_limit.py`), permission cache (`core/permission_engine.py:14-15`), worker heartbeats. HTTP-level caching is mostly client-side (Vite cache busting + service worker).

---

## 3. FUNCTIONALITY AUDIT
**Score: 80 / 100**

### Working features (live-verified on this machine)
- ✅ `GET /health/live` → `{"status":"alive"}`
- ✅ `GET /health/ready` → 200 `ready`, `alembic` at `0078_add_ai_decisions_table`
- ✅ `POST /auth/login` → returns JWT
- ✅ `POST /chat/decision` → 200, persists row in `ai_decisions` (decision_id 6 in last test), `decision_brain_source: policy_engine`, requires_approval pending
- ✅ Alembic upgrade head succeeded (idempotent 0078 handles pre-existing table)
- ✅ Circuit breaker wires `PolicyEngineCircuitBreaker.call` around `engine.decide` (`services/policy_engine_wrapper.py:216-223`)
- ✅ Phase-3 HITL: `services/approval_service.insert_ai_decision` / `list_pending_ai_decisions` / `update_ai_decision_status` paths
- ✅ Prometheus metrics catalogue: `services/observability/decision_metrics.py:93-169`

### Gaps / not fully functional
- ❌ **`_bundle_from_decision_brain_v2` only maps `analyze`/`monitor`/`alert`/`no_action`** to executor verbs — it always sets `requires_approval=True` (`api/routes/ai_chat.py:107-115`). Successful PolicyEngine decisions cannot auto-execute through `/chat/decision` without HITL today. That may be intentional, but the README narrative ("100% PolicyEngine, no human-in-loop bottleneck") oversells current behavior.
- ❌ **Voice input** is browser-side only (`VoiceButton.jsx`, `GlobalCommandBar.jsx` Web Speech API). No server-side ASR; no Tanglish-specific recognizer.
- ❌ **Tamil/Tanglish output**: there is a `tamil_watch` policy and a `repair_tamil_and_fluff` post-processor (`core/orchestrator.py`, `core/policies/loader.py`), but no string catalog or i18n library.
- ❌ **Service worker / PWA install** is shipped (`static/command_center/sw.js`) but offline behavior for the API is undocumented.

### Bugs found

#### Critical (P0)
1. **RLS tenant isolation is effectively disabled in production**
   - **Location:** `core/database.py:55` (`SET LOCAL row_security = force`); `alembic/versions/0047_add_rls_tenant_isolation.py:107-112` (`superuser_bypass TO {bypass_role}`).
   - **Evidence:** Live probe — `SET row_security = force;` returns `ERROR: parameter "row_security" requires a Boolean value`. Web container connects as `thiramai`. `pg_policy` shows `superuser_bypass {thiramai}` on `ai_decisions`. Web env has no `THIRAMAI_RLS_BYPASS`, but `superuser_bypass` is unconditional `USING (true)`.
   - **Impact:** Any single missing `WHERE organization_id = …` clause → cross-tenant data leakage. Database-level isolation is not active for the API connection.
   - **Fix:**
     - Use a **dedicated app role** (e.g. `thiramai_app`) for the API — grant DML on tenant tables but **do not** include it in the `superuser_bypass` policy. Migrations / admin tasks continue to use `thiramai`.
     - Replace `SET LOCAL row_security = force` with `SET LOCAL row_security = on` (PostgreSQL only accepts `on`/`off` for this GUC; the table-level `FORCE ROW LEVEL SECURITY` from the migration already gives the intended "always-on for table owners" semantics).
     - Remove the bare `except Exception: return` in `_session_after_begin_set_rls` so RLS configuration failures fail fast, not silently.

#### High (P1)
2. **JWT `tv` (token version) claim is set but not validated.** Comment in `core/auth.py` calls it "future"; `decode_access_token` does not check it. Refreshing access tokens can re-issue with new TTL but old access tokens remain valid until `exp`.
3. **No login lockout / CAPTCHA / progressive delay.** Bcrypt + per-IP rate limit (`THIRAMAI_RL_AUTH_PER_MINUTE`) is the only barrier (`core/rate_limit_middleware.py:140-160`).
4. **Default integration Fernet key** falls back to literal `"dev-unsafe-thiramai-integration"` if `THIRAMAI_INTEGRATION_FERNET_KEY` and `SECRET_KEY` are both absent (`services/integration_crypto.py:12-21`). Production startup should refuse to boot without an explicit key.
5. **`THIRAMAI_PROXY_TRUSTED_HOSTS=*`** in `.env.production.example` line 72. Combined with `THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1`, this means any client-supplied `X-Forwarded-For` is trusted unless the operator narrows it.
6. **`docker compose restart web` does not reload `.env.production`.** Operationally caused two near-misses in this audit session. Documented now in `docs/deployment/QUICK_START.md`, but a defensive guard or a `make reload-env` would help.

#### Medium (P2)
7. **`_bundle_from_decision_brain_v2` always forces `requires_approval=True`** (`api/routes/ai_chat.py:107-115`). README implies autonomous execution.
8. **`THIRAMAI_SAFE_ERRORS=1` masks 5xx detail.** Good for prod, but combined with a 500 it forced operators to read container logs to diagnose the previous DB-schema bug. A `THIRAMAI_TRACE_HEADER` toggle for authenticated admin tokens would help.
9. **`/metrics` exposure is inverted from typical practice** — only mounted in non-production unless `THIRAMAI_EXPOSE_PUBLIC_METRICS=1` (`app.py:149-155`). Prometheus scrape paths must be planned (sidecar or env flag).
10. **`docker-compose.production.yml` has no CPU/memory `deploy.resources` limits**. A runaway worker can starve `web`.

#### Low (P3)
11. **Worker service naming differs**: `worker` (dev `docker-compose.yml`) vs `worker-alerts` (prod). Easy to confuse runbook commands.
12. **Coverage gate split.** `ci.yml` runs `pytest -q` only; `test-coverage.yml` enforces critical-path floors. PRs that fail to update coverage in main CI may still merge.
13. **Frontend `rbac-ui.test.mjs`** runs via `node:test`; not wired into `ci.yml` (only `npm run build` is run).
14. **`CHANGELOG.md`** is static at `[1.0.0] - April 2026`. No incremental entries.

---

## 4. UI / UX ASSESSMENT
**Score: 65 / 100**

### Desktop experience
- **Layout:** React + Tailwind 4 + custom design tokens (`web/command_center/src/design-system/`, `cc-theme.css`). `ShellLayout.jsx`, `BusinessShellLayout.jsx`, `PersonalShellLayout.jsx` are clean shells.
- **Navigation:** **HashRouter** (`main.jsx`) — works behind any host, but kills SEO and breaks deep-link sharing for SSR/CDN scenarios.
- **Responsiveness:** Tailwind breakpoints in shells (`md:hidden`, `md:translate-x-0`); media queries in `cc-theme.css`; `prefers-reduced-motion` honored.

### Mobile compatibility
- **Responsive design:** Yes (Tailwind utility classes + sidebar off-canvas on `md:` breakpoint).
- **Touch optimization:** Partial — most controls are large enough; not measured.
- **Mobile-first:** No — desktop-first patterns, with mobile overrides.

### Accessibility
- **Keyboard navigation:** Modal `role="dialog"` + Escape close (`Modal.jsx:7-22`); skip link `#cc-main-content` in `main.jsx`.
- **Screen reader:** Some `aria-label`/`aria-expanded`/`aria-selected` (e.g. `ShellLayout.jsx:174-202`, `AgenticOSPage.jsx`).
- **WCAG:** **No automated a11y test in CI.** No axe / Pa11y / Storybook a11y addon evidenced.
- **Focus management:** `Modal.jsx` lacks an explicit focus trap.

### Other
- **No TypeScript.** `package.json` lints `js,jsx` only.
- **No React Query / SWR.** Manual `useEffect` + axios.
- **No Prettier config in `web/command_center/`**.
- **One frontend test file** (`tests/rbac-ui.test.mjs`) and not wired into CI.

---

## 5. PRODUCTION READINESS
**Score: 74 / 100**

### Deployment
- **Containerization:** Multi-stage Dockerfile, non-root `appuser`, HTTP healthcheck, builder/frontend/runtime stages. `Dockerfile:18-122`.
- **Compose stacks:** `docker-compose.production.yml` includes `db`, `redis`, `web`, `worker-jobs`, `worker-alerts`, log rotation `json-file` `max-size 10–50m max-file 3–5`.
- **Loopback bind:** `web` published on `127.0.0.1:${WEB_PORT:-8000}:8000` — good default; assumes a reverse proxy.
- **Secrets:** `core/secrets_manager.py` supports `environment | aws | vault | gcp`. Rotation workflow `.github/workflows/rotate-secrets.yml` runs monthly dry-run.

### Monitoring
- **Health checks:** `/health`, `/health/live`, `/health/ready`, `/health/metrics`, `/health/system`, `/health/stocks`. `api/routes/health.py:285-489`.
- **Logging:** `THIRAMAI_LOG_JSON=1` in production; correlation IDs propagated; Bandit/Semgrep in CI.
- **Metrics:** Prometheus catalogue in `services/observability/decision_metrics.py` and `business_metrics.py`. Grafana dashboards: 12 JSON files. Prometheus alert + recording rules: 2 files.
- **SLOs:** `monitoring/slos/slo-definitions.yml`, `monitoring/alerts/slo_alerts.yml`, `docs/operations/slo-management.md`.

### Reliability
- **Error handling:** Pydantic validation, typed exceptions (`ThiramaiAppError`), safe-error masking.
- **Circuit breakers:** PolicyEngine wrapper.
- **Graceful degradation:** `safe_fallback` path on PolicyEngine failure; `decision_brain_source: safe_fallback` returned.
- **Rate limiting:** `core/rate_limit_middleware.py` tiered per-prefix; optional Redis global cap.

### Documentation
- **Setup guide:** `README.md` + `docs/deployment/QUICK_START.md` are strong.
- **API docs:** `docs/API_REFERENCE.md` is a hand-curated summary (~119 lines) — incomplete vs auto-generated OpenAPI.
- **Runbooks:** 14 scenario runbooks + index + template (`docs/runbooks/`).

### Gaps
- No CPU/memory `deploy.resources` in compose.
- No automated DR drill / restore-from-backup script (only `scripts/backup_before_reset.sh`).
- `docker compose build` in `deploy.yml` does not reuse Buildx GHA cache that `ci.yml` builds.
- `/metrics` mount inverted vs common practice.

---

## 6. TECHNOLOGY ASSESSMENT
**Score: 82 / 100**

### Stack modernity (2026 standards)
- **Python 3.12.9** (slim-bookworm). Current LTS-ish.
- **FastAPI 0.135.3** — current.
- **SQLAlchemy 2.0.49** — current major.
- **Pydantic Settings 2.13** — current.
- **psycopg2** (sync) — would migrate to `psycopg3` over time but not blocking.
- **python-jose 3.5** + **cryptography 46** — pinned for compatibility (note in `requirements-base.txt`).
- **Redis 7** + **Postgres 16-alpine** — current.
- **Node 20 / Vite 5 / React 18 / Tailwind 4** — current. **No TypeScript** is the main gap.

### Future-proofing
- **Maintainability:** Medium — model and app god-files are friction; otherwise typed and modular.
- **Extensibility:** Easy on routes/services; harder on models due to monolith.
- **Scalability:** Horizontal — Gunicorn + Uvicorn workers, `THIRAMAI_JOB_QUEUE=db` → external worker. Some per-process state (in-memory AI quality tracker) reduces multi-worker coherence; documented as such.

---

## 7. AI & AUTONOMY
**Score: 78 / 100**

### Capabilities
- **PolicyEngine:** `services/policy_engine.py` — bandit-style action registry (`_DEFAULT_ACTION_REGISTRY`, lines 283-404) per intent (trading/business/personal/system).
- **Decision flow:** `services/decision_brain_v2.py` (A/B `THIRAMAI_DECISION_AB_TEST`, `THIRAMAI_POLICY_ENGINE_PCT`), policy / safe-fallback / legacy three-way, `record_outcome` updates bandit when source is `policy_engine`.
- **Quality tracking:** `services/ai_quality_tracker.py` (rolling window, drift, low-confidence, anomalies). **Per-process in-memory** — multi-worker coherence is approximate (documented).
- **Prometheus:** `thiramai_decision_route_total`, `thiramai_policy_engine_circuit_state`, `thiramai_safe_fallback_decisions_total`, `thiramai_ai_quality_anomalies_total`, etc.

### Natural language support
- **English:** Full.
- **Tamil:** Partial — `tamil_watch` repair (`core/orchestrator.py`), Jarvis force-language flag (`THIRAMAI_JARVIS_TAMIL_FORCE`), Unicode detection.
- **Tanglish:** Documented intent in `api/routes/os_central_brain.py` (lines ~35-44). No string catalog.
- **Voice input:** Client-side Web Speech API only (`VoiceButton.jsx`, `GlobalCommandBar.jsx`). No server ASR pipeline.

### Self-improvement
- **Auto-recovery:** Circuit breaker + safe fallback yes; auto-restart of containers via Docker `restart: unless-stopped`.
- **Self-configuration:** Schedulers (`services/scheduler.py`) drive `auto_propose_loop`, `self_evolution_trigger_cron`. **Gated** by feature flags + owner permissions.
- **Code generation:** `services/self_coder_agent.py` exists with `POST /self-coder/run` (kernel-microkernel route) — gated by `self_coder_enabled()`.
- **Honest framing:** Phase-4 self-evolution is **wired but governed** (HITL + flags + scheduler), not "lights-out closed-loop autonomous".

### Provider integrations
- **Groq + Tavily** abstraction in `services/llm/local_llama.py` (`groq_available`, `tavily_available`, `chat_groq`, `research_query`) and `core/search_pipeline.py`. Failover from Tavily → Groq-only synthesis exists; cross-LLM failover not uniform.
- **`/chat`** enforces presence of GROQ + TAVILY (`api/routes/ai_chat.py:219-223`); **`/chat/decision`** does not (PolicyEngine path can run without LLM keys).

---

## 8. SECURITY AUDIT
**Score: 70 / 100**

### Findings (Risk levels)

| Area | Risk | Notes |
|------|------|-------|
| AuthN (bcrypt, refresh, HS256) | Medium | No lockout; `tv` not enforced; `JWT_EXPIRE_MINUTES=1440` in example vs prod-enforced ≤60 (`core/production_safety.py:46-62`) |
| AuthZ / RBAC | Low–Medium | `require_permission` + DB perms; route coverage manual |
| **RLS** (`row_security=force` + `superuser_bypass{thiramai}`) | **High** | **DB-level isolation is not active for the API role on this deployment** (live-verified). |
| SQL injection | Low | Parameterized; identifier f-strings in migrations from controlled lists |
| CORS / Headers | Medium | CSP/COOP/COEP set; HSTS at edge only; example `THIRAMAI_PROXY_TRUSTED_HOSTS=*` |
| Rate limiting | Low–Medium | Tiered + optional Redis global cap |
| Secrets | Low | Multi-backend manager + monthly rotation workflow |
| Cookies | Low | `SecureCookieEnforcementMiddleware` adds Secure/HttpOnly/SameSite |
| Input validation | Medium | Pydantic + `sanitize_user_text` on AI routes |
| Audit logs | Low | `system_audit_logs` + `security_audit_logs` |
| Dependencies | Medium | `pip-audit` workflow gates High/Critical CVSS; ongoing posture |
| Encryption | Medium | `services/integration_crypto.py:12-21` falls back to dev-unsafe constant |
| **PII / GDPR** | **High (completeness)** | No erasure / consent / export endpoints found |
| Pitfalls | Medium | `/metrics` flag inversion, proxy trust, env-example drift |

### Compliance
- **GDPR readiness:** Not ready — no DSAR / export / erasure / consent endpoints; no DPA template referenced.
- **Data encryption:** TLS expected at edge (`deploy/nginx`); at rest is the responsibility of the Postgres host. Application-layer Fernet for integration tokens / vault items is present.
- **Audit logging:** Comprehensive but retention/access-control on the audit tables themselves is not codified.

---

## 9. TEST COVERAGE
**Score: 72 / 100**

- **~117 unique test modules** under `tests/` and **1 integration module** (`tests/integration/test_e2e_decision_flow.py`).
- **`pytest.ini`:** `testpaths = tests`, `--import-mode=importlib --capture=no --durations=10`. Coverage opt-in.
- **`.coveragerc`:** `branch=True`, `dynamic_context=test_function`, source `core,services,api,workers`.
- **Critical-path floor script:** `scripts/check_critical_coverage.py` documents `services/execution_decision_engine.py` ≥7%, `api/routes/auth.py` ≥39%, `core/security_middleware.py` ≥44%, `core/database.py` ≥43%. **These accept known thin coverage**.
- **Coverage JSON not committed** (CI artifact). Live overall % is N/A from the workspace alone.
- **CI:** `ci.yml` runs unit tests + Bandit + Semgrep + Trivy + npm build. `test-coverage.yml` enforces branch coverage + critical-path floors and posts PR comment with `MINIMUM_GREEN=85 / ORANGE=75`.
- **Frontend tests:** **One file**, not wired into CI.

### Gaps
- PolicyEngine circuit breaker is **unit-tested** (`tests/test_policy_engine_circuit.py`) but not exercised through HTTP failure injection.
- Trusted-proxy header trust at the middleware level not asserted end-to-end.
- No E2E / Playwright tests for the Command Center UI.
- No load tests run in CI (a `locustfile.py` exists at repo root but no scheduled run).

---

## 10. BUGS & TECHNICAL DEBT

### Critical (P0)
1. **RLS bypass on the API connection role + invalid `row_security = force` statement.** Fix: dedicated low-priv app role, replace `force` with `on`, remove bare-except in `_session_after_begin_set_rls`. (See §3 P0.)

### High (P1)
2. JWT `tv` not enforced on decode → no fast revocation channel for access tokens.
3. No login lockout / CAPTCHA / progressive backoff.
4. `services/integration_crypto.py:12-21` falls back to `"dev-unsafe-thiramai-integration"` if both env vars empty → fail startup instead.
5. `.env.production.example`: `THIRAMAI_PROXY_TRUSTED_HOSTS=*` and `JWT_EXPIRE_MINUTES=1440`. Update to `JWT_ACCESS_EXPIRE_MINUTES=60` and a narrowed proxy host comment.
6. `docker compose restart` lore: documented but a `make` target / wrapper would prevent operator confusion.

### Medium (P2)
7. `_bundle_from_decision_brain_v2` forces `requires_approval=True` regardless of PolicyEngine outcome (`api/routes/ai_chat.py:107-115`). Decide whether autonomous execution is in or out of the v1 contract.
8. `/metrics` exposure inverted vs convention (only outside production unless flag).
9. Compose: no CPU/memory limits on `web` / workers.
10. Coverage gate split from main CI; merge can pass with no coverage delta.
11. Worker service name drift `worker` vs `worker-alerts` between dev and prod.

### Low (P3)
12. `app.py` god-module; `core/db/models.py` ~5,000 lines; `services/dashboard_command_executor.py` ~1,200 lines.
13. Frontend `rbac-ui.test.mjs` not run in CI; no Prettier; no TypeScript; HashRouter SEO trade-off.
14. `CHANGELOG.md` static; no `CONTRIBUTING.md`; no ERD; no living architecture diagram (only an ASCII README block + `CENTRAL_BRAIN_OS_ARCHITECTURE.md`).

### Technical debt
- `static/` and `templates/` contain **legacy HTML** alongside the React build. Decide and remove or archive.
- Two fetch paths in the frontend (axios + raw `fetch` in voice).
- Per-process AI quality tracker has multi-worker drift; either accept (documented) or back it with Redis.
- Inline / SQLite goal queue and the Postgres `background_jobs` queue are two different mechanisms — pick one for v2.

---

## OVERALL SCORES

| Category | Score | Status |
|----------|-------|--------|
| Architecture | 78/100 | ⭐⭐⭐⭐ |
| Code Quality | 76/100 | ⭐⭐⭐⭐ |
| Functionality | 80/100 | ⭐⭐⭐⭐ |
| UI/UX | 65/100 | ⭐⭐⭐ |
| Production Ready | 74/100 | ⭐⭐⭐⭐ |
| Technology | 82/100 | ⭐⭐⭐⭐ |
| AI/Autonomy | 78/100 | ⭐⭐⭐⭐ |
| Security | 70/100 | ⭐⭐⭐ |
| Testing | 72/100 | ⭐⭐⭐⭐ |
| **WEIGHTED TOTAL** | **75 / 100** | ⭐⭐⭐⭐ |

Weighting used: Architecture 12, Code 10, Functionality 14, UI/UX 8, Production 14, Tech 8, AI 12, Security 14, Testing 8.

---

## FINAL VERDICT

**Production readiness: CONDITIONALLY READY.**

### Can deploy to production?
**Yes — for a single-tenant pilot or internal SaaS to a known cohort, after the P0 RLS fix and the P1 auth/secret-key items.** The decision pipeline, health probes, observability, and HITL approval flow work end-to-end on this machine.

**No — not yet for an open multi-tenant SaaS** advertised as DB-enforced isolation, until the API connects with a non-bypass Postgres role and `row_security = on` is applied correctly.

### Recommended actions before launch
1. **P0 (blocker):** Create a dedicated `thiramai_app` Postgres role; grant DML on tenant tables; do **not** include it in `superuser_bypass`. Migrate web/worker to use it. Replace `SET LOCAL row_security = force` → `on` in `core/database.py`. Remove bare-except in `_session_after_begin_set_rls`. Add an integration test that proves cross-org reads are blocked.
2. **P1:** Enforce JWT `tv` on decode, add login lockout / progressive backoff, fail startup if `THIRAMAI_INTEGRATION_FERNET_KEY` and `SECRET_KEY` are both empty, fix `.env.production.example` (`JWT_ACCESS_EXPIRE_MINUTES=60`, narrowed proxy hosts).
3. **P1:** Add data-subject endpoints for GDPR (export / erase) or document the legal basis & manual process if not in scope.
4. **P2:** Decide policy on `requires_approval` for PolicyEngine outputs; remove the unconditional `True`.
5. **P2:** Move coverage gate into `ci.yml` (or make `test-coverage.yml` required on PRs).
6. **P3:** Split `app.py` and `core/db/models.py`; switch to FastAPI `lifespan`; introduce TypeScript or at least JSDoc + Prettier in `web/command_center`.

### International standards compliance
- **Industry best practices:** Mostly. JWT, bcrypt, Pydantic, Alembic, RLS scaffolding, Prometheus, structured logging, multi-stage Docker, runbooks. Gaps in lockout, GDPR DSAR endpoints, formal a11y testing.
- **Enterprise-grade:** Conditional. With the P0 fix, **single-customer enterprise** is plausible. Multi-tenant SaaS for regulated buyers (FSI / health) requires the RLS fix, GDPR endpoints, and a SOC2-style change-management trail.
- **Fortune 500 ready:** No, not yet. The Fortune 500 bar means data-subject programs, formal SLAs, third-party penetration test reports, full audit-log retention policy, RTO/RPO drills. Some scaffolding exists; the program is not.

---

## USAGE SCENARIOS

### What this system does well
- Phase-3 HITL approval pipeline (PolicyEngine → safe fallback → audited DB row)
- Operator ergonomics: health probes, runbooks, secrets rotation, structured logs, Grafana dashboards
- Tenant- and role-aware data model with broad migration coverage (78 revisions)
- Resilience patterns (circuit breaker, safe fallback, rate limiting, correlation IDs)

### What needs improvement
- True DB-enforced multi-tenancy (RLS + non-bypass app role)
- Auth hardening (lockout, JWT revocation)
- Frontend rigor (TypeScript, axe, focus management, broader tests)
- Documentation parity with code (living changelog, ERD, API reference parity)

### Best use cases
- Pilot / internal AI-driven decision platform with HITL approval
- SMB / single-tenant deployments with one-org per database
- Internal experimentation on PolicyEngine + bandit-style learning loops

### Not recommended for
- Open multi-tenant SaaS with cross-customer data on the same DB until the RLS fix lands
- Regulated workloads (HIPAA / SOX / RBI sensitive financial) without the security and DR work in §8 / §10

---

## PLATFORM COMPATIBILITY

- ✅ Desktop (Windows / macOS / Linux): Yes (browser app)
- ✅ Tablet: Partial — Tailwind responsive shells; no measured tablet QA
- ✅ Mobile (iOS / Android): Partial — responsive UI but desktop-first; voice features depend on browser Web Speech support
- ✅ Browsers: Modern evergreen (Chrome / Edge / Firefox / Safari recent). Service worker requires HTTPS in production.

---

## CONCLUSION

This is a **substantively built, opinionated AI-decision platform** with real production patterns, not a demo. It earns a confident **75 / 100**: the code, infra and AI plumbing are well past prototype. It falls short of an unconditional production sign-off on three axes — DB-level multi-tenant isolation, auth-attack hardening, and GDPR-style compliance plumbing.

Fix the **P0 RLS issue**, ship the **P1 auth/secret-key items**, narrow the **`.env.production.example`** defaults, and this is a credible single-tenant or pilot launch. Treat the **P2 / P3 list** as the next two-sprint backlog and the system moves toward enterprise SaaS posture.

---

## APPENDIX: KEY FILE-LINE CITATIONS

- Middleware stack: `app.py:266-313`
- Exception handlers: `app.py:520-602`
- RLS session hook: `core/database.py:45-64, 240-250`
- RLS migration: `alembic/versions/0047_add_rls_tenant_isolation.py:95-112`
- RLS fix migration: `alembic/versions/0077_fix_rls_superuser_bypass_role.py`
- ai_decisions table migration: `alembic/versions/0078_add_ai_decisions_table.py`
- JWT issue: `core/auth.py:132-171`
- JWT prod-safety: `core/production_safety.py:46-62`
- Refresh tokens: `services/refresh_token_service.py`, `api/routes/auth.py:395-439`
- PolicyEngine circuit: `services/policy_engine_wrapper.py:62-193, 216-269`
- Decision brain V2: `services/decision_brain_v2.py:21-39, 183-217, 248-297`
- Decision endpoint: `api/routes/ai_chat.py:107-115, 219-223, 286-474`
- Decision RBAC: `core/decision_rbac.py:10-45`
- Decision safety: `core/decision_schema.py:143-203`
- Health endpoints: `api/routes/health.py:243-489`
- Approval persistence: `services/approval_service.py`
- Auto-action engine: `services/auto_action_engine.py:117-385`
- Self-coder gate: `services/self_coder_agent.py`, `api/routes/kernel_microkernel.py`
- AI quality tracker: `services/ai_quality_tracker.py:5-214`
- Decision metrics: `services/observability/decision_metrics.py:93-337`
- Integration crypto fallback: `services/integration_crypto.py:12-21`
- Settings: `core/settings.py:54-267`
- Critical coverage gate: `scripts/check_critical_coverage.py`
- Compose prod: `docker-compose.production.yml`
- Dockerfile: `Dockerfile:18-122`
