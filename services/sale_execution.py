"""
Retail sale: verify stock, deduct inventory, insert ``bills`` row.

Sync-only (call from worker threads or ``asyncio.to_thread`` from ASGI handlers).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import Bill
from services import audit_log as system_audit
from services import billing_guard
from services.action_policy import PolicyResult, evaluate_tool_action
from services.audit_service import log_policy_evaluation
from services.gst_compute import compute_gst_line
from services.inventory_ops import apply_inventory_delta

_log = logging.getLogger(__name__)

_SQLITE_LOCK_RETRIES = 24


def _session_factory_bind(factory: sessionmaker[Session]) -> Any:
    kw = getattr(factory, "kw", None)
    if isinstance(kw, dict):
        return kw.get("bind")
    return None


def execute_sell_stock_sync(
    organization_id: int,
    sku_name: str,
    quantity: float,
    location: str = "",
    *,
    interstate_gst: bool = False,
    _session_factory: Optional[Callable[[], Session]] = None,
    principal_user_id: int | None = None,
    principal_role_level: int | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Check stock, deduct ``quantity``, create ``Bill`` with line items and ``total_amount``.

    Returns:
        ``{"ok": True, "bill_id", "total_amount", "sku_name", "quantity_sold", "remaining_quantity", "items"}``
        or ``{"ok": False, "error": "..."}`` (no exception for expected business failures).
    """
    oid = int(organization_id)
    factory: sessionmaker[Session] | None = _session_factory or get_session_factory()  # type: ignore[assignment]
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    if billing_guard.is_billing_paused(oid, _session_factory=factory):
        return {
            "ok": False,
            "error": billing_guard.billing_pause_message(oid, _session_factory=factory)
            or "Factory billing is paused.",
        }

    if principal_role_level is not None:
        decision = evaluate_tool_action(
            tool_id="inventory.sell_stock",
            organization_id=oid,
            user_role_level=int(principal_role_level),
            billing_paused=False,
        )
        log_policy_evaluation(
            correlation_id=correlation_id,
            action_name="sell_stock",
            policy_decision=decision.result.value.upper(),
            user_id=principal_user_id,
            organization_id=oid,
            tool_id="inventory.sell_stock",
            reason=decision.reason,
        )
        if decision.result is PolicyResult.BLOCK:
            raise HTTPException(status_code=403, detail=decision.reason)
        if decision.result is PolicyResult.PROPOSE:
            _log.info(
                "sale_execution.policy_propose_pending org=%s user=%s sku=%r",
                oid,
                principal_user_id,
                sku_name,
            )
            return {
                "ok": False,
                "policy": "PROPOSE",
                "pending_approval": True,
                "detail": decision.reason,
                "tool_id": "inventory.sell_stock",
                "message": "Pending approval — policy engine requires owner/manager confirmation before posting this sale.",
            }

    sku = (sku_name or "").strip()
    if not sku:
        return {"ok": False, "error": "sku_name is required"}
    try:
        qty = Decimal(str(quantity))
    except Exception:
        return {"ok": False, "error": "invalid quantity"}
    if qty <= 0:
        return {"ok": False, "error": "quantity must be a positive whole number"}
    if qty != qty.to_integral_value():
        return {"ok": False, "error": "fractional units are not supported; use a whole number of units"}
    qty = qty.quantize(Decimal("1"))

    loc = (location or "").strip()

    bind = _session_factory_bind(factory)
    is_sqlite = bind is not None and bind.dialect.name == "sqlite"
    lock_retries = _SQLITE_LOCK_RETRIES if is_sqlite else 0

    bill_id = 0
    items: list[dict[str, Any]] = []
    line_total = Decimal("0")
    remaining = 0.0

    for attempt in range(lock_retries + 1):
        try:
            with factory() as session:
                with session.begin():
                    row = apply_inventory_delta(
                        session,
                        organization_id=oid,
                        sku_name=sku,
                        location=loc,
                        delta=-qty,
                    )
                    unit_price = row.unit_price or Decimal("0")
                    taxable = (qty * unit_price).quantize(Decimal("0.01"))
                    gst_rate = row.gst_rate_percent if row.gst_rate_percent is not None else Decimal("0")
                    gst_parts = compute_gst_line(taxable, gst_rate, use_igst=interstate_gst)
                    grand = gst_parts["grand_total"]
                    hsn = ((getattr(row, "hsn_code", None) or "") or "").strip() or None
                    items = [
                        {
                            "sku_name": sku,
                            "hsn_sac": hsn,
                            "quantity": float(qty),
                            "unit_price_pre_tax": float(unit_price),
                            "taxable_value": float(gst_parts["taxable_value"]),
                            "gst_rate_percent": float(gst_rate),
                            "cgst": float(gst_parts["cgst"]),
                            "sgst": float(gst_parts["sgst"]),
                            "igst": float(gst_parts["igst"]),
                            "gst_total": float(gst_parts["gst_total"]),
                            "line_total_with_tax": float(grand),
                            "supply_type": "inter_state_igst"
                            if interstate_gst
                            else "intra_state_cgst_sgst",
                        }
                    ]
                    bill = Bill(
                        organization_id=oid,
                        items=items,
                        total_amount=grand,
                    )
                    session.add(bill)
                    session.flush()
                    bill_id = int(bill.id)
                    remaining = float(row.quantity or Decimal("0"))
                    line_total = grand
            break
        except ValueError as exc:
            _log.warning(
                "sale_execution.business_reject org=%s sku=%r qty=%s: %s",
                oid,
                sku,
                qty,
                exc,
            )
            return {"ok": False, "error": str(exc)}
        except OperationalError as exc:
            msg = str(exc).lower()
            locked = "database is locked" in msg or "locked" in msg
            if is_sqlite and locked and attempt < lock_retries:
                time.sleep(0.002 * (attempt + 1))
                _log.debug(
                    "sale_execution.sqlite_lock_retry org=%s sku=%r attempt=%s",
                    oid,
                    sku,
                    attempt + 1,
                )
                continue
            _log.exception(
                "sale_execution.db_operational_error org=%s sku=%r",
                oid,
                sku,
            )
            if "database is locked" in msg or "locked" in msg:
                return {"ok": False, "error": "Inventory is busy; retry the sale in a moment."}
            return {"ok": False, "error": "Temporary database error; retry the sale shortly."}
        except Exception as exc:
            _log.exception("sale_execution.unexpected_error org=%s sku=%r", oid, sku)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # Production: audit on the app engine. Injected session factories (tests) often use a
    # partial schema without ``system_audit_logs`` — skip audit to avoid spurious DB errors.
    audit_factory = None if _session_factory is not None else get_session_factory()
    if audit_factory is not None:
        try:
            with audit_factory() as asession:
                with asession.begin():
                    system_audit.record_system_audit(
                        action=system_audit.ACTION_FINANCIAL_EXECUTION,
                        outcome="success",
                        organization_id=oid,
                        resource_type="bill",
                        metadata={
                            "bill_id": bill_id,
                            "sku": sku[:128],
                            "quantity_sold": str(qty),
                            "total_inr": float(line_total),
                            "channel": "sale_execution_sell_stock",
                        },
                        session=asession,
                    )
        except Exception as exc:
            _log.warning(
                "sale_execution.audit_append_failed %s",
                type(exc).__name__,
                exc_info=True,
            )

    return {
        "ok": True,
        "bill_id": bill_id,
        "total_amount": float(line_total),
        "sku_name": sku,
        "quantity_sold": float(qty),
        "remaining_quantity": remaining,
        "items": items,
    }
