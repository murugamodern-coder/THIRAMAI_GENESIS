"""
Upgrade 2.1 — Action engine: tool payloads, execution modes, safe auto-draft paths.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import InventoryItem, JarvisFact, Supplier

_log = logging.getLogger("thiramai.jarvis_proactive_action_engine")


def user_execution_mode() -> str:
    """
    Global execution posture: ``suggest`` | ``confirm`` | ``auto``.

    Per-user override: ``JarvisFact`` ``fact_type=jarvis_settings``, ``key=proactive_execution_mode``.
    """
    raw = (os.getenv("THIRAMAI_PROACTIVE_EXECUTION_MODE") or "suggest").strip().lower()
    return raw if raw in ("suggest", "confirm", "auto") else "suggest"


def user_execution_mode_for_user(user_id: int) -> str:
    """Resolve execution mode for a user (fact override → env default)."""
    uid = int(user_id)
    if uid <= 0:
        return user_execution_mode()
    factory = get_session_factory()
    if factory is None:
        return user_execution_mode()
    try:
        with factory() as session:
            row = session.execute(
                select(JarvisFact).where(
                    JarvisFact.user_id == uid,
                    JarvisFact.fact_type == "jarvis_settings",
                    JarvisFact.key == "proactive_execution_mode",
                ).limit(1)
            ).scalar_one_or_none()
        if row:
            v = (row.value or "").strip().lower()
            if v in ("suggest", "confirm", "auto"):
                return v
    except Exception as exc:
        _log.debug("user_execution_mode_for_user: %s", exc)
    return user_execution_mode()


def auto_po_draft_enabled() -> bool:
    return (os.getenv("THIRAMAI_PROACTIVE_AUTO_PO_DRAFT") or "").strip().lower() in ("1", "true", "yes", "on")


def build_reorder_po_draft_payload_sync(
    *,
    organization_id: int,
    sku: str,
    user_id: int,
    quantity_hint: Any = None,
    supplier_index: int = 0,
) -> dict[str, Any]:
    """
    Build ``action_ready_payload`` for a draft purchase order (supplier + line).

    Returns ``handler`` = ``create_purchase_order_draft`` for UI / Jarvis tool routing.
    """
    oid = int(organization_id)
    sku_s = (sku or "").strip()
    uid = int(user_id)
    if oid <= 0 or not sku_s:
        return {"ok": False, "error": "organization_id and sku required", "handler": "create_purchase_order_draft"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured", "handler": "create_purchase_order_draft"}
    idx = max(0, int(supplier_index))
    with factory() as session:
        sup = session.execute(
            select(Supplier)
            .where(Supplier.organization_id == oid)
            .order_by(Supplier.name.asc())
            .offset(idx)
            .limit(1)
        ).scalar_one_or_none()
        if sup is None:
            return {
                "ok": False,
                "error": "no_supplier_configured",
                "handler": "create_purchase_order_draft",
                "organization_id": oid,
                "sku": sku_s,
            }
        sid = int(sup.id)
        row = session.execute(
            select(InventoryItem).where(InventoryItem.organization_id == oid, InventoryItem.sku_name == sku_s).limit(1)
        ).scalar_one_or_none()
        q_ord = Decimal("1")
        if quantity_hint is not None:
            try:
                q_ord = max(Decimal("1"), Decimal(str(quantity_hint)))
            except Exception:
                q_ord = Decimal("1")
        elif row and row.reorder_point is not None and row.quantity is not None:
            try:
                gap = Decimal(str(row.reorder_point)) - Decimal(str(row.quantity))
                if gap > 0:
                    q_ord = max(Decimal("1"), gap)
            except Exception:
                q_ord = Decimal("1")
        uc = Decimal("1")
        if row and row.unit_cost_pre_tax is not None:
            try:
                uc = max(Decimal("0.01"), Decimal(str(row.unit_cost_pre_tax)))
            except Exception:
                uc = Decimal("1")

    lines = [{"sku_name": sku_s, "quantity_ordered": str(q_ord), "unit_cost_pre_tax": str(uc)}]
    return {
        "ok": True,
        "handler": "create_purchase_order_draft",
        "organization_id": oid,
        "supplier_id": sid,
        "order_date": date.today().isoformat(),
        "lines": lines,
        "notes": "Auto-draft from Jarvis proactive (review before sending to supplier).",
        "user_id": uid,
        "supplier_index": idx,
    }


def try_execute_create_po_draft(*, user_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    When ``THIRAMAI_PROACTIVE_AUTO_PO_DRAFT=1`` and execution mode is ``auto``, create draft PO in DB.

    Returns execution result dict, or ``None`` when skipped.
    """
    if user_execution_mode_for_user(int(user_id)) != "auto" or not auto_po_draft_enabled():
        return None
    if (payload.get("handler") or "") != "create_purchase_order_draft":
        return None
    if not payload.get("ok"):
        return None
    oid = int(payload.get("organization_id") or 0)
    sid = int(payload.get("supplier_id") or 0)
    if oid <= 0 or sid <= 0:
        return None
    lines = payload.get("lines")
    if not isinstance(lines, list) or not lines:
        return None
    try:
        from datetime import datetime as _dt

        from services.inventory_phase2_service import create_purchase_order_sync

        od = _dt.fromisoformat(str(payload.get("order_date") or date.today().isoformat())).date()
        out = create_purchase_order_sync(
            organization_id=oid,
            supplier_id=sid,
            order_date=od,
            expected_date=None,
            notes=str(payload.get("notes") or "")[:2000] or None,
            lines=lines,
            user_id=int(user_id),
        )
        return {"executed": True, "result": out}
    except Exception as exc:
        _log.warning("auto PO draft failed: %s", exc)
        return {"executed": False, "error": str(exc)}
