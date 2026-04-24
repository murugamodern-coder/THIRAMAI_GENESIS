"""
OpenAPI tag metadata and API description for ``/docs`` and ``/openapi.json``.

Referenced from ``app.FastAPI(..., openapi_tags=..., description=...)``.
"""

from __future__ import annotations

OPENAPI_DESCRIPTION = """
## THIRAMAI Genesis

Multi-tenant **Sovereign AI** backend: **JWT auth**, **RBAC** (owner → worker), **Groq + Tavily** council brain,
**PostgreSQL** for org-scoped ERP-style data, **human-in-the-loop** approvals for high-risk actions, and
**factory / vault** file indexing.

### Security model
- Send **Authorization: Bearer** (short-lived **access** token from **`POST /auth/login`**, **`POST /auth/register`**, or **`POST /auth/refresh`**) on protected routes. Store the opaque **refresh_token** securely; default access TTL is ~30 minutes (`JWT_ACCESS_EXPIRE_MINUTES` / legacy `JWT_EXPIRE_MINUTES`).
- With **Redis** (`REDIS_URL`), a **global** per-user (or per-IP) cap applies to most routes (`THIRAMAI_RL_GLOBAL_PER_MINUTE`, default **100**/min); `/auth/*` uses separate in-memory limits.
- **`organization_id`** is embedded in the JWT; list/detail queries for tenant data **must** filter by the caller's org (IDOR protection).
- **`/auth/*`** and **`GET /chat`** are **rate-limited** per client IP (see env `THIRAMAI_RL_*`).
- **`POST /chat/query`** requires a **valid, non-expired** Bearer JWT (middleware returns **401** if missing/expired/invalid) and is **rate-limited per user** (`THIRAMAI_RL_CHAT_QUERY_PER_USER_PER_MINUTE`, default **5**/min for testing).
- **Retail auto-sale** (`sell_stock` execution from chat): only roles listed in **`THIRAMAI_RETAIL_SALE_ROLES`** (default **`admin`**, **`staff`**) may trigger automatic sale execution; others get a narrative refusal.

### Static & dashboard
- **`GET /`** — Tailwind SPA (`static/index.html`); send **`Accept: application/json`** for liveness JSON.
- **`GET /public/...`** — static files from `static/` (see `main.py`).
- **`GET /dashboard`** — legacy HTML dashboard (root `index.html` if present).
- **`GET /static/factory/...`** — generated factory output (invoices, etc.).

### Production notes
- Set **`THIRAMAI_CORS_ORIGINS`** explicitly; do not use `*` in production.
- Set strong **`SECRET_KEY`** (or **`JWT_SECRET_KEY`**) and **`DATABASE_URL`** for real deployments.
""".strip()

# Tag "name" must match `tags=[...]` on routers and app-level routes.
OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": "System",
        "description": (
            "Discovery **`GET /health`**; liveness **`GET /health/live`**; readiness **`GET /health/ready`** (DB, Redis if set, Alembic, AI key presence, optional worker heartbeats). "
            "SPA **`GET /`**, static **`/dashboard`**, **`/script.js`**."
        ),
    },
    {
        "name": "Authentication",
        "description": (
            "Register organization + owner, OAuth2 password login, **`POST /auth/refresh`** (rotate access + refresh tokens), "
            "and **`GET /auth/me`**. **`/auth/*`** uses in-memory rate limits (`THIRAMAI_RL_AUTH_PER_MINUTE`)."
        ),
    },
    {
        "name": "Tenancy & organizations",
        "description": (
            "Phase 2 multi-business identity: **`GET /me/organizations`** lists memberships; "
            "**`POST /me/switch-organization/{org_id}`** issues a new JWT with updated **`active_org_id`**."
        ),
    },
    {
        "name": "AI & Council",
        "description": (
            "**`GET /chat`** — tenant-scoped chat UI helper; rate-limited per IP (`THIRAMAI_RL_CHAT_PER_MINUTE`). "
            "**`POST /chat/query`** — Groq + Tavily brain; **JWT required** (expiry enforced in middleware); "
            "**per-user** rate limit `THIRAMAI_RL_CHAT_QUERY_PER_USER_PER_MINUTE`. "
            "Retail **`sell_stock`** auto-execution is restricted to roles in `THIRAMAI_RETAIL_SALE_ROLES` (default admin, staff). "
            "Unless `THIRAMAI_AUTH_DISABLED=1` (dev only). "
            "Optional header **`X-Personal-Vault-Passphrase`** unlocks encrypted **Life OS** fields in the executive pack."
        ),
    },
    {
        "name": "Life OS",
        "description": (
            "**`GET /life/dashboard`** — today's habits, health metrics, open missions (executive vault JSON synced into Postgres). "
            "**`POST /life/habit/check-in`**, **`POST /life/mission`** (create or update via optional `mission_id`) — habits and personal goals. "
            "**`/life/vault/init`**, **`PUT /life/planner`**, **`POST /life/health`**, **`POST /life/reminders`** — "
            "planner, health logs, reminders; private text stored as **Fernet ciphertext** in PostgreSQL "
            "(key from user passphrase + PBKDF2; only a **verifier hash** is stored). Encrypted writes need "
            "**`X-Personal-Vault-Passphrase`**."
        ),
    },
    {
        "name": "Business OS",
        "description": (
            "Phase 4 operations depth: **`GET /business/snapshot`** (sales vs target, low stock, attendance, monthly margin), "
            "**`GET /business/economics/margin`**, department lead, **staff** profiles, **attendance** check-in/out, "
            "**`POST /business/expenses`**. Mutations are audited (`action=business_depth`) with **`X-Correlation-ID`**. "
            "Set **`THIRAMAI_DAILY_SALES_TARGET_INR`** for target comparison; inventory **`unit_cost_pre_tax`** feeds COGS."
        ),
    },
    {
        "name": "Compliance & Comms",
        "description": (
            "Phase 5: **`GET /compliance/daily-briefing`** (narrative + draft replies; seeds statutory **notifications**), "
            "**`GET /compliance/statutory-calendar`**. Email ingestion uses **`tools.email_reader`** tiers (🔴/🟠/🟡) + Groq when "
            "**`GROQ_API_KEY`** is set; 🟠 mail opens **compliance_cases**. Optional **`THIRAMAI_STATUTORY_RULES_JSON`** overrides default GST dates."
        ),
    },
    {
        "name": "Inventory & Assets",
        "description": "Tenant-scoped asset vault listing and CSV/vault-backed **financial summary** (`/assets`, `/assets/financial-summary`).",
    },
    {
        "name": "Factory & Digital Twin",
        "description": (
            "Empire lab status, live twin sensors, financial aggregates from DB, vault media **`/media/vault/...`**, "
            "twin control POST, and **Factory OS**: **`/factory/os/projects`** (lifecycle stages 2=income, 3=repair, 4=expansion), "
            "staff assignment, revival cost, **`/factory/os/.../machine-failure`** (🔴 emergency + billing pause), "
            "**`/factory/os/billing-hold`**, **Phase 6** **`GET /factory/status`** (equipment + work orders + manpower), "
            "**`PATCH /factory/os/equipment/{id}/status`** (Down → billing pause). Org enforced via JWT."
        ),
    },
    {
        "name": "Billing & HITL",
        "description": (
            "Human-in-the-loop **approvals**, invoice from production log, resolve approval, direct invoice PDF, "
            "and Stage-5 **brain intent** queue (`brain_action_intent`). Owner/Manager gates."
        ),
    },
    {
        "name": "Empire",
        "description": "**`GET /empire/forecast`** — next-month revenue + production/inventory index forecast (numpy). Owner/Manager.",
    },
    {
        "name": "Analytics & Control Tower",
        "description": (
            "**`GET /analytics/master-dashboard`** — single JSON: revenue (financial_service), unread alerts, "
            "pending approvals, AI forecast. Owner/Manager."
        ),
    },
    {
        "name": "Business Dashboard",
        "description": (
            "**`GET /dashboard/summary`** — bills-based revenue (today/week/month), GST (CGST/SGST/IGST), top SKUs. "
            "**`GET /dashboard/inventory-alerts`** — low stock. "
            "**`GET /dashboard/command-center`** — SAP-style life + business + AI JSON (authenticated); legacy analytics fields retained. "
            "**`GET /dashboard/command-center/legacy`** — admin-only pre-SAP unified snapshot. "
            "**`GET /dashboard/command-center/app`** — HTML shell (`templates/command_center.html`). "
            "**`WS /ws/dashboard`** — after connect, send JSON with field ``token`` (JWT); periodic SAP-style snapshot push (interval ``THIRAMAI_DASHBOARD_WS_INTERVAL`` s, default 7)."
        ),
    },
    {
        "name": "AI Memory & HITL",
        "description": (
            "**`POST /ai/hitl/feedback`** — owner/manager submits sentiment (-1 tighten, +1 loosen) per **rule_key** "
            "(typically a **tool_id**) to adjust policy weighting. **`GET /ai/hitl/rule-weight?rule_key=`** — read weight. "
            "Vector long-term memory uses Chroma when **`THIRAMAI_LTM_ENABLED=1`** (see `services/ltm_chroma`)."
        ),
    },
    {
        "name": "Unified local AI",
        "description": (
            "**Local Ollama** (JWT): **`POST /ai/local/chat`**, **`POST /ai/local/chat/stream`** (plain text stream), "
            "**`GET /ai/local/router-preview`**. Model routing: short → **llama3**, reasoning → **deepseek-r1**, "
            "long → **gemma2** (override via `THIRAMAI_OLLAMA_MODEL_*`). Set **`OLLAMA_HOST`**; disable with **`THIRAMAI_LOCAL_AI_ENABLED=0`**."
        ),
    },
    {
        "name": "Micro-kernel",
        "description": (
            "**Owner-only**, **off by default** (`THIRAMAI_KERNEL_API=1`). "
            "**`GET /kernel/status`**, **`POST /kernel/sandbox/pytest`** (Docker-isolated pytest + optional patch), "
            "**`POST /kernel/self-coder/run`** (LLM patch → sandbox tests → hot-reload signal), **`POST /kernel/reload/ack`**. "
            "Requires `THIRAMAI_KERNEL_SANDBOX=1` and Docker image `thiramai-sandbox:latest` for sandbox routes."
        ),
    },
    {
        "name": "Sovereign Stage 5",
        "description": (
            "**Global orchestrator:** **`GET /sovereign/cot/recent`**, **`GET /sovereign/cot/stream`** (SSE), "
            "**`GET /sovereign/dashboard`**, world scan + executive summary, LTM tuning brief, "
            "**`POST /sovereign/inbound/auto-reply`** (priority filter + brain). "
            "**Empire Governance:** **`/sovereign/empire/*`** P&L vs market, weekly opportunity, prompt self-tune, self-heal tick. "
            "Flags: **`THIRAMAI_EMPIRE_GOVERNANCE_MODE`**, **`THIRAMAI_EXCEPTION_ONLY_UX`** (chat stays silent unless strategic). "
            "Background: **`THIRAMAI_SOVEREIGN_SCHEDULER=1`**."
        ),
    },
    {
        "name": "Agentic workflow",
        "description": (
            "**Plan → Approve → Execute:** **`POST /api/agent/command`** (Groq JSON plan), **`GET /api/agent/plan/{task_id}`**, "
            "**`POST /api/agent/approve/{task_id}`** with JSON body `{ \"signal\": \"success\" | \"reject\" }`. "
            "Persisted in PostgreSQL **`agent_tasks`** (survives restarts). Trading steps use **`trade`** / **`search`** / **`code`** / **`reason`** "
            "(`services.orchestrator`). Model: **`THIRAMAI_AGENT_PLAN_MODEL`**."
        ),
    },
    {
        "name": "Action Execution",
        "description": (
            "**Real-world action layer:** **`POST /actions/plan`** (decompose command → persisted steps with risk levels), "
            "**`POST /actions/runs/{id}/confirm`** (batch medium-risk + explicit high-risk step IDs), "
            "**`POST /actions/runs/{id}/execute`** (sequential execution with verification, retries, execution memory), "
            "**`GET /actions/runs/{id}`**. Background: set **`async_execution`** on plan/execute or enable RQ (`THIRAMAI_ASYNC_QUEUE_MODE=rq`). "
            "Browser automation uses Playwright when installed (`playwright install chromium`)."
        ),
    },
]
