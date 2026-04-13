"""
THIRAMAI Genesis - FastAPI: core app, CORS, static factory mount, dashboard, and domain routers
(api/routes: auth, inventory, factory, billing, ai_chat — see api.routes.registry).
"""

import io
import sys

def _wrap_stdio_utf8(stream: object, *, name: str) -> None:
    """Re-wrap stdio as UTF-8 TextIOWrapper when the underlying buffer is usable (skip closed/NUL)."""
    try:
        buf = getattr(stream, "buffer", None)
        if buf is None or getattr(buf, "closed", False):
            return
        wrapper = io.TextIOWrapper(buf, encoding="utf-8", errors="replace")
        if name == "stdout":
            sys.stdout = wrapper
        else:
            sys.stderr = wrapper
    except (ValueError, OSError, AttributeError):
        return


_wrap_stdio_utf8(sys.stdout, name="stdout")
_wrap_stdio_utf8(sys.stderr, name="stderr")

import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=ROOT / ".env", override=True)

from core.settings import get_settings

import asset_portal
from api.middleware.correlation import CorrelationIdMiddleware
from api.middleware.request_logging import RequestLoggingMiddleware
from api.openapi_metadata import OPENAPI_DESCRIPTION, OPENAPI_TAGS
from api.routes.auth import router as auth_router, seed_default_roles_on_startup
from api.routes.registry import attach_domain_routers
from core.observability import ensure_thiramai_logging
from core.production_safety import assert_safe_production_config
from core.rate_limit_middleware import RateLimitMiddleware
from core.safe_errors import (
    log_server_exception,
    merge_response_headers,
    safe_errors_enabled,
    sanitize_http_exception,
)
from core.security_middleware import CsrfOriginMiddleware, SecurityHeadersMiddleware
from core.background_agent import start_background_agent, stop_background_agent
from workers.alert_system import shutdown_alert_scheduler, start_alert_scheduler
from workers.sovereign_scheduler import shutdown_sovereign_scheduler, start_sovereign_scheduler

# Legacy control-tower HTML (optional). Default ``GET /`` redirects to Command Center when built.
SPA_INDEX_PATH = ROOT / "static" / "index.html"
SCRIPT_PATH = ROOT / "script.js"


def _alert_scheduler_enabled() -> bool:
    return get_settings().scheduler_alert_truthy()


def _sovereign_scheduler_enabled() -> bool:
    return get_settings().scheduler_sovereign_truthy()


def _background_agent_enabled() -> bool:
    return get_settings().background_agent_truthy()


def _cors_allow_origins() -> list[str]:
    """
    Build CORS ``allow_origins`` for ``CORSMiddleware`` (see ``core.settings.ThiramaiSettings``).

    In **production**, only explicit ``THIRAMAI_CORS_ORIGINS`` are allowed; allow-all is disabled.
    """
    return get_settings().cors_allow_origins_list()


_s_app = get_settings()
_docs_url = None if _s_app.disable_openapi_uis() else "/docs"
_redoc_url = None if _s_app.disable_openapi_uis() else "/redoc"

app = FastAPI(
    title="THIRAMAI Genesis",
    description=OPENAPI_DESCRIPTION,
    version="0.4.0",
    openapi_tags=OPENAPI_TAGS,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

# Auth: POST /auth/register, /auth/login, GET /auth/me (see api/routes/auth.py).
app.include_router(auth_router)

attach_domain_routers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
# Outer layer: throttle /auth and /chat before route handlers (see THIRAMAI_RL_* env vars).
app.add_middleware(RateLimitMiddleware)
# Response security headers (CSP, nosniff, frame denial) + optional Origin gate (THIRAMAI_STRICT_ORIGIN).
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CsrfOriginMiddleware)
# JSON request lines (THIRAMAI_LOG_JSON=1); inside CorrelationId so correlation_id is on request.state.
app.add_middleware(RequestLoggingMiddleware)
# Stable correlation id for policy audit + client tracing (echoes X-Correlation-ID).
app.add_middleware(CorrelationIdMiddleware)

_proxy_hosts = (os.getenv("THIRAMAI_PROXY_TRUSTED_HOSTS") or "").strip()
if _proxy_hosts:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    _trusted: list[str] | str = (
        "*"
        if _proxy_hosts == "*"
        else [h.strip() for h in _proxy_hosts.split(",") if h.strip()]
    )
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted)

# Optional Host header validation (Django-style ALLOWED_HOSTS). Set THIRAMAI_ALLOWED_HOSTS=comma,separated,hosts
_allowed_hosts_raw = (os.getenv("THIRAMAI_ALLOWED_HOSTS") or "").strip()
if _allowed_hosts_raw:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    _allowed_hosts_list = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]
    if _allowed_hosts_list:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts_list)


@app.on_event("startup")
def _startup_thiramai() -> None:
    """
    Startup: structured logging + RBAC seed.

    Ensures each organization has default roles + **General** department when missing
    — see api.routes.auth.seed_default_roles_on_startup and core.db.provisioning.
    """
    assert_safe_production_config()
    ensure_thiramai_logging()
    logging.getLogger("thiramai").info(
        "LAN / mobile: run `ipconfig` on this PC and open http://<Wi-Fi IPv4>:8000/ on a device "
        "on the same network. If an old IP (e.g. 10.89.x.x) times out, the adapter address may have changed."
    )
    seed_default_roles_on_startup()
    if _alert_scheduler_enabled():
        start_alert_scheduler()
    if _sovereign_scheduler_enabled():
        start_sovereign_scheduler()


@app.on_event("startup")
async def _startup_background_agent() -> None:
    if _background_agent_enabled():
        start_background_agent()


@app.on_event("shutdown")
def _shutdown_thiramai() -> None:
    shutdown_alert_scheduler()
    shutdown_sovereign_scheduler()


@app.on_event("shutdown")
async def _shutdown_background_agent() -> None:
    stop_background_agent()


@app.exception_handler(RequestValidationError)
async def invoice_body_validation_400(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return 400 with clear JSON for invoice-style POSTs (easier dashboard debugging than 422)."""
    if safe_errors_enabled():
        if request.url.path.rstrip("/").endswith("/assets/invoice"):
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid invoice payload.", "errors": "redacted"},
            )
        return JSONResponse(status_code=422, content={"detail": "Validation failed.", "errors": "redacted"})
    if request.url.path.rstrip("/").endswith("/assets/invoice"):
        return JSONResponse(
            status_code=400,
            content={
                "detail": exc.errors(),
                "message": "Invalid invoice payload — check length, grade, weight, and rate (all required).",
            },
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(HTTPException)
async def http_exception_safe_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Mask error bodies in production (THIRAMAI_SAFE_ERRORS=1); preserve auth response headers."""
    _ = request
    body = sanitize_http_exception(exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=merge_response_headers(exc),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log_server_exception(request.url.path, exc)
    if safe_errors_enabled():
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred."},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )

asset_portal.FACTORY_OUTPUT.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/factory",
    StaticFiles(directory=str(asset_portal.FACTORY_OUTPUT)),
    name="factory_static",
)

_command_center_static = ROOT / "static" / "command_center"
_COMMAND_CENTER_INDEX = _command_center_static / "index.html"
_CC_INDEX_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
}
if _command_center_static.is_dir():
    # Exact path wins over the mount below so browsers/proxies always refetch HTML
    # (hashed ?v= on JS/CSS still allows long cache for bundles).
    if _COMMAND_CENTER_INDEX.is_file():

        @app.api_route(
            "/static/command_center/index.html",
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )
        def command_center_index_html() -> FileResponse:
            return FileResponse(
                str(_COMMAND_CENTER_INDEX),
                media_type="text/html; charset=utf-8",
                headers=_CC_INDEX_CACHE_HEADERS,
            )

    app.mount(
        "/static/command_center",
        StaticFiles(directory=str(_command_center_static)),
        name="command_center_static",
    )


@app.get("/command-center", tags=["System"], summary="Redirect to Command Center React SPA")
@app.get("/command-center/", tags=["System"], include_in_schema=False)
def command_center_spa_shortcut() -> RedirectResponse:
    """Browser shortcut: same app as ``/static/command_center/index.html`` (hash routing)."""
    if not _COMMAND_CENTER_INDEX.is_file():
        raise HTTPException(
            status_code=404,
            detail="Command Center SPA not built. Run: cd web/command_center && npm run build",
        )
    return RedirectResponse(
        url="/static/command_center/index.html#/today",
        status_code=302,
        headers=_browser_root_redirect_headers(),
    )


def _browser_root_redirect_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}


@app.api_route("/", methods=["GET", "HEAD"], tags=["System"], summary="Command Center redirect, legacy SPA, or JSON liveness")
def home(request: Request) -> Response:
    """
    - ``Accept: application/json`` → JSON liveness (unchanged for probes).
    - Default browser request → **302** to React Command Center ``#/personal`` when built.
    - ``THIRAMAI_LEGACY_ROOT_SPA=1`` → serve ``static/index.html`` again (rollback).
    """
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        if request.method == "HEAD":
            return Response(status_code=200, media_type="application/json")
        return JSONResponse(content={"status": "Thiramai Genesis is Active"})

    if get_settings().legacy_root_spa_truthy():
        if not SPA_INDEX_PATH.is_file():
            return JSONResponse(
                status_code=503,
                content={"detail": "SPA not found at static/index.html"},
            )
        return FileResponse(
            SPA_INDEX_PATH,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    if _COMMAND_CENTER_INDEX.is_file():
        return RedirectResponse(
            url="/static/command_center/index.html#/today",
            status_code=302,
            headers=_browser_root_redirect_headers(),
        )

    if not SPA_INDEX_PATH.is_file():
        return JSONResponse(
            status_code=503,
            content={"detail": "Command Center not built and static/index.html missing."},
        )
    return FileResponse(
        SPA_INDEX_PATH,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.api_route("/dashboard", methods=["GET", "HEAD"], tags=["System"], summary="Command Center redirect (business shell)")
def dashboard_page() -> Response:
    """Browser entry for the org dashboard → React ``#/dashboard`` (same SPA as Command Center)."""
    if get_settings().legacy_root_spa_truthy():
        if not SPA_INDEX_PATH.is_file():
            raise HTTPException(status_code=500, detail="SPA not found at static/index.html.")
        return FileResponse(
            SPA_INDEX_PATH,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    if _COMMAND_CENTER_INDEX.is_file():
        return RedirectResponse(
            url="/static/command_center/index.html#/dashboard",
            status_code=302,
            headers=_browser_root_redirect_headers(),
        )
    if not SPA_INDEX_PATH.is_file():
        raise HTTPException(status_code=500, detail="Command Center not built and static/index.html missing.")
    return FileResponse(
        SPA_INDEX_PATH,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.head("/script.js", tags=["System"], include_in_schema=False)
def dashboard_script_head() -> Response:
    return Response(status_code=200)


@app.get("/script.js", tags=["System"], summary="Dashboard bundle (script.js)")
def dashboard_script() -> FileResponse:
    if not SCRIPT_PATH.is_file():
        raise HTTPException(status_code=500, detail="Dashboard script is not available.")
    return FileResponse(SCRIPT_PATH, media_type="application/javascript; charset=utf-8")
