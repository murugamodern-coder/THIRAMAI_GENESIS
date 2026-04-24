"""
Master orchestrator for ``POST /dashboard/command/execute``: Groq intent → registered handlers.

Built-in actions: corporate identity, SRE health snapshot, infra budget cap (persisted override),
thought stream clear, inventory low-stock summary, inventory adjust (signed delta), solar DPR research refresh.
Optional handlers load from
``services.dashboard_command_plugins``.
"""

from __future__ import annotations

import importlib
import json
import logging
import math
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.brain_output import _extract_json_object
from services.dashboard_command_registry import (
    get_dashboard_command_handler,
    register_dashboard_command_handler as _register_handler,
)
from services.economics_service import get_corporate_economics_context, persist_corporate_identity

_LOG = logging.getLogger(__name__)

_MAX_CHARS = int((os.getenv("THIRAMAI_DASHBOARD_COMMAND_MAX_CHARS") or "4000").strip() or "4000")

_PLUGINS_LOADED = False
_MUTATING_ACTIONS = {
    "inventory_adjust",
    "run_worker_autoscale",
    "run_auto_repair",
    "set_predictive_scaling_mode",
    "update_company_identity",
    "set_operational_infra_budget",
    "clear_thought_stream",
}
_ALLOW_ANON_MUTATING_ACTIONS = {
    "update_company_identity",
    "run_auto_repair",
    "set_operational_infra_budget",
    "set_predictive_scaling_mode",
    "run_worker_autoscale",
    "clear_thought_stream",
}


def _is_jinja_undefined(obj: Any) -> bool:
    """Jinja2 ``Undefined`` is not JSON-serializable; detect without hard-depending on jinja2."""
    cls_name = type(obj).__name__
    if cls_name == "Undefined":
        return True
    mod = getattr(type(obj), "__module__", "") or ""
    return mod.startswith("jinja2") and "Undefined" in cls_name


def _sanitize_for_json(obj: Any, *, _depth: int = 0) -> Any:
    """Recursively coerce values to JSON-safe types (no Undefined, Decimal, nan, etc.)."""
    if _depth > 64:
        return None
    if obj is None:
        return None
    if _is_jinja_undefined(obj):
        return None
    if isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, Decimal):
        return format(obj, "f")
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key = str(k) if not isinstance(k, str) else k
            out[key] = _sanitize_for_json(v, _depth=_depth + 1)
        return out
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_json(x, _depth=_depth + 1) for x in obj]
    if isinstance(obj, (bytes, bytearray)):
        try:
            return bytes(obj).decode("utf-8", errors="replace")
        except Exception:
            return ""
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        try:
            return str(obj)[:8000]
        except Exception:
            return ""


def _default_parsed_string_fields() -> dict[str, Any]:
    """Stable ``parsed`` shape for JSON (no missing string keys)."""
    return {
        "action": "",
        "entity_name": "",
        "value": "",
        "rationale": "",
        "numeric_value": None,
        "confidence": None,
    }


def finalize_dashboard_command_response(result: Any) -> dict[str, Any]:
    """
    Ensure API responses are JSON-serializable and shaped for the dashboard client.

    Strips Jinja2 ``Undefined``, normalizes ``parsed`` string fields to ``""`` when missing.
    """
    if result is None:
        result = {}
    if not isinstance(result, dict):
        return {
            "ok": False,
            "error": "invalid_executor_response",
            "parsed": _default_parsed_string_fields(),
            "executed": None,
            "result": None,
            "thought_message": None,
        }

    cleaned = _sanitize_for_json(result)
    if not isinstance(cleaned, dict):
        return {
            "ok": False,
            "error": "invalid_executor_response",
            "parsed": _default_parsed_string_fields(),
            "executed": None,
            "result": None,
            "thought_message": None,
        }

    # None -> {} yields an empty dict; treat as invalid executor payload (same as before).
    if cleaned == {}:
        return {
            "ok": False,
            "error": "invalid_executor_response",
            "parsed": _default_parsed_string_fields(),
            "executed": None,
            "result": None,
            "thought_message": None,
        }

    parsed = cleaned.get("parsed")
    if not isinstance(parsed, dict):
        cleaned["parsed"] = _default_parsed_string_fields()
        parsed = cleaned["parsed"]
    else:
        defaults = _default_parsed_string_fields()
        for key in ("action", "entity_name", "value", "rationale"):
            val = parsed.get(key)
            if val is None or _is_jinja_undefined(val):
                parsed[key] = defaults[key]
            else:
                parsed[key] = str(val)
        if "numeric_value" not in parsed or _is_jinja_undefined(parsed.get("numeric_value")):
            parsed["numeric_value"] = None
        conf = parsed.get("confidence")
        if conf is None or _is_jinja_undefined(conf):
            parsed["confidence"] = None
        else:
            try:
                parsed["confidence"] = float(conf)
            except (TypeError, ValueError):
                parsed["confidence"] = None
    try:
        json.dumps(cleaned)
    except TypeError:
        cleaned = json.loads(json.dumps(cleaned, default=str))

    return cleaned


_SYSTEM_PROMPT = """You are JARVIS — a universal ops console for an Indian SMB platform.
Users type free-form commands (typos OK). Respond with ONE JSON object only (no markdown fences).

Required keys (exact spelling):
- "action": one of the canonical actions below, or "unknown"
- "entity_name": string — company name when updating identity; otherwise often ""
- "value": string — GSTIN (15-char Indian GST) when updating tax id; or a free-text parameter
- "numeric_value": number or null — monthly infra budget in INR when setting budget; otherwise null
- "confidence": number from 0 to 1
- "rationale": one short English phrase

Canonical actions (use exact spelling):
- "update_company_identity" — set/rename company, GST/GSTIN, or both (Indian SMB).
- "run_sre_health_check" — system / SRE health, probes, status, "are we green", diagnostics overview.
- "set_operational_infra_budget" — set or lower/raise the monthly operational infra cap in INR (use numeric_value; e.g. "lower budget to 1000").
- "clear_thought_stream" — clear JARVIS thought log / reasoning feed / "clear logs" for the dashboard stream.
- "inventory_low_stock" — list SKUs below stock threshold, warehouse inventory alerts.
- "inventory_adjust" — add or remove stock for one SKU: put SKU name in entity_name (or value if name is long), signed delta in numeric_value (positive = receive/add, negative = remove/deduct); optional warehouse hint in value if entity_name holds the SKU.
- "trigger_solar_research" — run or refresh solar DPR market research (Tavily + cache); phrases like "run solar research", "refresh solar market". Put "refresh" or "force" in value when operator wants a fresh pull (bypass cache).
- "run_worker_autoscale" — run one worker autoscale cycle (queue + DO), when operator asks to scale/trigger autoscale.
- "set_predictive_scaling_mode" — set predictive scaling to AI or manual (put "ai" or "manual" in value).
- "run_auto_repair" — database self-heal: run Alembic migrations, reset organizations sequence (PostgreSQL), trigger Uvicorn reload/restart when configured. For **inventory sync only** after an audit, put "inventory_sync" in value (operator-approved correction apply).
- "run_inventory_integrity_audit" — full SKU integrity audit: on-hand vs bills + stock audit logs, negatives, orphans, correction deltas; writes **System: Audit Report** to the thought stream (no mutations).

If nothing matches safely, use "unknown" with empty entity_name and value and numeric_value null.

Rules:
- Never invent GST digits; copy only what the user gave (normalize spacing).
- For budget, put the INR amount in numeric_value when possible; else parse from value text.
- Prefer the most specific action when multiple could apply.
"""


def register_dashboard_command_handler(action: str, fn: Any) -> None:
    """Allow optional modules to register handlers (same as ``dashboard_command_registry``)."""
    _register_handler(action, fn)


def _ensure_plugins_loaded() -> None:
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED:
        return
    _PLUGINS_LOADED = True
    try:
        importlib.import_module("services.dashboard_command_plugins")
    except ImportError:
        pass


def _normalize_action(raw: str) -> str:
    a = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "set_corporate_identity": "update_company_identity",
        "add_company": "update_company_identity",
        "register_company": "update_company_identity",
        "update_company": "update_company_identity",
        "company_setup": "update_company_identity",
        "set_company": "update_company_identity",
        "set_gst": "update_company_identity",
        "update_gst": "update_company_identity",
        "health_check": "run_sre_health_check",
        "sre_health": "run_sre_health_check",
        "system_health": "run_sre_health_check",
        "check_health": "run_sre_health_check",
        "infra_budget": "set_operational_infra_budget",
        "set_budget": "set_operational_infra_budget",
        "update_budget": "set_operational_infra_budget",
        "clear_logs": "clear_thought_stream",
        "clear_thoughts": "clear_thought_stream",
        "inventory": "inventory_low_stock",
        "low_stock": "inventory_low_stock",
        "stock_alerts": "inventory_low_stock",
        "autoscale": "run_worker_autoscale",
        "scale_workers": "run_worker_autoscale",
        "trigger_autoscale": "run_worker_autoscale",
        "predictive_mode": "set_predictive_scaling_mode",
        "scaling_mode": "set_predictive_scaling_mode",
        "auto_repair": "run_auto_repair",
        "repair_database": "run_auto_repair",
        "database_repair": "run_auto_repair",
        "self_heal": "run_auto_repair",
        "selfheal": "run_auto_repair",
        "alembic_upgrade": "run_auto_repair",
        "migrate_database": "run_auto_repair",
        "fix_database": "run_auto_repair",
        "solar_research": "trigger_solar_research",
        "run_solar_research": "trigger_solar_research",
        "solar_dpr": "trigger_solar_research",
        "dpr_research": "trigger_solar_research",
        "adjust_inventory": "inventory_adjust",
        "add_stock": "inventory_adjust",
        "stock_adjust": "inventory_adjust",
        "update_inventory": "inventory_adjust",
        "inventory_integrity_audit": "run_inventory_integrity_audit",
        "inventory_audit": "run_inventory_integrity_audit",
        "stock_integrity_audit": "run_inventory_integrity_audit",
        "full_inventory_audit": "run_inventory_integrity_audit",
    }
    return aliases.get(a, a)


def _groq_extract_structured(user_text: str) -> dict[str, Any]:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("groq_not_configured")

    from groq import Groq

    model = (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
    client = Groq(api_key=key)
    user_msg = (
        f"Operator command (may contain typos):\n\n{(user_text or '').strip()[:_MAX_CHARS]}\n\n"
        "Return JSON with keys: action, entity_name, value, numeric_value, confidence, rationale."
    )
    try:
        chat = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        raw = (chat.choices[0].message.content or "").strip()
    except Exception as exc:
        _LOG.warning("dashboard_command_executor: groq failed: %s", exc)
        raise RuntimeError("groq_request_failed") from exc

    data = _extract_json_object(raw)
    if data is None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}

    nv = data.get("numeric_value")
    if nv is not None and not isinstance(nv, (int, float)):
        try:
            nv = float(str(nv).replace(",", ""))
        except (TypeError, ValueError):
            nv = None

    return {
        "action": _normalize_action(str(data.get("action") or "unknown")),
        "entity_name": str(data.get("entity_name") or "").strip(),
        "value": str(data.get("value") or "").strip(),
        "numeric_value": nv,
        "confidence": float(data.get("confidence") or 0) if data.get("confidence") is not None else 0.0,
        "rationale": str(data.get("rationale") or "")[:500],
    }


# Alias for callers / introspection
_groq_parse_command_intent = _groq_extract_structured


def _looks_like_auto_repair_command(text: str) -> bool:
    """Bypass Groq when the operator clearly asked for DB self-heal (works without GROQ_API_KEY)."""
    tl = (text or "").strip().lower()
    if not tl:
        return False
    needles = (
        "auto repair",
        "auto-repair",
        "autorepair",
        "self heal",
        "self-heal",
        "repair database",
        "db repair",
        "database repair",
        "heal database",
        "fix database",
        "alembic upgrade",
        "migrate database",
        "run migrations",
        "schema repair",
    )
    return any(n in tl for n in needles)


def _parsed_run_auto_repair(*, value: str = "") -> dict[str, Any]:
    return {
        "action": "run_auto_repair",
        "entity_name": "",
        "value": (value or "").strip(),
        "numeric_value": None,
        "confidence": 1.0,
        "rationale": "auto_repair_keyword_or_pulse_shortcut",
    }


def _looks_like_inventory_sync_command(text: str) -> bool:
    tl = (text or "").strip().lower().replace("-", "_")
    if "inventory_sync" in tl:
        return True
    return "inventory" in tl and "sync" in tl and any(
        k in tl for k in ("auto_repair", "auto repair", "run_auto_repair", "repair")
    )


def _looks_like_inventory_integrity_audit_command(text: str) -> bool:
    tl = (text or "").strip().lower()
    if not tl:
        return False
    phrases = (
        "inventory integrity",
        "integrity audit",
        "full inventory audit",
        "inventory integrity audit",
        "sku integrity",
        "stock integrity audit",
        "jarvis inventory audit",
        "compare on hand",
        "compare on-hand",
        "transaction log",
        "audit all sku",
        "audit all skus",
    )
    return any(p in tl for p in phrases)

_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z0-9]{13}$", re.I)
_DIGITS_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def _merge_identity_fields(
    *,
    organization_id: int,
    entity_name: str,
    value_gst: str,
) -> tuple[str, str]:
    cur = get_corporate_economics_context(int(organization_id))
    cur_name = (cur.get("company_name") or "").strip()
    cur_gst = (cur.get("gst_number") or "").strip()

    name = (entity_name or "").strip()
    gst = (value_gst or "").strip().replace(" ", "").upper()

    if not name:
        name = cur_name
    if not gst:
        gst = cur_gst

    return name, gst


def _parse_budget_inr(parsed: dict[str, Any]) -> str | None:
    nv = parsed.get("numeric_value")
    if nv is not None:
        try:
            d = Decimal(str(nv)).quantize(Decimal("0.01"))
            if d > 0:
                return str(d)
        except (InvalidOperation, ValueError, TypeError):
            pass
    val = (parsed.get("value") or "").strip()
    m = _DIGITS_RE.search(val.replace(",", ""))
    if m:
        try:
            d = Decimal(m.group(0).replace(",", "")).quantize(Decimal("0.01"))
            if d > 0:
                return str(d)
        except (InvalidOperation, ValueError):
            pass
    return None


def _base_out(parsed: dict[str, Any]) -> dict[str, Any]:
    action = parsed.get("action") or "unknown"
    return {
        "ok": True,
        "parsed": {
            "action": action,
            "entity_name": parsed.get("entity_name") or "",
            "value": parsed.get("value") or "",
            "numeric_value": parsed.get("numeric_value"),
            "confidence": parsed.get("confidence"),
            "rationale": parsed.get("rationale") or "",
        },
        "executed": None,
        "result": None,
        "thought_message": None,
    }


def _route_mutation_to_brain_execute(
    *,
    raw_command: str,
    organization_id: int,
    parsed: dict[str, Any],
    executor_context: dict[str, Any] | None,
) -> dict[str, Any]:
    out = _base_out(parsed)
    xctx = dict(executor_context or {})
    uid = int(xctx.get("user_id") or 0)
    if uid <= 0:
        out["ok"] = False
        out["error"] = "single_execution_authority_requires_user_id"
        out["thought_message"] = "System: Mutating commands require authenticated user context for brain routing."
        return out
    try:
        from services.brain_execute import brain_execute

        routed = brain_execute(
            str(raw_command or "").strip()[:2000],
            uid,
            int(organization_id),
        )
    except Exception as exc:
        _LOG.exception("brain routing failed for dashboard command")
        out["ok"] = False
        out["error"] = f"brain_route_failed:{type(exc).__name__}"
        out["thought_message"] = "System: Brain routing failed for this command."
        return out
    out["ok"] = bool((routed.get("result") or {}).get("ok"))
    out["executed"] = "brain_execute"
    out["result"] = {
        "brain_status": routed.get("status"),
        "brain_result": routed.get("result"),
        "closure": routed.get("closure"),
    }
    out["thought_message"] = "System: Command routed to central execution authority."
    return out


def _handle_update_company_identity(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = sre_profile
    out = _base_out(parsed)
    entity_name = str(parsed.get("entity_name") or "").strip()
    value_gst = str(parsed.get("value") or "").strip()

    merged_name, merged_gst = _merge_identity_fields(
        organization_id=int(organization_id),
        entity_name=entity_name,
        value_gst=value_gst,
    )

    if not merged_name:
        out["ok"] = False
        out["error"] = "company_name_required_after_merge"
        out["thought_message"] = "System: Could not resolve company name for identity update (set name or GST context)."
        return out

    if merged_gst and not _GSTIN_RE.match(merged_gst):
        strict = (os.getenv("THIRAMAI_DASHBOARD_COMMAND_STRICT_GST") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if strict:
            out["ok"] = False
            out["error"] = "invalid_gstin_format"
            out["thought_message"] = "System: GST value did not match 15-char GSTIN pattern; not saved."
            return out

    try:
        saved = persist_corporate_identity(
            int(organization_id),
            company_name=merged_name,
            gst_number=merged_gst or "",
        )
    except ValueError as exc:
        out["ok"] = False
        out["error"] = str(exc)
        out["thought_message"] = f"System: Identity update failed ({exc})."
        return out
    except RuntimeError:
        out["ok"] = False
        out["error"] = "database_not_configured"
        out["thought_message"] = "System: Database not configured; identity not saved."
        return out

    display = (saved.get("company_name") or merged_name or "organization").strip()
    out["executed"] = "persist_corporate_identity"
    out["result"] = saved
    out["thought_message"] = f"System: Corporate identity updated for {display}."
    return out


def _handle_run_sre_health_check(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = organization_id
    out = _base_out(parsed)
    from services.sre_health_report import build_sre_health_report

    prof = sre_profile if sre_profile in ("development", "production") else "development"
    try:
        report = build_sre_health_report(profile=prof, write_reflection=False)
    except Exception as exc:
        out["ok"] = False
        out["error"] = "sre_report_failed"
        out["thought_message"] = f"System: SRE health check failed ({type(exc).__name__})."
        return out

    chk = report.get("checks") or {}
    if isinstance(chk, dict):
        chk_summary = {k: (v.get("ok") if isinstance(v, dict) else None) for k, v in list(chk.items())[:40]}
    else:
        chk_summary = {}

    out["executed"] = "build_sre_health_report"
    out["result"] = {
        "overall_ok": bool(report.get("ok")),
        "profile": report.get("profile"),
        "failure_reasons": list(report.get("failure_reasons") or [])[:12],
        "checks_ok_preview": chk_summary,
    }
    green = "GREEN" if report.get("ok") else "RED"
    out["thought_message"] = f"System: SRE health snapshot ({green}) profile={prof}."
    return out


def _handle_set_operational_infra_budget(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = organization_id, sre_profile
    out = _base_out(parsed)
    cap = _parse_budget_inr(parsed)
    if not cap:
        out["ok"] = False
        out["error"] = "budget_amount_unparsed"
        out["thought_message"] = "System: Could not parse monthly infra budget (INR) from command."
        return out

    from services.dashboard_ops_state import set_operational_infra_budget_inr_override

    try:
        set_operational_infra_budget_inr_override(cap)
    except ValueError:
        out["ok"] = False
        out["error"] = "budget_amount_required"
        out["thought_message"] = "System: Invalid budget amount."
        return out

    out["executed"] = "set_operational_infra_budget_inr_override"
    out["result"] = {"budget_cap_inr": cap, "source": "var_override"}
    out["thought_message"] = f"System: Operational infra budget cap set to ₹{cap} INR (persisted)."
    return out


def _handle_clear_thought_stream(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = organization_id, sre_profile
    out = _base_out(parsed)
    from services.thought_stream import clear_thought_stream

    cleared = clear_thought_stream()
    out["executed"] = "clear_thought_stream"
    out["result"] = {"ok": bool(cleared.get("ok")), "thought_count": len(cleared.get("thoughts") or [])}
    out["thought_message"] = "System: Thought stream cleared."
    return out


def _handle_run_worker_autoscale(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = organization_id, parsed, sre_profile
    out = _base_out(parsed)
    from services.do_worker_autoscale import run_autoscale_once

    try:
        result = run_autoscale_once()
    except Exception as exc:
        _LOG.exception("run_autoscale_once failed")
        out["ok"] = False
        out["error"] = "autoscale_failed"
        out["thought_message"] = f"System: Autoscale error ({type(exc).__name__})."
        return out

    out["executed"] = "run_autoscale_once"
    out["result"] = result
    act = (result or {}).get("action")
    out["thought_message"] = f"System: Autoscale run finished (action={act!r})."
    return out


def _handle_run_auto_repair(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    out = _base_out(parsed)
    prof = sre_profile if sre_profile in ("development", "production") else "development"
    raw = f"{parsed.get('value') or ''} {parsed.get('entity_name') or ''}".strip().lower()
    raw_norm = raw.replace("-", "_")
    target = "inventory_sync" if "inventory_sync" in raw_norm else None
    try:
        from services.auto_repair import run_auto_repair

        result = run_auto_repair(
            profile=prof,
            force=True,
            target=target,
            organization_id=int(organization_id) if target else None,
        )
    except Exception as exc:
        _LOG.exception("run_auto_repair failed")
        out["ok"] = False
        out["error"] = "auto_repair_failed"
        out["thought_message"] = f"System: Auto-repair failed ({type(exc).__name__})."
        return out

    out["executed"] = "run_auto_repair"
    out["result"] = result
    if target == "inventory_sync":
        step = next(
            (
                s
                for s in (result.get("steps") or [])
                if isinstance(s, dict) and s.get("step") == "inventory_sync"
            ),
            {},
        )
        n_applied = len(step.get("applied") or [])
        errs = step.get("errors") or []
        out["thought_message"] = (
            f"System: inventory_sync finished — {n_applied} correction(s) applied."
            + (f" Errors: {len(errs)}." if errs else "")
        )
        out["ok"] = bool(result.get("ok", True))
        return out

    alembic_ok = True
    for step in result.get("steps") or []:
        if isinstance(step, dict) and step.get("step") == "alembic":
            alembic_ok = bool(step.get("ok"))
            break
    tail = "migrations OK" if alembic_ok else "Alembic reported an error — see result.steps"
    out["thought_message"] = f"System: Auto-repair finished ({tail}); sequence + restart attempted."
    out["ok"] = bool(result.get("ok", True))
    return out


def _handle_run_inventory_integrity_audit(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = sre_profile
    out = _base_out(parsed)
    try:
        from services.inventory_integrity_audit import emit_audit_report_to_thought_stream

        audit = emit_audit_report_to_thought_stream(int(organization_id))
    except Exception as exc:
        _LOG.exception("inventory_integrity_audit failed")
        out["ok"] = False
        out["error"] = "inventory_integrity_audit_failed"
        out["thought_message"] = f"System: Inventory audit failed ({type(exc).__name__})."
        return out

    if not audit.get("ok"):
        out["ok"] = False
        out["error"] = str(audit.get("error") or "audit_failed")
        out["thought_message"] = "System: Inventory audit could not complete (see error)."
        return out

    mc = int(audit.get("mismatch_count") or 0)
    nc = len(audit.get("corrections") or [])
    out["executed"] = "run_full_inventory_integrity_audit"
    out["result"] = {
        "mismatch_count": mc,
        "corrections_planned": nc,
        "negative_stock_rows": len(audit.get("negative_stock_rows") or []),
        "orphaned_bill_skus": len(audit.get("orphaned_bill_skus") or []),
        "pending_operator_approval": bool(audit.get("pending_operator_approval")),
        "approval_hint": audit.get("approval_hint"),
    }
    out["thought_message"] = (
        f"System: Audit Report posted to thought stream — {mc} mismatch signal(s), "
        f"{nc} auto-correction delta(s) planned. Approve **run_auto_repair** with value **inventory_sync** to apply."
    )
    return out


def _handle_set_predictive_scaling_mode(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = organization_id, sre_profile
    out = _base_out(parsed)
    from services.dashboard_ops_state import set_predictive_scaling_mode

    raw = f"{parsed.get('value') or ''} {parsed.get('entity_name') or ''}".strip().lower()
    if any(x in raw for x in ("manual", "off", "disable", "human")):
        mode = "manual"
    elif any(x in raw for x in ("ai", "auto", "enable", "on")):
        mode = "ai"
    else:
        out["ok"] = False
        out["error"] = "predictive_mode_unparsed"
        out["thought_message"] = "System: Say 'predictive manual' or 'predictive AI' to switch mode."
        return out

    normalized = set_predictive_scaling_mode(mode)
    out["executed"] = "set_predictive_scaling_mode"
    out["result"] = {"predictive_mode": normalized}
    out["thought_message"] = f"System: Predictive scaling mode set to {normalized.upper()}."
    return out


def _handle_inventory_low_stock(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = sre_profile, parsed
    out = _base_out(parsed)
    from services.analytics_service import list_low_stock_alerts_sync

    snap = list_low_stock_alerts_sync(int(organization_id), threshold=5, limit=50)
    items = snap.get("items") or []
    out["executed"] = "list_low_stock_alerts_sync"
    out["result"] = {
        "ok": snap.get("ok"),
        "error": snap.get("error"),
        "item_count": len(items),
        "sample": items[:15],
    }
    out["thought_message"] = f"System: Low-stock query — {len(items)} SKU(s) below threshold."
    return out


def _handle_trigger_solar_research(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = organization_id, sre_profile
    out = _base_out(parsed)
    from services.market_research_service import fetch_solar_dpr_research_bundle, format_solar_dpr_bundle_markdown

    raw_v = f"{parsed.get('value') or ''} {parsed.get('entity_name') or ''}".strip().lower()
    force = any(
        x in raw_v for x in ("force", "refresh", "reload", "bypass", "hard", "true", "1", "yes")
    )
    try:
        bundle = fetch_solar_dpr_research_bundle(force_refresh=force)
    except Exception as exc:
        _LOG.exception("trigger_solar_research failed")
        out["ok"] = False
        out["error"] = "solar_research_failed"
        out["thought_message"] = f"System: Solar research failed ({type(exc).__name__})."
        return out

    md = format_solar_dpr_bundle_markdown(bundle)
    out["executed"] = "fetch_solar_dpr_research_bundle"
    out["result"] = {
        "ok": True,
        "initial_capex_estimate_inr": bundle.get("initial_capex_estimate_inr"),
        "initial_capex_low_inr": bundle.get("initial_capex_low_inr"),
        "initial_capex_high_inr": bundle.get("initial_capex_high_inr"),
        "initial_capex_note": bundle.get("initial_capex_note"),
        "query_count": len(bundle.get("queries") or []),
        "cache": bundle.get("cache"),
        "markdown": md,
    }
    # Full markdown for operator console (JSON) + structured UI hook; thought_stream may truncate duplicate (see API).
    out["thought_message"] = md
    out["ui_display_data"] = {
        "schema": "thiramai.ui_display.markdown.v1",
        "kind": "solar_dpr_market_research",
        "format": "markdown",
        "markdown": md,
        "title": "Solar DPR market research",
    }
    return out


def _handle_inventory_adjust(
    *,
    organization_id: int,
    parsed: dict[str, Any],
    sre_profile: str,
) -> dict[str, Any]:
    _ = sre_profile
    out = _base_out(parsed)
    sku = str(parsed.get("entity_name") or "").strip() or str(parsed.get("value") or "").strip()
    if not sku:
        out["ok"] = False
        out["error"] = "inventory_sku_required"
        out["thought_message"] = "System: inventory_adjust needs a SKU in entity_name (or value)."
        return out

    nv = parsed.get("numeric_value")
    delta: Decimal | None = None
    if nv is not None:
        try:
            delta = Decimal(str(nv))
        except (InvalidOperation, TypeError, ValueError):
            delta = None
    if delta is None:
        val_only = str(parsed.get("value") or "").strip()
        if sku and val_only and val_only.lower() != sku.lower():
            m = _DIGITS_RE.search(val_only.replace(",", ""))
            if m:
                try:
                    delta = Decimal(m.group(0).replace(",", ""))
                except (InvalidOperation, ValueError):
                    delta = None
    if delta is None or delta == 0:
        out["ok"] = False
        out["error"] = "inventory_delta_unparsed"
        out["thought_message"] = "System: Could not parse signed stock delta (numeric_value)."
        return out

    loc = ""
    en = str(parsed.get("entity_name") or "").strip()
    val = str(parsed.get("value") or "").strip()
    if (
        en
        and val
        and val.lower() != en.lower()
        and _DIGITS_RE.fullmatch(val.replace(",", "").strip()) is None
    ):
        loc = val

    from sqlalchemy.exc import InvalidRequestError
    from sqlalchemy.orm.exc import DetachedInstanceError

    from core.database import db_session
    from services.inventory_ops import apply_inventory_delta

    nq: float
    try:
        with db_session() as session:
            try:
                with session.begin():
                    item = apply_inventory_delta(
                        session,
                        organization_id=int(organization_id),
                        sku_name=sku,
                        location=loc,
                        delta=delta,
                    )
                session.refresh(item)
                nq = float(item.quantity)
            except DetachedInstanceError as exc:
                _LOG.warning("inventory_adjust ORM detached: %s", exc)
                out["ok"] = False
                out["error"] = "inventory_orm_detached"
                out["thought_message"] = (
                    f"System: Inventory row detached after update ({type(exc).__name__})."
                )
                return out
            except InvalidRequestError as exc:
                msg = str(exc).lower()
                if any(s in msg for s in ("detached", "not bound to a session", "not persistent")):
                    _LOG.warning("inventory_adjust ORM invalid request: %s", exc)
                    out["ok"] = False
                    out["error"] = "inventory_orm_detached"
                    out["thought_message"] = (
                        f"System: ORM session error after stock adjust ({type(exc).__name__})."
                    )
                    return out
                raise
    except RuntimeError as exc:
        if "DATABASE_URL" in str(exc) or "not set" in str(exc).lower():
            out["ok"] = False
            out["error"] = "database_not_configured"
            out["thought_message"] = "System: Database not configured; stock not adjusted."
            return out
        raise
    except ValueError as exc:
        out["ok"] = False
        out["error"] = "inventory_adjust_rejected"
        out["thought_message"] = f"System: {exc}"
        return out
    except Exception as exc:
        _LOG.exception("inventory_adjust failed")
        out["ok"] = False
        out["error"] = "inventory_adjust_failed"
        out["thought_message"] = f"System: Stock adjust error ({type(exc).__name__})."
        return out

    out["executed"] = "apply_inventory_delta"
    out["result"] = {"sku_name": sku, "new_quantity": nq, "delta": str(delta), "location": loc or "(any)"}
    out["thought_message"] = f"System: Stock adjusted `{sku}` by {delta} → on-hand **{nq}**."
    return out


def _register_builtin_handlers() -> None:
    _register_handler("run_sre_health_check", _handle_run_sre_health_check)
    _register_handler("set_operational_infra_budget", _handle_set_operational_infra_budget)
    _register_handler("clear_thought_stream", _handle_clear_thought_stream)
    _register_handler("inventory_low_stock", _handle_inventory_low_stock)
    _register_handler("run_inventory_integrity_audit", _handle_run_inventory_integrity_audit)
    _register_handler("trigger_solar_research", _handle_trigger_solar_research)
    _register_handler("inventory_adjust", _handle_inventory_adjust)
    _register_handler("run_worker_autoscale", _handle_run_worker_autoscale)
    _register_handler("set_predictive_scaling_mode", _handle_set_predictive_scaling_mode)
    _register_handler("run_auto_repair", _handle_run_auto_repair)


_register_builtin_handlers()


def _execute_natural_language_dashboard_command_raw(
    *,
    raw_command: str,
    organization_id: int,
    sre_profile: str = "development",
    executor_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inner implementation; use ``execute_natural_language_dashboard_command`` for JSON-safe output."""
    _ensure_plugins_loaded()
    text = (raw_command or "").strip()
    if not text:
        return {
            "ok": False,
            "error": "empty_command",
            "parsed": None,
            "executed": None,
            "thought_message": None,
        }

    if _looks_like_inventory_sync_command(text):
        return _route_mutation_to_brain_execute(
            raw_command=text,
            organization_id=int(organization_id),
            parsed=_parsed_run_auto_repair(value="inventory_sync"),
            executor_context=executor_context,
        )

    if _looks_like_inventory_integrity_audit_command(text):
        return _handle_run_inventory_integrity_audit(
            organization_id=int(organization_id),
            parsed={
                "action": "run_inventory_integrity_audit",
                "entity_name": "",
                "value": "",
                "numeric_value": None,
                "confidence": 1.0,
                "rationale": "keyword_inventory_integrity_audit",
            },
            sre_profile=sre_profile,
        )

    if _looks_like_auto_repair_command(text):
        parsed_auto = _parsed_run_auto_repair()
        uid = int((executor_context or {}).get("user_id") or 0)
        if uid <= 0:
            return _handle_run_auto_repair(
                organization_id=int(organization_id),
                parsed=parsed_auto,
                sre_profile=sre_profile,
            )
        return _route_mutation_to_brain_execute(
            raw_command=text,
            organization_id=int(organization_id),
            parsed=parsed_auto,
            executor_context=executor_context,
        )

    from core.sale_intent_heuristic import (
        parsed_solar_research_intent_from_message,
        parsed_update_stock_intent_from_message,
    )

    sol_hint = parsed_solar_research_intent_from_message(text)
    if sol_hint is not None:
        return _handle_trigger_solar_research(
            organization_id=int(organization_id),
            parsed={
                "action": "trigger_solar_research",
                "entity_name": "",
                "value": "force_refresh" if sol_hint.force_refresh else "",
                "numeric_value": None,
                "confidence": 1.0,
                "rationale": "keyword_trigger_solar_research",
            },
            sre_profile=sre_profile,
        )

    inv_hint = parsed_update_stock_intent_from_message(text)
    if inv_hint is not None:
        parsed_adjust = {
                "action": "inventory_adjust",
                "entity_name": inv_hint.sku_name,
                "value": inv_hint.location or "",
                "numeric_value": float(inv_hint.quantity_delta),
                "confidence": 1.0,
                "rationale": "keyword_inventory_adjust",
            }
        return _route_mutation_to_brain_execute(
            raw_command=text,
            organization_id=int(organization_id),
            parsed=parsed_adjust,
            executor_context=executor_context,
        )

    try:
        parsed = _groq_extract_structured(text)
    except RuntimeError as exc:
        code = str(exc)
        return {
            "ok": False,
            "error": code,
            "parsed": None,
            "executed": None,
            "thought_message": None,
        }

    action = parsed.get("action") or "unknown"
    if action in _MUTATING_ACTIONS:
        uid = int((executor_context or {}).get("user_id") or 0)
        if uid > 0 or action not in _ALLOW_ANON_MUTATING_ACTIONS:
            return _route_mutation_to_brain_execute(
                raw_command=text,
                organization_id=int(organization_id),
                parsed=parsed,
                executor_context=executor_context,
            )
    custom = get_dashboard_command_handler(action)
    if custom is not None:
        try:
            return custom(organization_id=int(organization_id), parsed=parsed, sre_profile=sre_profile)
        except Exception as exc:
            _LOG.exception("dashboard_command handler %s failed", action)
            out = _base_out(parsed)
            out["ok"] = False
            out["error"] = "handler_exception"
            out["thought_message"] = f"System: Command handler error ({type(exc).__name__})."
            return out

    if action == "update_company_identity":
        return _handle_update_company_identity(
            organization_id=organization_id, parsed=parsed, sre_profile=sre_profile
        )

    if action == "unknown":
        from core.sale_intent_heuristic import early_retail_sell_quantity_veto_message

        veto = early_retail_sell_quantity_veto_message(text)
        if veto:
            out = _base_out(parsed)
            out["ok"] = False
            out["status"] = "error"
            out["action"] = "unknown"
            out["message"] = veto.strip()
            out["data"] = {"error": "retail_quantity_veto"}
            out["thought_message"] = veto.strip()
            out["error"] = "retail_quantity_veto"
            return out

        from core.intent_engine import resolve_intent

        resolved = resolve_intent(text, skip_llm=True)
        if resolved.get("intent") != "unknown":
            return _route_mutation_to_brain_execute(
                raw_command=text,
                organization_id=int(organization_id),
                parsed={
                    "action": "intent_engine_routed",
                    "entity_name": str(resolved.get("entity") or ""),
                    "value": "",
                    "numeric_value": resolved.get("quantity"),
                    "confidence": resolved.get("confidence"),
                    "rationale": "intent_engine_route_to_brain",
                },
                executor_context=executor_context,
            )

        out = _base_out(parsed)
        out["thought_message"] = (
            "System: Intent unclear — try company/GST, health, budget INR, clear thoughts, low stock, "
            "stock adjust (SKU + delta), solar DPR research, inventory integrity audit, or inventory_sync repair."
        )
        return out

    out = _base_out(parsed)
    out["thought_message"] = f"System: No handler for action {action!r} (extend dashboard_command_plugins)."
    return out


def execute_natural_language_dashboard_command(
    *,
    raw_command: str,
    organization_id: int,
    sre_profile: str = "development",
    executor_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Parse ``raw_command`` with Groq, dispatch to handlers, return a **JSON-serializable** dict.

    ``executor_context`` (optional): ``user_id``, ``actor_role_name``, ``role_level``, ``correlation_id``
    for intent-engine tool execution (retail sell policy, audit).
    """
    try:
        raw = _execute_natural_language_dashboard_command_raw(
            raw_command=raw_command,
            organization_id=organization_id,
            sre_profile=sre_profile,
            executor_context=executor_context,
        )
    except Exception as exc:
        _LOG.exception("execute_natural_language_dashboard_command failed")
        raw = {
            "ok": False,
            "error": "executor_exception",
            "parsed": None,
            "executed": None,
            "result": None,
            "thought_message": f"System: {type(exc).__name__}",
        }
    return finalize_dashboard_command_response(raw)

