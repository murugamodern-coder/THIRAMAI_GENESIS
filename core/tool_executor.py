"""
Execute resolved intents using existing THIRAMAI services (inventory_ops, sale_execution, analytics).

Policy + retail preflight mirror orchestrator / API expectations.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from core.database import db_session, get_session_factory
from core.db.models import Inventory
from fastapi import HTTPException

from services.experience_buffer import record_experience
from services.inventory_ops import apply_inventory_delta
from services.sale_execution import execute_sell_stock_sync

_LOG = logging.getLogger(__name__)


def _snapshot_inventory(organization_id: int, *, limit: int = 200) -> dict[str, Any]:
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database_not_configured", "items": []}
    with factory() as session:
        stmt = (
            select(Inventory)
            .where(
                or_(Inventory.organization_id == oid, Inventory.organization_id.is_(None)),
            )
            .order_by(Inventory.sku_name.asc(), Inventory.id.asc())
            .limit(int(limit))
        )
        rows = list(session.scalars(stmt).all())
        items = [
            {
                "sku_name": r.sku_name,
                "quantity": float(r.quantity or Decimal("0")),
                "location": r.location or "",
            }
            for r in rows
        ]
    return {"ok": True, "organization_id": oid, "count": len(items), "items": items}


def execute_intent(intent_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Run the tool chain for a resolved intent.

    ``context`` should include:
    - ``organization_id`` (int, required)
    - ``actor_role_name`` (str, optional; default owner for dashboard)
    - ``user_id`` (int, optional; for sale audit / policy)
    - ``role_level`` (int, optional; overrides mapping from role name)
    - ``user_message`` (str, optional; retail quantity veto)
    - ``correlation_id`` (str, optional)
    - ``experience_source`` (str, optional; forwarded to ``record_experience``, default ``intent_engine``)
    """
    oid = int(context.get("organization_id") or 0)
    if oid <= 0:
        return _err("invalid_organization", "organization_id is required", intent_data)

    intent = str(intent_data.get("intent") or "unknown")
    if intent == "unknown":
        return _err("unknown_intent", "No executable intent", intent_data)

    role_name = (context.get("actor_role_name") or "owner").strip().lower() or "owner"
    try:
        from api.dependencies import ROLE_LEVEL_BY_NAME

        role_level = int(context.get("role_level") if context.get("role_level") is not None else ROLE_LEVEL_BY_NAME.get(role_name, 5))
    except Exception:
        role_level = int(context.get("role_level") or 5)
    uid = context.get("user_id")
    uid_i = int(uid) if uid is not None and int(uid) > 0 else None
    user_msg = str(context.get("user_message") or "")
    corr = context.get("correlation_id")
    exp_src = str(context.get("experience_source") or "intent_engine")

    try:
        if intent == "sell_inventory":
            return _exec_sell(
                intent_data,
                organization_id=oid,
                role_level=role_level,
                user_id=uid_i,
                user_message=user_msg,
                correlation_id=corr if isinstance(corr, str) else None,
                experience_source=exp_src,
            )
        if intent == "add_inventory":
            return _exec_add(intent_data, organization_id=oid, experience_source=exp_src)
        if intent == "read_inventory":
            return _exec_read(intent_data, organization_id=oid, experience_source=exp_src)
    except Exception as exc:
        _LOG.exception("tool_executor.execute_intent failed intent=%s", intent)
        return _err("execution_exception", str(exc), intent_data, ok=False)

    return _err("unsupported_intent", f"Intent {intent!r} is not supported", intent_data)


def _err(
    code: str,
    message: str,
    intent_data: dict[str, Any],
    *,
    ok: bool = False,
) -> dict[str, Any]:
    return {
        "status": "error" if not ok else "success",
        "ok": ok,
        "action": str(intent_data.get("intent") or "unknown"),
        "message": message,
        "data": {"error": code},
    }


def _ok(intent: str, message: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "success",
        "ok": True,
        "action": intent,
        "message": message,
        "data": data,
    }


def _exec_sell(
    intent_data: dict[str, Any],
    *,
    organization_id: int,
    role_level: int,
    user_id: int | None,
    user_message: str,
    correlation_id: str | None,
    experience_source: str = "intent_engine",
) -> dict[str, Any]:
    from core.sale_intent_heuristic import early_retail_sell_quantity_veto_message

    veto = early_retail_sell_quantity_veto_message(user_message)
    if veto:
        return _err("retail_quantity_veto", veto.strip(), intent_data)

    sku = str(intent_data.get("entity") or "").strip()
    qty = intent_data.get("quantity")
    if not sku:
        return _err("sku_required", "SKU (entity) is required for sell_inventory", intent_data)
    try:
        qf = float(qty)
    except (TypeError, ValueError):
        return _err("invalid_quantity", "Quantity must be a number", intent_data)
    if qf <= 0:
        return _err("invalid_quantity", "Sell quantity must be positive", intent_data)
    if qf != int(qf):
        return _err("invalid_quantity", "Only whole units can be sold", intent_data)

    try:
        from services.experience_buffer import is_blocked_by_critical_mistake

        blocked, reason = is_blocked_by_critical_mistake(int(organization_id), "inventory.sell_stock")
    except Exception:
        blocked, reason = False, ""
    if blocked:
        return _err("critical_mistake_block", reason or "Tool blocked for this organization.", intent_data)

    loc = str(intent_data.get("location") or "").strip()
    try:
        out = execute_sell_stock_sync(
            int(organization_id),
            sku,
            float(qf),
            loc,
            principal_user_id=user_id,
            principal_role_level=int(role_level),
            correlation_id=correlation_id,
        )
    except HTTPException as he:
        return _err("policy_block", str(he.detail), intent_data)
    if not out.get("ok"):
        if out.get("policy") == "PROPOSE":
            return _err("policy_propose", str(out.get("detail") or "Pending approval"), intent_data)
        return _err("sell_failed", str(out.get("error") or "sell failed"), intent_data)

    msg = f"Sold {int(qf)} {sku} — bill #{out.get('bill_id')} total ₹{out.get('total_amount', 0):.2f}"
    result = _ok("sell_inventory", msg, out)
    _record_success("sell_inventory", intent_data, out, experience_source=experience_source)
    return result


def _exec_add(
    intent_data: dict[str, Any],
    *,
    organization_id: int,
    experience_source: str = "intent_engine",
) -> dict[str, Any]:
    sku = str(intent_data.get("entity") or "").strip()
    qty = intent_data.get("quantity")
    if not sku:
        return _err("sku_required", "SKU (entity) is required for add_inventory", intent_data)
    try:
        delta = Decimal(str(qty))
    except Exception:
        return _err("invalid_quantity", "Quantity must be numeric", intent_data)
    if delta == 0:
        return _err("invalid_quantity", "Quantity cannot be zero", intent_data)

    loc = str(intent_data.get("location") or "").strip()
    try:
        with db_session() as session:
            with session.begin():
                row = apply_inventory_delta(
                    session,
                    organization_id=int(organization_id),
                    sku_name=sku,
                    location=loc,
                    delta=delta,
                )
            session.refresh(row)
            nq = float(row.quantity)
    except RuntimeError:
        return _err("database_not_configured", "DATABASE_URL is not set", intent_data)
    except ValueError as exc:
        return _err("adjust_rejected", str(exc), intent_data)
    except Exception as exc:
        return _err("adjust_failed", f"{type(exc).__name__}: {exc}", intent_data)

    verb = "Added" if delta > 0 else "Adjusted"
    msg = f"{verb} stock for `{sku}` by {delta} → on-hand **{nq}**"
    data = {"sku_name": sku, "new_quantity": nq, "delta": str(delta), "location": loc or "(any)"}
    result = _ok("add_inventory", msg, data)
    _record_success("add_inventory", intent_data, data, experience_source=experience_source)
    return result


def _exec_read(
    intent_data: dict[str, Any],
    *,
    organization_id: int,
    experience_source: str = "intent_engine",
) -> dict[str, Any]:
    mode = str(intent_data.get("read_mode") or "snapshot")
    if mode == "low_stock":
        from services.analytics_service import list_low_stock_alerts_sync

        snap = list_low_stock_alerts_sync(int(organization_id), threshold=5, limit=100)
        msg = f"Low-stock rows: {snap.get('count', 0)} (threshold {snap.get('threshold', 5)})"
        result = _ok("read_inventory", msg, snap)
        _record_success(
            "read_inventory",
            intent_data,
            {"mode": "low_stock", "count": snap.get("count")},
            experience_source=experience_source,
        )
        return result

    snap = _snapshot_inventory(int(organization_id))
    if not snap.get("ok"):
        return _err(
            str(snap.get("error") or "read_failed"),
            "Could not read inventory",
            intent_data,
        )
    n = int(snap.get("count") or 0)
    msg = f"Inventory snapshot: {n} row(s) (tenant-scoped, capped)."
    result = _ok("read_inventory", msg, snap)
    _record_success(
        "read_inventory",
        intent_data,
        {"mode": "snapshot", "count": n},
        experience_source=experience_source,
    )
    return result


def _record_success(
    intent: str,
    intent_data: dict[str, Any],
    result_payload: dict[str, Any],
    *,
    experience_source: str = "intent_engine",
) -> None:
    try:
        record_experience(
            source=(experience_source or "intent_engine")[:128],
            action=intent,
            result={
                "entity": intent_data.get("entity"),
                "quantity": intent_data.get("quantity"),
                "tool_result": result_payload,
            },
            success=True,
            meta={"source_detail": intent_data.get("source")},
        )
    except Exception as exc:
        _LOG.debug("record_experience skipped: %s", exc)
