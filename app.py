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
import re
import signal
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=ROOT / ".env", override=True)

from core.settings import get_settings

import asset_portal
from api.middleware.ai_payload_limit import AiPayloadLimitMiddleware
from api.middleware.correlation import CorrelationIdMiddleware
from api.middleware.request_logging import RequestLoggingMiddleware
from api.openapi_metadata import OPENAPI_DESCRIPTION, OPENAPI_TAGS
from api.dependencies import CurrentUser, get_current_user
from api.routes.auth import router as auth_router, seed_default_roles_on_startup
from api.routes.registry import attach_domain_routers
from core.exceptions import ThiramaiAppError
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


def _incident_or_degraded() -> bool:
    return get_settings().incident_mode_truthy()


def _alert_scheduler_enabled() -> bool:
    if _incident_or_degraded():
        return False
    return get_settings().scheduler_alert_truthy()


def _sovereign_scheduler_enabled() -> bool:
    if _incident_or_degraded():
        return False
    return get_settings().scheduler_sovereign_truthy()


def _background_agent_enabled() -> bool:
    if _incident_or_degraded():
        return False
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

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.post("/auto-deploy/trigger", tags=["AutoDeploy"])
async def trigger_auto_deploy(
    action: str = "health-check",
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _ = current_user
    from services.auto_deploy_engine import run_health_check, safe_restart_service

    if action == "health-check":
        ok = run_health_check()
        return {"ok": ok, "message": "healthy" if ok else "unhealthy"}
    if action == "restart":
        return safe_restart_service()
    return {"ok": False, "message": f"Unknown action: {action}"}


@app.get("/auto-deploy/status", tags=["AutoDeploy"])
async def auto_deploy_status() -> dict[str, Any]:
    import json
    from services.auto_deploy_engine import DEPLOY_LOG_PATH, can_auto_deploy

    ok, reason = can_auto_deploy()
    history: list[dict[str, Any]] = []
    if DEPLOY_LOG_PATH.exists():
        with open(DEPLOY_LOG_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    history.append(json.loads(line))
                except Exception:
                    continue
    return {"can_deploy": ok, "reason": reason, "recent_deploys": history[-5:]}


def _signal_begin_goal_shutdown(*_args: object) -> None:
    try:
        from thiramai.runtime import goal_jobs

        goal_jobs.begin_shutdown(accept_new_jobs=False)
        logging.getLogger("thiramai").warning(
            "Shutdown signal: autonomous goal submissions disabled; in-flight jobs may finish."
        )
    except Exception:
        logging.getLogger("thiramai").exception("goal_jobs.begin_shutdown from signal failed")


if hasattr(signal, "SIGTERM"):
    try:
        signal.signal(signal.SIGTERM, _signal_begin_goal_shutdown)
    except (OSError, ValueError, AttributeError):
        pass


@app.get(
    "/api/system/command-center-build",
    tags=["System"],
    summary="Command Center deploy id for cache-busting shell URLs",
    include_in_schema=False,
)
def command_center_build_metadata() -> dict[str, str]:
    """Exposes ``THIRAMAI_COMMAND_CENTER_BUILD_ID`` for legacy ``static/index.html`` navigations."""
    s = get_settings()
    return {"v": (s.THIRAMAI_COMMAND_CENTER_BUILD_ID or "").strip()}


class CommandCenterStaticNoStoreMiddleware(BaseHTTPMiddleware):
    """Force no-store for Command Center assets (index + hashed bundles); avoids stale JS when proxies strip app headers."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/command_center/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


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

app.add_middleware(CommandCenterStaticNoStoreMiddleware)
app.add_middleware(AiPayloadLimitMiddleware)


@app.on_event("startup")
def _startup_thiramai() -> None:
    """
    Startup: structured logging + RBAC seed.

    Ensures each organization has default roles + **General** department when missing
    — see api.routes.auth.seed_default_roles_on_startup and core.db.provisioning.
    """
    try:
        from thiramai.runtime.env_validate import validate_thiramai_environment

        validate_thiramai_environment(raise_on_error=True)
    except Exception:
        logging.getLogger("thiramai").exception("THIRAMAI environment validation failed — refusing startup")
        raise
    assert_safe_production_config()
    ensure_thiramai_logging()
    _log_command_center_index_sanity()
    logging.getLogger("thiramai").info(
        "LAN / mobile: run `ipconfig` on this PC and open http://<Wi-Fi IPv4>:8000/ on a device "
        "on the same network. If an old IP (e.g. 10.89.x.x) times out, the adapter address may have changed."
    )
    seed_default_roles_on_startup()
    if _incident_or_degraded():
        logging.getLogger("thiramai").warning(
            "THIRAMAI_INCIDENT_MODE or THIRAMAI_STARTUP_DEGRADED is on — background schedulers and agent are disabled."
        )
    if (os.getenv("THIRAMAI_STARTUP_DISABLE_POST_PROBE") or "").strip() != "1":
        from core.startup_checks import schedule_post_bind_self_probe

        schedule_post_bind_self_probe()
    if (os.getenv("THIRAMAI_STABILITY_RESOURCE_POLL_SEC") or "").strip() not in ("", "0"):
        from core.stability.resource_monitor import start_optional_resource_poll

        start_optional_resource_poll()
    try:
        from thiramai.runtime import goal_jobs

        goal_jobs.initialize_persistence()
    except Exception:
        logging.getLogger("thiramai").exception("goal_jobs.initialize_persistence failed")
    try:
        from thiramai.runtime.warm_start import run_warm_start

        ws = run_warm_start()
        logging.getLogger("thiramai").info("warm_start %s", ws)
    except Exception:
        logging.getLogger("thiramai").exception("warm_start failed")
    try:
        from thiramai.runtime import ops_alerts

        ops_alerts.start_background_checks(60.0)
    except Exception:
        logging.getLogger("thiramai").exception("ops_alerts.start_background_checks failed")
    try:
        from thiramai.runtime import sqlite_maintenance

        sqlite_maintenance.start_optional_backup_scheduler()
    except Exception:
        logging.getLogger("thiramai").exception("sqlite_maintenance.start_optional_backup_scheduler failed")
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
    try:
        from thiramai.runtime import ops_alerts

        ops_alerts.stop_background_checks()
    except Exception:
        logging.getLogger("thiramai").exception("ops_alerts.stop_background_checks failed")
    try:
        from thiramai.runtime import sqlite_maintenance

        sqlite_maintenance.stop_backup_scheduler()
    except Exception:
        logging.getLogger("thiramai").exception("sqlite_maintenance.stop_backup_scheduler failed")
    try:
        from thiramai.runtime import goal_jobs

        goal_jobs.begin_shutdown(accept_new_jobs=False)
        goal_jobs.shutdown_graceful(timeout_sec=45.0)
    except Exception:
        logging.getLogger("thiramai").exception("goal_jobs.shutdown_graceful failed")
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


@app.exception_handler(ThiramaiAppError)
async def thiramai_app_error_handler(request: Request, exc: ThiramaiAppError) -> JSONResponse:
    """Structured API errors (``core.exceptions``) with stable JSON shape."""
    _ = request
    if safe_errors_enabled() and exc.status_code >= 500:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": "Request could not be completed.", "code": exc.code},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
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
    # Exact path wins over the mount below so browsers/proxies always refetch HTML.
    # Vite emits hashed bundles (cc-app-[hash].js, cc-*-[hash].css); those can be cached aggressively by CDN/browser.
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


def _command_center_index_diagnostics() -> dict[str, Any]:
    """Detect stale shells (``cc-app.js?v=``) vs Vite ``cc-app-<hash>.js``."""
    out: dict[str, Any] = {
        "index_path": str(_COMMAND_CENTER_INDEX),
        "exists": _COMMAND_CENTER_INDEX.is_file(),
    }
    if not out["exists"]:
        out["ok"] = False
        out["issues"] = ["index.html missing"]
        return out
    try:
        text = _COMMAND_CENTER_INDEX.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        out["ok"] = False
        out["issues"] = [f"read failed: {e}"]
        return out
    out["bytes"] = len(text.encode("utf-8"))
    m = re.search(r'src="([^"]*cc-app[^"]*)"', text)
    out["cc_app_script_src"] = m.group(1) if m else None
    has_hashed = bool(re.search(r"cc-app-[A-Za-z0-9_-]+\.js", text))
    has_legacy = "/cc-app.js" in text
    if has_hashed and not has_legacy:
        out["ok"] = True
        out["bundle_style"] = "content_hashed"
    elif has_legacy:
        out["ok"] = False
        out["bundle_style"] = "legacy_cc_app_js"
        out["issues"] = [
            "index references cc-app.js (unhashed). Rebuild Command Center (Vite) and redeploy; "
            "ensure Nginx proxies /static/command_center/ to this app, not alias to an old directory.",
        ]
    else:
        out["ok"] = False
        out["bundle_style"] = "unknown"
        out["issues"] = ["could not detect cc-app entry in index.html"]
    return out


def _log_command_center_index_sanity() -> None:
    if not _command_center_static.is_dir():
        return
    log = logging.getLogger("thiramai")
    d = _command_center_index_diagnostics()
    if d.get("ok") is True:
        log.info("Command Center index OK (%s)", d.get("bundle_style"))
        return
    log.error("Command Center index problem: %s", d)


@app.get("/health/command-center-index", tags=["System"], include_in_schema=False)
def health_command_center_index() -> dict[str, Any]:
    """Operator probe: does on-disk ``index.html`` use content-hashed ``cc-app-*.js``?"""
    return _command_center_index_diagnostics()


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
        url=get_settings().command_center_shell_url("today"),
        status_code=302,
        headers=_browser_root_redirect_headers(),
    )


def _browser_root_redirect_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}


@app.api_route("/", methods=["GET", "HEAD"], tags=["System"], summary="Command Center redirect, legacy SPA, or JSON liveness")
def home(request: Request) -> Response:
    """
    - ``Accept: application/json`` → JSON liveness (unchanged for probes).
    - Default browser request → **302** to React Command Center ``#/today`` when built.
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
            url=get_settings().command_center_shell_url("today"),
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
            url=get_settings().command_center_shell_url("dashboard"),
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
