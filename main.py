"""
THIRAMAI Genesis — production ASGI entry.

**Run (development):** ``python main.py`` (reload if ``THIRAMAI_UVICORN_RELOAD=1``) or
``python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000``

**Run (production):** ``python -m uvicorn main:app --host 0.0.0.0 --port 8000`` or ``python main.py`` — defaults to **0.0.0.0:8000** (place behind TLS termination).

**Common mistakes (Windows / PowerShell):**

- Do **not** run ``python -m main.py`` — ``-m`` takes a *module name* (use ``python main.py``, ``python run.py``, or ``DevServer.cmd`` on Windows).
- If ``uvicorn`` is not recognized, use ``python -m uvicorn main:app ...`` or ``python main.py`` (no ``uvicorn`` on PATH required).

**Live ops HTML:** ``GET /dashboard/live`` — SRE checks + scaling intelligence (Tailwind CDN).

---

### OpenAPI (Swagger)

- **Interactive docs:** ``GET /docs``
- **Schema:** ``GET /openapi.json``

Tag names and the high-level API description are defined in ``api.openapi_metadata`` and attached in
``app.FastAPI(...)`` (see ``app.py``). Route groups use the same tag names (e.g. *Authentication*,
*AI & Council*, *Billing & HITL*).

---

### Rate limiting (abuse protection)

Sliding-window limits:

- **Per client IP:** **``/auth/*``** (``THIRAMAI_RL_AUTH_PER_MINUTE``), **``GET /chat``** (``THIRAMAI_RL_CHAT_PER_MINUTE``).
- **Per authenticated user (JWT ``sub``):** **``POST /chat/query``** — ``THIRAMAI_RL_CHAT_QUERY_PER_USER_PER_MINUTE`` (default 5/min; raise for load tests only).

**``POST /chat/query``** also **rejects missing/expired/invalid JWT** in middleware (**401**) before the route runs.

Implementation: ``core.rate_limit_middleware.RateLimitMiddleware`` (stdlib + Starlette; no slowapi).

Behind a reverse proxy, set ``THIRAMAI_RL_TRUST_X_FORWARDED_FOR=1`` so the **first** hop in
``X-Forwarded-For`` is used as the client key (only if you trust the proxy).

---

### Multi-tenant (IDOR)

JWT embeds ``organization_id``. Routes that read/write tenant tables must use
``CurrentUser.organization_id`` (or equivalent) and **never** trust a client-supplied org id alone.

Service-layer audit highlights: ``approval_store``, ``vault_snapshot``, ``predictive_engine``, and
``financial_analytics`` filter by org; ``robotics_service`` inventory hints require ``organization_id``.
Legacy ``inventory.organization_id IS NULL`` rows may match only when explicitly allowed alongside a
tenant id (billing / execution paths).

---

### Environment

See **``.env.example``** for all supported variables. Production Docker and cloud steps: **``docs/DEPLOYMENT.md``** and **``.env.production.example``**.

---

### Static SPA

- **``GET /``** serves ``static/index.html`` (Tailwind SPA) unless ``Accept: application/json`` (liveness JSON).
- **``GET /public/...``** — ``StaticFiles`` for the same ``static/`` directory (does not use ``/static`` so ``/static/factory`` from ``app.py`` stays valid).
"""

import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles

# CORS is applied in ``app.py`` (CORSMiddleware on ``app``). See ``core.settings.ThiramaiSettings.cors_allow_origins_list``;
# production requires explicit ``THIRAMAI_CORS_ORIGINS`` (allow-all is disabled).
from app import app
from api.routes.registry import attach_domain_routers

# ``app`` already called ``attach_domain_routers`` in ``app.py``; calling again is idempotent (registry guard).
attach_domain_routers(app)

# ``GET /dashboard/live`` is registered on the **Business Dashboard** router:
# ``api.routes.dashboard`` → ``APIRouter(prefix="/dashboard")`` + ``@router.get("/live")``.
# It is not missing from ``main.py`` merges: the path exists on ``main:app`` after ``include_router``.

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)
# Mount must not be `/static` — app.py already serves factory output at `/static/factory`.
app.mount("/public", StaticFiles(directory=str(_STATIC_DIR)), name="thiramai_public")

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    # Same as: python -m uvicorn main:app --host 0.0.0.0 --port 8000
    # Default host is 0.0.0.0 (all interfaces), not 127.0.0.1 — required for LAN access to /dashboard/live.
    _bind_host = (os.getenv("THIRAMAI_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    _bind_port = int((os.getenv("THIRAMAI_PORT") or "8000").strip() or "8000")
    uvicorn.run(
        "main:app",
        host=_bind_host,
        port=_bind_port,
        reload=os.getenv("THIRAMAI_UVICORN_RELOAD", "").strip().lower() in ("1", "true", "yes", "on"),
    )
