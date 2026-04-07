"""
Sovereign Billing — DB-aware invoicing, inventory deduction, GST preflight.

High-risk paths require HITL approval via services.approval_store (see app routes).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import asset_portal
from core.database import get_session_factory
from services import audit_log as system_audit
from services import billing_guard
from core.db.models import Inventory, Invoice
from services.tenant_access import get_production_log_for_organization
from factory.billing_tool import build_invoice_pdf, default_invoice_path

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z0-9]{13}$")


def gst_breakdown(
    subtotal_inr: float,
    gst_percent: float,
    *,
    intra_state: bool = True,
) -> dict[str, float]:
    """
    Intra-state: SGST + CGST each half of total GST amount.
    Inter-state (not fully modeled for filing): returns IGST = full GST % on subtotal.
    """
    total_gst_amt = subtotal_inr * (gst_percent / 100.0)
    if intra_state:
        half = total_gst_amt / 2.0
        return {
            "subtotal_inr": round(subtotal_inr, 2),
            "cgst_inr": round(half, 2),
            "sgst_inr": round(half, 2),
            "igst_inr": 0.0,
            "total_gst_inr": round(total_gst_amt, 2),
            "grand_total_inr": round(subtotal_inr + total_gst_amt, 2),
        }
    return {
        "subtotal_inr": round(subtotal_inr, 2),
        "cgst_inr": 0.0,
        "sgst_inr": 0.0,
        "igst_inr": round(total_gst_amt, 2),
        "total_gst_inr": round(total_gst_amt, 2),
        "grand_total_inr": round(subtotal_inr + total_gst_amt, 2),
    }


def gst_compliance_check(
    *,
    seller_gstin: str,
    buyer_gstin: str | None,
    gst_percent: float,
) -> dict[str, Any]:
    """Preflight before finalizing draft — SGST/CGST split when state codes match."""
    warnings: list[str] = []
    s = (seller_gstin or "").strip().upper()
    b = (buyer_gstin or "").strip().upper()
    if s and not GSTIN_RE.match(s):
        warnings.append("Seller GSTIN format should be 15 chars (06ABCDE1234F1Z5).")
    if b and not GSTIN_RE.match(b):
        warnings.append("Buyer GSTIN format should be 15 chars.")
    intra = True
    if len(s) >= 2 and len(b) >= 2:
        intra = s[:2] == b[:2]
    elif not b:
        warnings.append("No buyer GSTIN — assuming intra-state SGST/CGST split; verify with CA.")
    sub = 100_000.0  # reference ₹1L for percentage display only
    br = gst_breakdown(sub, gst_percent, intra_state=intra)
    return {
        "ok": len(warnings) == 0,
        "warnings": warnings,
        "intra_state": intra,
        "seller_state_prefix": s[:2] if len(s) >= 2 else None,
        "buyer_state_prefix": b[:2] if len(b) >= 2 else None,
        "reference_breakdown_on_1lakh": br,
    }


def _deduct_inventory(session: Session, org_id: int | None, sku_name: str, location: str, qty: Decimal) -> bool:
    stmt = select(Inventory).where(Inventory.sku_name == sku_name)
    loc = (location or "").strip()
    if loc:
        stmt = stmt.where(Inventory.location == loc)
    if org_id is not None:
        stmt = stmt.where(
            or_(Inventory.organization_id == org_id, Inventory.organization_id.is_(None))
        )
    q = session.execute(stmt).scalars().first()
    if q is None:
        return False
    if q.quantity < qty:
        return False
    q.quantity = q.quantity - qty
    if q.unit_price is not None:
        q.total_value = (q.quantity * q.unit_price).quantize(Decimal("0.01"))
    elif q.total_value is not None and qty > 0:
        # Pro-rata shrink value by sold proportion if no unit price
        orig = q.quantity + qty
        if orig > 0:
            q.total_value = (q.total_value * (q.quantity / orig)).quantize(Decimal("0.01"))
    session.flush()
    return True


def build_sale_payload_from_production_log(
    production_log_id: int,
    *,
    organization_id: int,
    buyer: str,
    buyer_address: str,
    rate_per_kg: float,
    gst_percent: float,
    seller_name: str,
    seller_address: str,
    seller_gstin: str,
    sku_name: str,
    inventory_location: str,
    length_m: float = 1.0,
    grade: str = "HDPE",
    invoice_no: str = "",
    invoice_date: str = "",
) -> dict[str, Any]:
    """Load pipe sale quantities from production_logs; caller supplies commercial terms."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL not configured — cannot load production log.")
    oid = int(organization_id)
    with factory() as session:
        lg = get_production_log_for_organization(session, production_log_id, oid)
        if lg is None:
            raise ValueError(f"production_log id={production_log_id} not found")
        weight = float(lg.yield_out or lg.raw_material_in or 0)
        if weight <= 0:
            raise ValueError("production log has no yield_out / raw_material_in quantity")
        org_id = oid
    inv_date = (invoice_date or "").strip() or date.today().isoformat()
    inv_no = (invoice_no or "").strip() or f"INV-{inv_date.replace('-', '')}-PL{production_log_id}"
    return {
        "production_log_id": production_log_id,
        "organization_id": org_id,
        "buyer": buyer,
        "buyer_address": buyer_address,
        "buyer_gstin": "",
        "weight_kg": weight,
        "rate_per_kg": rate_per_kg,
        "gst_percent": gst_percent,
        "seller_name": seller_name,
        "seller_address": seller_address,
        "seller_gstin": seller_gstin,
        "sku_name": sku_name,
        "inventory_location": inventory_location,
        "length_m": length_m,
        "grade": grade,
        "invoice_no": inv_no,
        "invoice_date": inv_date,
    }


def draft_invoice_from_db_sale(payload: dict[str, Any]) -> dict[str, Any]:
    """GST + totals only — no PDF, no inventory mutation (safe for dashboard preview)."""
    w = float(payload["weight_kg"])
    r = float(payload["rate_per_kg"])
    g = float(payload["gst_percent"])
    sub = w * r
    bg = payload.get("buyer_gstin")
    pre = gst_compliance_check(
        seller_gstin=str(payload.get("seller_gstin") or ""),
        buyer_gstin=str(bg).strip() if bg else None,
        gst_percent=g,
    )
    br = gst_breakdown(sub, g, intra_state=pre["intra_state"])
    return {
        "payload": payload,
        "gst_compliance": pre,
        "totals": br,
        "risk_tier": "high",
        "action_type": "issue_invoice",
    }


def execute_approved_invoice_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Finalize: deduct inventory (PostgreSQL), generate PDF, master_index + sales_history.
    Caller must enforce idempotency + HITL for high-risk flows.
    """
    org_raw = payload.get("organization_id")
    if org_raw is not None:
        billing_guard.assert_billing_not_paused(int(org_raw))

    w = float(payload["weight_kg"])
    r = float(payload["rate_per_kg"])
    g = float(payload["gst_percent"])
    bg = payload.get("buyer_gstin")
    pre = gst_compliance_check(
        seller_gstin=str(payload.get("seller_gstin") or ""),
        buyer_gstin=str(bg).strip() if bg else None,
        gst_percent=g,
    )
    if not pre["ok"] and not payload.get("force_despite_gst_warnings"):
        raise ValueError("GST compliance warnings: " + "; ".join(pre["warnings"]))

    factory = get_session_factory()
    if factory is not None and payload.get("sku_name"):
        org_raw = payload.get("organization_id")
        if org_raw is None:
            raise ValueError(
                "organization_id is required on approved invoice payloads when deducting inventory (tenant boundary)."
            )
        org_id = int(org_raw)
        with factory() as session:
            with session.begin():
                ok = _deduct_inventory(
                    session,
                    org_id,
                    str(payload["sku_name"]),
                    str(payload.get("inventory_location") or ""),
                    Decimal(str(w)),
                )
                if not ok:
                    raise RuntimeError(
                        "Inventory deduction failed — insufficient stock or SKU not found for "
                        f"{payload['sku_name']} @ {payload.get('inventory_location') or '(any)'}"
                    )
                system_audit.record_system_audit(
                    action=system_audit.ACTION_STOCK_UPDATE,
                    outcome="success",
                    organization_id=org_id,
                    resource_type="inventory",
                    metadata={
                        "sku": str(payload.get("sku_name") or "")[:128],
                        "deduct_kg": w,
                        "channel": "billing_invoice_deduct",
                    },
                )

    out = default_invoice_path()
    path = build_invoice_pdf(
        buyer_name=str(payload["buyer"]),
        buyer_address=str(payload.get("buyer_address") or "-"),
        invoice_no=str(payload["invoice_no"]),
        invoice_date=str(payload["invoice_date"]),
        length_m=float(payload.get("length_m") or 1.0),
        grade=str(payload.get("grade") or "HDPE"),
        weight_kg=w,
        rate_per_kg=r,
        gst_percent=g,
        seller_name=str(payload.get("seller_name") or "Seller"),
        seller_address=str(payload.get("seller_address") or "-"),
        seller_gstin=str(payload.get("seller_gstin") or "-"),
        out_path=out,
        append_master_index=False,
    )
    rel = path.relative_to(asset_portal.FACTORY_OUTPUT.resolve()).as_posix()
    subtotal = w * r
    gst_amt = subtotal * (g / 100.0)
    grand = subtotal + gst_amt
    br = gst_breakdown(subtotal, g, intra_state=pre["intra_state"])
    org_for_index = int(payload.get("organization_id") or asset_portal.legacy_default_organization_id())
    note = (
        f"grade={payload.get('grade')}; weight_kg={w}; revenue_inr={grand:.2f}; "
        f"sgst_inr={br['sgst_inr']}; cgst_inr={br['cgst_inr']}; action_engine=1"
    )
    note = asset_portal.append_organization_to_index_note(note, org_for_index)
    asset_portal.append_master_index_row(
        zone="factory",
        relative_path=rel,
        kind="invoice",
        title=f"Invoice {payload['invoice_no']}",
        size_bytes=path.stat().st_size if path.is_file() else 0,
        note=note,
    )
    asset_portal.append_sales_history_entry(
        {
            "invoice_no": payload["invoice_no"],
            "invoice_date": payload["invoice_date"],
            "relative_path": rel,
            "buyer": payload["buyer"],
            "weight_kg": w,
            "rate_per_kg_inr": r,
            "gst_percent": g,
            "subtotal_inr": round(subtotal, 2),
            "gst_inr": round(gst_amt, 2),
            "grand_total_inr": round(grand, 2),
            "cgst_inr": br["cgst_inr"],
            "sgst_inr": br["sgst_inr"],
            "seller": payload.get("seller_name"),
            "seller_gstin": payload.get("seller_gstin"),
            "production_log_id": payload.get("production_log_id"),
            "source": "sovereign_billing_service",
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    asset_portal.sync_index_cursor_to_end()
    org_audit = int(payload.get("organization_id") or asset_portal.legacy_default_organization_id())
    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=org_audit,
        resource_type="invoice",
        metadata={
            "invoice_no": str(payload.get("invoice_no") or "")[:64],
            "grand_total_inr": round(grand, 2),
            "source": "billing_service_approved_invoice",
        },
    )
    return {
        "ok": True,
        "relative_path": rel,
        "url": asset_portal.factory_url_for_relative(rel),
        "totals": br,
        "gst_compliance": pre,
    }


def create_simple_erp_invoice_sync(
    organization_id: int,
    *,
    invoice_no: str,
    invoice_date: date | None,
    grand_total_inr: float | Decimal,
    user_id: int | None = None,
    external_ref: str | None = None,
    post_ledger: bool = True,
) -> dict[str, Any]:
    """
    Minimal ERP posting: one ``invoices`` row + optional matching ``ledger_transactions`` row (same DB txn).

    Does **not** generate PDF — use Sovereign /assets/invoice or production-log flows for documents.
    """
    from services import finance_service

    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    no = (invoice_no or "").strip() or f"ERP-{date.today().isoformat().replace('-', '')}"
    d = invoice_date or date.today()
    gt = Decimal(str(grand_total_inr))
    if gt < 0:
        return {"ok": False, "error": "grand_total_inr must be non-negative"}
    ref = (external_ref or "").strip()[:512] or None

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    with factory() as session:
        with session.begin():
            inv = Invoice(
                organization_id=oid,
                invoice_no=no,
                invoice_date=d,
                grand_total_inr=gt,
                external_ref=ref,
            )
            session.add(inv)
            session.flush()
            iid = int(inv.id)
            lid: int | None = None
            if post_ledger and gt > 0:
                lid = finance_service.insert_ledger_row(
                    session,
                    organization_id=oid,
                    user_id=user_id,
                    entry_type="revenue",
                    amount_inr=gt,
                    category="invoice",
                    reference=no,
                    extra={"invoice_id": iid, "source": "erp_simple_invoice"},
                )

    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="invoice",
        metadata={
            "invoice_id": iid,
            "invoice_no": no[:64],
            "grand_total_inr": float(gt),
            "ledger_transaction_id": lid,
            "source": "billing_service.create_simple_erp_invoice",
        },
    )
    return {
        "ok": True,
        "invoice_id": iid,
        "invoice_no": no,
        "ledger_transaction_id": lid,
        "organization_id": oid,
    }


from services.billing_phase2_service import (  # noqa: E402
    create_structured_invoice_sync,
    gst_report_sync,
    list_invoices_sync,
    record_payment_sync,
)

