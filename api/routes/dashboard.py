"""
Phase 5 — Business dashboard: bills-based revenue, GST, top SKUs; inventory low-stock alerts.

**Admin-only** (exact JWT role name ``admin``). Heavy work runs in ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.templating import Jinja2Templates

from api.dependencies import CurrentUser, get_current_user, get_current_user_optional, require_exact_role
from services.analytics_service import compute_dashboard_summary_sync, list_low_stock_alerts_sync
from services.command_center import build_command_center_sap_payload_sync, build_unified_snapshot
from services.dashboard_ops_state import get_predictive_scaling_mode, set_predictive_scaling_mode
from services.experience_buffer import recent_successful_experiences
from services.dashboard_command_executor import execute_natural_language_dashboard_command
from services.dashboard_live_context import default_dashboard_org_id, safe_corporate_identity_for_live_dashboard
from services.economics_service import get_corporate_economics_context, persist_corporate_identity
from services.sre_health_report import build_sre_health_report
from services.thought_stream import append_thought, clear_thought_stream

router = APIRouter(prefix="/dashboard", tags=["Business Dashboard"])

# ``jsonable_encoder`` custom types — ``type(None)`` forces JSON null; Jinja2 ``Undefined`` maps to null too.
_dashboard_command_json_encoders: dict[Any, Any] = {type(None): lambda _: None}
try:
    from jinja2.runtime import Undefined as _JinjaUndefined

    _dashboard_command_json_encoders[_JinjaUndefined] = lambda _: None
except ImportError:
    pass

_DASH_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _DASH_ROOT
_live_templates = Jinja2Templates(directory=str(_DASH_ROOT / "templates"))

RequireAdmin = Depends(require_exact_role("admin"))


def _normalize_profile(p: str) -> str:
    return p if p in ("development", "production") else "development"


async def _safe_build_report(*, profile: str, write_reflection: bool) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        try:
            return build_sre_health_report(profile=profile, write_reflection=write_reflection)
        except Exception as exc:
            return {
                "profile": profile,
                "ok": False,
                "checks": {},
                "failure_reasons": ["report_exception"],
                "recovered_wounds": [],
                "scaling_intelligence": {
                    "ok": False,
                    "error": type(exc).__name__,
                    "detail": str(exc)[:500],
                },
                "report_error": str(exc)[:800],
            }

    return await asyncio.to_thread(_run)


def _collect_config_warnings(report: dict[str, Any], *, profile: str) -> list[str]:
    warnings: list[str] = []
    chk = report.get("checks") or {}
    esp = chk.get("env_secrets_present")
    if isinstance(esp, dict):
        if not esp.get("has_jwt_secret"):
            warnings.append("JWT / SECRET not configured — authenticated APIs may reject tokens.")
    if profile == "production":
        pr = chk.get("production_required")
        if isinstance(pr, dict) and not all(bool(v) for v in pr.values()):
            warnings.append("Production profile: DATABASE_URL or production gates incomplete.")
    ext = chk.get("external_api_keys")
    if isinstance(ext, dict):
        for w in ext.get("warnings") or []:
            if isinstance(w, str) and w.strip():
                warnings.append(w.strip())
    xconn = chk.get("external_connectivity")
    if isinstance(xconn, dict) and xconn.get("ok") is False and not xconn.get("skipped"):
        fails = xconn.get("failures") or []
        detail = (xconn.get("detail") or "").strip()
        if fails:
            warnings.append(f"External connectivity: failed services — {', '.join(str(f) for f in fails)}.")
        elif detail:
            warnings.append(f"External connectivity: {detail[:220]}")
    dschema = chk.get("database_schema")
    if isinstance(dschema, dict) and dschema.get("ok") is False and not dschema.get("skipped"):
        mc = dschema.get("missing_column")
        tail = f" Missing column hint: {mc}." if mc else ""
        warnings.append(
            f"Database schema probe failed — run `python -m services.verify_keys --sync` or alembic upgrade head.{tail}"
        )
    hb = chk.get("external_api_heartbeat")
    if isinstance(hb, dict) and hb.get("ok") is False and not hb.get("skipped"):
        warnings.append(
            f"External API Heartbeat failed — {str(hb.get('detail') or 'see SRE checks')[:220]}"
        )
    re = report.get("report_error")
    if re:
        warnings.append(f"SRE report builder raised an error (page still usable): {str(re)[:240]}")
    return warnings


def _default_corporate_dashboard_org_id() -> int:
    return default_dashboard_org_id()


def _resolve_corporate_write_org(request: Request, user: CurrentUser | None) -> int:
    if user is not None:
        if int(user.role_level) > 2:
            raise HTTPException(
                status_code=403,
                detail="Corporate identity updates require owner, admin, or manager role.",
            )
        return int(user.organization_id)
    tok = (os.getenv("THIRAMAI_DASHBOARD_ACTION_TOKEN") or "").strip()
    if not tok:
        raise HTTPException(
            status_code=401,
            detail=(
                "Authenticate with Bearer JWT or set THIRAMAI_DASHBOARD_ACTION_TOKEN and send "
                "X-THIRAMAI-Dashboard-Token for token-only dashboard saves."
            ),
        )
    _dashboard_action_authorized(request)
    return _default_corporate_dashboard_org_id()


def _live_context_from_report(
    *,
    request: Request,
    report: dict[str, Any],
    predictive_mode: str,
    generated_at: str,
    corporate_identity: dict[str, Any],
) -> dict[str, Any]:
    si = report.get("scaling_intelligence") or {}
    exp = si.get("successful_experiences") or {} if isinstance(si, dict) else {}
    exp_count = int(exp.get("successful_experience_count") or 0)
    exp_scanned = int(exp.get("lines_scanned") or 0)
    exp_trunc = bool(exp.get("truncated"))
    if exp_scanned > 0:
        buffer_bar_pct = min(100.0, max(5.0, 100.0 * exp_count / exp_scanned))
    else:
        buffer_bar_pct = 0.0

    ib = si.get("infra_budget") if isinstance(si, dict) else None
    if not isinstance(ib, dict):
        ib = {}

    prof = str(report.get("profile") or "development")
    chk = report.get("checks") or {}
    try:
        command_execute_url = str(request.url_for("dashboard_command_execute"))
    except Exception:
        command_execute_url = "/dashboard/command/execute"
    return {
        "request": request,
        "report": report,
        "si": si,
        "ib": ib,
        "generated_at": generated_at,
        "predictive_reasons_display": ", ".join(si.get("predictive_reasons") or []) or "—",
        "exp_count": exp_count,
        "exp_scanned": exp_scanned,
        "exp_trunc": exp_trunc,
        "buffer_bar_pct": buffer_bar_pct,
        "external_api_heartbeat": chk.get("external_api_heartbeat") if isinstance(chk, dict) else None,
        "check_items": [
            (k, v)
            for k, v in (chk.items() if isinstance(chk, dict) else [])
            if k != "external_api_heartbeat"
        ],
        "predictive_mode": predictive_mode,
        "config_warnings": _collect_config_warnings(report, profile=prof),
        "dashboard_action_token_configured": bool((os.getenv("THIRAMAI_DASHBOARD_ACTION_TOKEN") or "").strip()),
        # Injected for same-origin dashboard so fetch() can send X-THIRAMAI-Dashboard-Token without manual sessionStorage.
        "dashboard_action_token_value": (os.getenv("THIRAMAI_DASHBOARD_ACTION_TOKEN") or "").strip(),
        "corporate_identity": corporate_identity,
        "command_execute_url": command_execute_url,
    }


def _public_state_dict(
    *,
    report: dict[str, Any],
    predictive_mode: str,
    generated_at: str,
    corporate_identity: dict[str, Any],
) -> dict[str, Any]:
    si = report.get("scaling_intelligence") or {}
    if not isinstance(si, dict):
        si = {}
    ib = si.get("infra_budget") if isinstance(si.get("infra_budget"), dict) else {}
    exp = si.get("successful_experiences") or {}
    if not isinstance(exp, dict):
        exp = {}
    pred_effective = si.get("predictive_effective_threshold")
    pred_active = bool(si.get("predictive_active")) and predictive_mode != "manual"
    return {
        "schema": "thiramai.dashboard_state.v1",
        "profile": report.get("profile"),
        "generated_at": generated_at,
        "overall_green": bool(report.get("ok")),
        "predictive_mode": predictive_mode,
        "predictive_active": pred_active,
        "predictive_reasons": si.get("predictive_reasons") or [],
        "predictive_effective_threshold": pred_effective,
        "predictive_threshold_drop": si.get("predictive_threshold_drop"),
        "predictive_timezone": si.get("predictive_timezone"),
        "base_pending_threshold": si.get("base_pending_threshold"),
        "learned_pending_threshold": si.get("learned_pending_threshold"),
        "successful_experience_count": int(exp.get("successful_experience_count") or 0),
        "budget_configured": bool(ib.get("budget_configured")),
        "remaining_infra_budget_inr": ib.get("remaining_infra_budget_inr"),
        "budget_cap_inr": ib.get("budget_cap_inr"),
        "config_warnings": _collect_config_warnings(report, profile=str(report.get("profile") or "development")),
        "company_name": corporate_identity.get("company_name")
        or corporate_identity.get("name")
        or "",
        "gst_number": str(corporate_identity.get("gst_number") or ""),
        "corporate_organization_id": corporate_identity.get("organization_id"),
        "corporate_identity": {
            "organization_id": corporate_identity.get("organization_id"),
            "name": corporate_identity.get("name") or corporate_identity.get("company_name") or "",
            "company_name": corporate_identity.get("company_name") or corporate_identity.get("name") or "",
            "gst_number": str(corporate_identity.get("gst_number") or ""),
        },
        "external_api_heartbeat": (report.get("checks") or {}).get("external_api_heartbeat")
        if isinstance(report.get("checks"), dict)
        else None,
    }


def _dashboard_action_authorized(request: Request) -> None:
    tok = (os.getenv("THIRAMAI_DASHBOARD_ACTION_TOKEN") or "").strip()
    if not tok:
        return
    got = (request.headers.get("x-thiramai-dashboard-token") or "").strip()
    if got != tok:
        raise HTTPException(status_code=401, detail="Missing or invalid X-THIRAMAI-Dashboard-Token")


class _PredictiveBody(BaseModel):
    mode: str = Field(default="ai", description="ai | manual")


class _CorporateIdentityBody(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=500)
    gst_number: str = Field(default="", max_length=64)


class _CommandExecuteBody(BaseModel):
    command: str = Field(..., min_length=1, max_length=4000)
    profile: str = Field(
        default="development",
        description="SRE profile when the resolved intent runs in-process health (development | production).",
    )


def _threshold() -> int:
    raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip()
    try:
        return max(0, min(10_000, int(raw)))
    except ValueError:
        return 5


@router.get(
    "/summary",
    summary="Bills revenue, GST, top SKUs",
    description="Admin only. Aggregates ``bills`` for this org: revenue today/week/month, GST, top 5 SKUs.",
)
async def dashboard_summary(_admin: CurrentUser = RequireAdmin) -> JSONResponse:
    data = await asyncio.to_thread(
        compute_dashboard_summary_sync,
        _admin.organization_id,
        low_stock_threshold=_threshold(),
    )
    return JSONResponse(content=data)


@router.get(
    "/today",
    summary="Today's dashboard slice (revenue + low stock)",
    description=(
        "Authenticated tenant snapshot: bills-based revenue summary and low-stock list. "
        "Uses JWT active organization (any member with a valid token)."
    ),
)
async def dashboard_today(
    _user: CurrentUser = Depends(get_current_user),
    threshold: int = Query(5, ge=0, le=10_000, description="Low-stock quantity threshold"),
) -> JSONResponse:
    oid = int(_user.organization_id)

    def _run() -> dict[str, Any]:
        return {
            "ok": True,
            "organization_id": oid,
            "low_stock": list_low_stock_alerts_sync(oid, threshold=threshold),
            "summary": compute_dashboard_summary_sync(oid, low_stock_threshold=threshold),
        }

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.get(
    "/inventory-alerts",
    summary="Low-stock inventory rows",
    description="Admin only. Items where quantity is below the threshold (env ``THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD``).",
)
async def dashboard_inventory_alerts(
    _admin: CurrentUser = RequireAdmin,
    threshold: int | None = Query(default=None, ge=0, le=10_000),
) -> JSONResponse:
    thr = int(threshold) if threshold is not None else _threshold()
    data = await asyncio.to_thread(
        list_low_stock_alerts_sync,
        _admin.organization_id,
        threshold=thr,
    )
    return JSONResponse(content=data)


@router.get(
    "/command-center",
    summary="SAP-style command center (life + business + AI + legacy ops snapshot)",
    description=(
        "Authenticated tenant member. Returns unified **life_dashboard**, **business_summary**, "
        "**inventory_summary**, **ai_decisions**, **next_best_move**, **alerts**, plus **legacy** fields "
        "(`analytics`, `inventory_alerts`, `priority_queue`, …) for backward compatibility."
    ),
)
async def dashboard_command_center(
    user: CurrentUser = Depends(get_current_user),
    threshold: int | None = Query(default=None, ge=0, le=10_000),
) -> JSONResponse:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Valid user id required")
    thr = int(threshold) if threshold is not None else _threshold()

    def _run() -> dict[str, Any]:
        return build_command_center_sap_payload_sync(
            int(user.id),
            int(user.organization_id),
            low_stock_threshold=thr,
        )

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.get(
    "/command-center/legacy",
    summary="Command center legacy JSON (admin, pre-SAP shape only)",
    description="Admin only. Same as historical `/dashboard/command-center` payload without life/AI SAP fields.",
    include_in_schema=True,
)
async def dashboard_command_center_legacy_admin(_admin: CurrentUser = RequireAdmin) -> JSONResponse:
    data = await asyncio.to_thread(
        build_unified_snapshot,
        _admin.organization_id,
        low_stock_threshold=_threshold(),
    )
    return JSONResponse(content=data)


@router.get(
    "/command-center/app",
    response_class=HTMLResponse,
    summary="Command Center dashboard (HTML shell)",
    description="Dark UI for GET /dashboard/command-center. Uses JWT from localStorage key `thiramai_jwt`.",
)
async def dashboard_command_center_app(request: Request) -> HTMLResponse:
    return _live_templates.TemplateResponse(
        request,
        "command_center.html",
        {"request": request},
    )


@router.get(
    "/recent_experiences.json",
    summary="Last successful experiences (ticker JSON)",
    description="Up to five newest successful rows from ``logs/experience_buffer.jsonl`` for the live dashboard ticker.",
)
async def dashboard_recent_experiences_json() -> JSONResponse:
    items = await asyncio.to_thread(recent_successful_experiences, limit=5)
    return JSONResponse(
        content={
            "schema": "thiramai.recent_experiences.v1",
            "items": items,
        }
    )


@router.get(
    "/live/state.json",
    summary="Live dashboard state (JSON)",
    description="Slim payload for refreshing pulse, predictive mode, budget, and config warnings without full HTML.",
)
async def dashboard_live_state_json(
    profile: str = Query("development", description="'development' or 'production'"),
) -> JSONResponse:
    prof = _normalize_profile(profile)
    report = await _safe_build_report(profile=prof, write_reflection=False)
    mode = await asyncio.to_thread(get_predictive_scaling_mode)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    corp = await asyncio.to_thread(safe_corporate_identity_for_live_dashboard)
    return JSONResponse(
        content=_public_state_dict(
            report=report,
            predictive_mode=mode,
            generated_at=generated_at,
            corporate_identity=corp,
        )
    )


@router.post(
    "/setup/identity",
    summary="Corporate setup: company name + GST",
    description=(
        "Writes ``organizations.name`` and ``organizations.gst_number`` and refreshes "
        "``economics_service`` in-process corporate identity. "
        "Use Bearer JWT (owner/admin/manager) **or** ``THIRAMAI_DASHBOARD_ACTION_TOKEN`` + "
        "``X-THIRAMAI-Dashboard-Token`` with ``THIRAMAI_CORPORATE_DASHBOARD_ORG_ID`` / default org env."
    ),
)
async def corporate_setup_identity(
    request: Request,
    body: _CorporateIdentityBody,
    user: CurrentUser | None = Depends(get_current_user_optional),
) -> JSONResponse:
    org_id = _resolve_corporate_write_org(request, user)

    def _save() -> dict[str, Any]:
        return persist_corporate_identity(
            org_id,
            company_name=body.company_name.strip(),
            gst_number=body.gst_number.strip(),
        )

    try:
        out = await asyncio.to_thread(_save)
    except ValueError as exc:
        msg = str(exc)
        if msg == "company_name_required":
            raise HTTPException(status_code=400, detail="company_name_required") from exc
        if msg == "organization_not_found":
            raise HTTPException(status_code=404, detail="organization_not_found") from exc
        raise HTTPException(status_code=400, detail=msg) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="database_not_configured") from exc
    try:
        append_thought(
            f"Corporate identity saved: {out.get('company_name')!r} (org {org_id}).",
            phase="dashboard",
            agent="dashboard",
        )
    except Exception:
        pass
    return JSONResponse(content={"ok": True, "corporate_identity": out})


@router.post(
    "/command/execute",
    name="dashboard_command_execute",
    summary="Universal autonomous console: NL → Groq intent → orchestrated actions",
    description=(
        "Master orchestrator: Groq classifies intent (identity, SRE health, infra budget, thought clear, "
        "inventory, autoscale, predictive mode, …). Extensible via ``dashboard_command_registry``. "
        "Same auth as ``/dashboard/setup/identity``. Trailing slash URL also accepted."
    ),
)
@router.post("/command/execute/", include_in_schema=False)
async def dashboard_command_execute(
    request: Request,
    body: _CommandExecuteBody,
    user: CurrentUser | None = Depends(get_current_user_optional),
) -> JSONResponse:
    org_id = _resolve_corporate_write_org(request, user)
    prof = _normalize_profile(body.profile)

    def _run() -> dict[str, Any]:
        xctx: dict[str, Any] = {}
        if user is not None:
            xctx["user_id"] = int(user.id)
            xctx["actor_role_name"] = user.role_name
            xctx["role_level"] = int(user.role_level)
        return execute_natural_language_dashboard_command(
            raw_command=body.command,
            organization_id=org_id,
            sre_profile=prof,
            executor_context=xctx if xctx else None,
        )

    result = await asyncio.to_thread(_run)
    if result is None or not isinstance(result, dict):
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Command processed but returned an invalid response format.",
            },
        )
    err = result.get("error")
    if err == "groq_not_configured":
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured; AI command console unavailable.",
        )
    tm = result.get("thought_message")
    if tm:
        try:
            ts_body = str(tm)
            udd = result.get("ui_display_data")
            if (
                isinstance(udd, dict)
                and udd.get("format") == "markdown"
                and isinstance(udd.get("markdown"), str)
                and len(udd["markdown"]) > 2000
            ):
                ts_body = (
                    "System: Solar DPR market research complete — full markdown is in "
                    "`thought_message` and `ui_display_data.markdown` in the API response "
                    f"({len(udd['markdown'])} chars)."
                )
            append_thought(ts_body, phase="system", agent="jarvis_console")
        except Exception:
            pass
    return JSONResponse(
        content=jsonable_encoder(
            result,
            custom_encoder=_dashboard_command_json_encoders,
        ),
    )


@router.post(
    "/live/action/health-check",
    summary="Run scripts/sre_health_check.py (writes reflection)",
    description="Subprocess health check with ``write_reflection=True`` equivalent (experience buffer updated).",
)
async def dashboard_action_health_check(
    request: Request,
    profile: str = Query("development", description="'development' or 'production'"),
) -> JSONResponse:
    _dashboard_action_authorized(request)
    prof = _normalize_profile(profile)

    def _subprocess() -> tuple[dict[str, Any], int, str]:
        cmd = [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "sre_health_check.py"),
            "--profile",
            prof,
            "--emit-json-only",
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=300,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "sre_health_check_timeout"}, -1, ""
        raw = (proc.stdout or "").strip()
        try:
            report = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            report = {
                "ok": False,
                "error": "invalid_json_from_sre_script",
                "stdout_tail": raw[-1200:],
                "stderr_tail": (proc.stderr or "")[-800:],
            }
        return report, int(proc.returncode), (proc.stderr or "")[-2000:]

    report, code, stderr_tail = await asyncio.to_thread(_subprocess)
    try:
        append_thought(
            f"SRE health check finished (exit {code}) profile={prof}.",
            phase="dashboard",
            agent="dashboard",
        )
    except Exception:
        pass
    return JSONResponse(
        content={
            "ok": True,
            "exit_code": code,
            "profile": prof,
            "report": report,
            "stderr_tail": stderr_tail if stderr_tail else None,
        }
    )


@router.post(
    "/live/action/autoscale",
    summary="Run services/do_worker_autoscale.run_autoscale_once",
)
async def dashboard_action_autoscale(request: Request) -> JSONResponse:
    _dashboard_action_authorized(request)

    def _run() -> dict[str, Any]:
        from services.do_worker_autoscale import run_autoscale_once

        return run_autoscale_once()

    result = await asyncio.to_thread(_run)
    try:
        append_thought(
            f"Manual autoscale trigger from dashboard — action={result.get('action')!r}.",
            phase="dashboard",
            agent="dashboard",
        )
    except Exception:
        pass
    return JSONResponse(content={"ok": True, "result": result})


@router.post(
    "/live/action/clear-thought-stream",
    summary="Clear logs/thought_stream.json",
)
async def dashboard_action_clear_thought_stream(request: Request) -> JSONResponse:
    _dashboard_action_authorized(request)

    out = await asyncio.to_thread(clear_thought_stream)
    return JSONResponse(content={"ok": bool(out.get("ok")), "thought_stream": out})


@router.post(
    "/live/action/predictive-mode",
    summary="Toggle AI predictive scaling vs manual (persisted under var/)",
)
async def dashboard_action_predictive_mode(
    request: Request,
    body: _PredictiveBody = Body(),
) -> JSONResponse:
    _dashboard_action_authorized(request)

    def _set() -> str:
        return set_predictive_scaling_mode(body.mode)

    mode = await asyncio.to_thread(_set)
    try:
        append_thought(
            f"Predictive scaling mode set to {mode.upper()} (dashboard).",
            phase="dashboard",
            agent="dashboard",
        )
    except Exception:
        pass
    return JSONResponse(content={"ok": True, "predictive_mode": mode})


@router.get(
    "/live",
    response_class=HTMLResponse,
    summary="Interactive JARVIS ops dashboard (HTML)",
    description=(
        "SRE probes, predictive scaling, infra budget, thought stream, and operator actions. "
        "Template: ``templates/dashboard.html``. Optional POST token: ``THIRAMAI_DASHBOARD_ACTION_TOKEN`` + "
        "header ``X-THIRAMAI-Dashboard-Token``."
    ),
)
async def dashboard_live_sre(
    request: Request,
    profile: str = Query("development", description="'development' or 'production'"),
) -> HTMLResponse:
    prof = _normalize_profile(profile)
    report = await _safe_build_report(profile=prof, write_reflection=False)
    mode = await asyncio.to_thread(get_predictive_scaling_mode)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    corp = await asyncio.to_thread(safe_corporate_identity_for_live_dashboard)
    ctx = _live_context_from_report(
        request=request,
        report=report,
        predictive_mode=mode,
        generated_at=generated_at,
        corporate_identity=corp,
    )
    return _live_templates.TemplateResponse(request, "dashboard.html", ctx)
