"""
Controlled autonomous cycle: observe → think → decide → safety filter → act → learn.

Execution mutates state **only** when ``context["auto_mode"]`` is true. Financial sells are never
auto-run from this loop. All steps emit structured logs for audit.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from core.observability import log_structured, new_request_id

# Intents that may be passed to ``execute_intent`` after safety filtering.
_SAFE_EXECUTE_INTENTS = frozenset({"read_inventory", "add_inventory"})
# Blocked from any automatic execution path (manual / HITL only).
_FORBIDDEN_AUTO_INTENTS = frozenset({"sell_inventory", "unknown"})


def _truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_money(s: Any) -> Decimal:
    try:
        return Decimal(str(s).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _inventory_row_count(organization_id: int) -> int:
    try:
        from sqlalchemy import func, select

        from core.database import get_session_factory
        from core.db.models import Inventory

        factory = get_session_factory()
        if factory is None:
            return 0
        oid = int(organization_id)
        with factory() as session:
            q = select(func.count()).select_from(Inventory).where(Inventory.organization_id == oid)
            n = session.execute(q).scalar()
        return int(n or 0)
    except Exception:
        return 0


def _observe(context: dict[str, Any]) -> dict[str, Any]:
    """Collect tenant-visible state using existing services (read-mostly)."""
    oid = int(context.get("organization_id") or 0)
    state: dict[str, Any] = {"organization_id": oid, "ts": time.time()}
    if oid <= 0:
        state["error"] = "missing_organization_id"
        return state

    thr_raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip()
    try:
        thr = max(0, min(10_000, int(thr_raw)))
    except ValueError:
        thr = 5

    try:
        from services.analytics_service import compute_dashboard_summary_sync, list_low_stock_alerts_sync

        state["low_stock"] = list_low_stock_alerts_sync(oid, threshold=thr, limit=50)
        state["dashboard"] = compute_dashboard_summary_sync(oid, low_stock_threshold=thr)
    except Exception as exc:
        state["low_stock"] = {"ok": False, "error": str(exc)}
        state["dashboard"] = {"ok": False, "error": str(exc)}

    try:
        from workers.alert_system import list_active_alerts_for_organization

        state["notifications"] = list_active_alerts_for_organization(organization_id=oid, limit=80)
    except Exception as exc:
        state["notifications"] = {"ok": False, "error": str(exc), "items": []}

    try:
        from services.experience_buffer import recent_experience_entries

        state["recent_experiences"] = recent_experience_entries(organization_id=oid, limit=15)
    except Exception as exc:
        state["recent_experiences"] = {"error": str(exc)}

    state["inventory_row_count"] = _inventory_row_count(oid)
    return state


def observe_tenant_state(context: dict[str, Any]) -> dict[str, Any]:
    """Public tenant snapshot for multi-agent / planners (same data as autonomous observe)."""
    return _observe(context)


def _think(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive problem / opportunity signals from observed state."""
    problems: list[dict[str, Any]] = []
    oid = int(state.get("organization_id") or 0)
    if oid <= 0:
        return [{"problem": "invalid_context", "priority": "high", "detail": {}}]

    low = state.get("low_stock") if isinstance(state.get("low_stock"), dict) else {}
    if low.get("ok") and int(low.get("count") or 0) > 0:
        problems.append(
            {
                "problem": "low_stock",
                "priority": "high",
                "detail": {"count": low.get("count"), "threshold": low.get("threshold")},
            }
        )

    notes = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}
    for item in notes.get("items") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        blob = f"{item.get('title') or ''} {item.get('body') or ''}".lower()
        if "gst" in kind.lower() or "gst" in blob:
            problems.append(
                {
                    "problem": "gst_pending",
                    "priority": "medium",
                    "detail": {"notification_id": item.get("id"), "kind": kind},
                }
            )
        elif kind == "debt_overdue":
            problems.append(
                {
                    "problem": "debt_overdue",
                    "priority": "high",
                    "detail": {"notification_id": item.get("id"), "kind": kind},
                }
            )

    dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
    if dash.get("ok"):
        rev = dash.get("revenue_inr") or {}
        today = _parse_money(rev.get("today"))
        month = _parse_money(rev.get("this_month"))
        top = dash.get("top_selling_products") or []
        inv_rows = int(state.get("inventory_row_count") or 0)
        hour_utc = time.gmtime().tm_hour
        min_hour = int((os.getenv("THIRAMAI_AUTONOMOUS_NO_SALES_MIN_HOUR_UTC") or "12").strip() or "12")
        if (
            today == 0
            and inv_rows > 0
            and hour_utc >= min_hour
            and (month > 0 or len(top) > 0)
        ):
            problems.append(
                {
                    "problem": "no_sales",
                    "priority": "medium",
                    "detail": {"revenue_today_inr": str(today), "min_hour_utc": min_hour},
                }
            )

    return problems


def _decide(problems: list[dict[str, Any]], context: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Map signals + ``evaluate_autonomy`` into concrete action records."""
    from core.autonomy_engine import evaluate_autonomy

    actions: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for row in evaluate_autonomy(context):
        key = (row.get("intent"), row.get("reason"), row.get("entity"), row.get("quantity"))
        if key in seen:
            continue
        seen.add(key)
        actions.append({**row, "kind": "tool"})

    gst_seen = any(p.get("problem") == "gst_pending" for p in problems)
    if gst_seen and not any(a.get("reason") == "gst_pending_or_review" for a in actions):
        actions.append(
            {
                "intent": "notify_operator",
                "reason": "gst_compliance_review",
                "entity": "",
                "quantity": None,
                "priority": "high",
                "kind": "notify",
            }
        )

    if any(p.get("problem") == "no_sales" for p in problems):
        actions.append(
            {
                "intent": "suggest_operator_action",
                "reason": "no_sales_today_review_marketing_or_pos",
                "entity": "",
                "quantity": None,
                "priority": "medium",
                "kind": "suggestion",
            }
        )

    if any(p.get("problem") == "debt_overdue" for p in problems):
        actions.append(
            {
                "intent": "notify_operator",
                "reason": "debt_overdue_follow_up",
                "entity": "",
                "quantity": None,
                "priority": "high",
                "kind": "notify",
            }
        )

    return actions


def _safety_partition(actions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split into tool-executable (subject to auto_mode) vs audit-only suggestions."""
    to_run: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    for a in actions:
        kind = str(a.get("kind") or "tool")
        intent = str(a.get("intent") or "unknown")
        if kind in ("notify", "suggestion"):
            suggestions.append({**a, "_safety": "non_executable_kind"})
            continue
        if intent in _FORBIDDEN_AUTO_INTENTS:
            suggestions.append({**a, "_safety": "forbidden_intent"})
            continue
        if intent not in _SAFE_EXECUTE_INTENTS:
            suggestions.append({**a, "_safety": "intent_not_allowed_in_autonomous_loop"})
            continue
        to_run.append(a)
    return to_run, suggestions


def _log_experience(
    *,
    organization_id: int,
    action: str,
    result: dict[str, Any],
    success: bool,
    request_id: str | None,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    try:
        from services.experience_buffer import record_experience

        meta = {"organization_id": int(organization_id), "request_id": request_id}
        if extra_meta:
            meta.update(extra_meta)
        record_experience(
            source="autonomous",
            action=action,
            result=result,
            success=success,
            meta=meta,
            tags=["autonomous_cycle", f"org:{int(organization_id)}"],
        )
    except Exception:
        pass


def run_autonomous_cycle(context: dict[str, Any]) -> dict[str, Any]:
    """
    Run one full cycle for a single organization (``context["organization_id"]``).

    Required context keys:
    - ``organization_id`` (int)

    Optional:
    - ``auto_mode`` (bool): when true, safe tool intents run via ``execute_intent`` (policy inside).
    - ``actor_role_name``, ``user_id``, ``role_level``, ``correlation_id`` — forwarded to tools.
    """
    from core.tool_executor import execute_intent

    request_id = new_request_id()
    oid = int(context.get("organization_id") or 0)
    auto_mode = _truthy(context.get("auto_mode"))

    state = _observe(context)
    problems = _think(state)
    planned = _decide(problems, context, state)
    to_run, suggestion_bucket = _safety_partition(planned)

    actions_taken: list[dict[str, Any]] = []
    learning_logged = False

    log_structured(
        "autonomous_cycle.start",
        request_id=request_id,
        organization_id=oid,
        problems=len(problems),
        planned=len(planned),
        auto_mode=auto_mode,
    )

    if auto_mode and oid > 0:
        exec_ctx = {
            "organization_id": oid,
            "actor_role_name": context.get("actor_role_name") or "owner",
            "user_id": context.get("user_id"),
            "role_level": context.get("role_level"),
            "user_message": "",
            "correlation_id": context.get("correlation_id") or request_id,
            "experience_source": "autonomous",
        }
        for act in to_run[:12]:
            intent_data: dict[str, Any] = {
                "intent": act.get("intent"),
                "entity": act.get("entity") or "",
                "quantity": act.get("quantity"),
                "confidence": float(act.get("confidence") or 1.0),
                "source": "autonomous_loop",
            }
            if act.get("intent") == "read_inventory":
                intent_data["read_mode"] = act.get("read_mode") or "snapshot"
            if str(act.get("intent")) == "add_inventory" and act.get("location"):
                intent_data["location"] = str(act.get("location"))
            ref = act.get("reference")
            if isinstance(ref, dict) and ref.get("location"):
                intent_data.setdefault("location", str(ref.get("location")))

            out = execute_intent(intent_data, exec_ctx)
            entry = {
                "intent": intent_data.get("intent"),
                "entity": intent_data.get("entity"),
                "ok": bool(out.get("ok")),
                "message": out.get("message"),
            }
            actions_taken.append(entry)
            log_structured(
                "autonomous_cycle.action",
                request_id=request_id,
                organization_id=oid,
                intent=intent_data.get("intent"),
                ok=entry["ok"],
            )
    else:
        for act in to_run:
            suggestion_bucket.append({**act, "_held": "auto_mode_off"})

    for sug in suggestion_bucket:
        log_structured(
            "autonomous_cycle.suggestion",
            request_id=request_id,
            organization_id=oid,
            intent=sug.get("intent"),
            reason=sug.get("reason"),
            safety=sug.get("_safety") or sug.get("_held"),
        )

    if oid > 0:
        summary_actions = [
            {"intent": x.get("intent"), "ok": x.get("ok"), "entity": x.get("entity")}
            for x in actions_taken[:20]
        ]
        summary_sug = [
            {
                "intent": x.get("intent"),
                "reason": x.get("reason"),
                "note": x.get("_safety") or x.get("_held"),
            }
            for x in suggestion_bucket[:30]
        ]
        _log_experience(
            organization_id=oid,
            action="autonomous_cycle",
            result={
                "status": "cycle_complete",
                "actions_taken": summary_actions,
                "suggestions": summary_sug,
                "problems": [p.get("problem") for p in problems],
            },
            success=True,
            request_id=request_id,
        )
        learning_logged = True

    out = {
        "status": "cycle_complete",
        "state": state,
        "problems": problems,
        "actions_planned": planned,
        "actions_taken": actions_taken,
        "suggestions": suggestion_bucket,
        "learning_logged": learning_logged,
        "organization_id": oid,
        "request_id": request_id,
        "auto_mode": auto_mode,
    }
    log_structured(
        "autonomous_cycle.complete",
        request_id=request_id,
        organization_id=oid,
        taken=len(actions_taken),
        suggestions=len(suggestion_bucket),
    )
    return out


def autonomous_mode_enabled() -> bool:
    """Global gate for the background scheduler (default off)."""
    return (os.getenv("THIRAMAI_AUTONOMOUS_MODE") or "").strip().lower() in ("1", "true", "yes", "on")
