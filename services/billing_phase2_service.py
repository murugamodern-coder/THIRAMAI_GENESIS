"""
Phase 2 structured billing: invoice line items, payments, GST reporting snapshots.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import GstRecord, Invoice, InvoiceItem, Payment
from services import audit_log as system_audit


def _dec(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def _serialize_invoice(inv: Invoice, session: Session, *, include_lines: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": int(inv.id),
        "organization_id": int(inv.organization_id),
        "invoice_no": inv.invoice_no,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "grand_total_inr": float(inv.grand_total_inr),
        "status": inv.status,
        "payment_status": inv.payment_status,
        "external_ref": inv.external_ref,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }
    if include_lines:
        lines = sorted(
            session.scalars(
                select(InvoiceItem).where(InvoiceItem.invoice_id == int(inv.id)).order_by(InvoiceItem.line_no)
            ).all(),
            key=lambda x: x.line_no,
        )
        out["line_items"] = [
            {
                "id": int(li.id),
                "line_no": li.line_no,
                "description": li.description,
                "quantity": float(li.quantity),
                "unit_price_pre_tax": float(li.unit_price_pre_tax),
                "gst_rate_percent": float(li.gst_rate_percent),
                "line_total_inr": float(li.line_total_inr),
                "hsn_code": li.hsn_code,
            }
            for li in lines
        ]
        pays = list(
            session.scalars(select(Payment).where(Payment.invoice_id == int(inv.id))).all()
        )
        out["payments"] = [
            {
                "id": int(p.id),
                "amount_inr": float(p.amount_inr),
                "method": p.method,
                "reference": p.reference,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in pays
        ]
    return out


def create_structured_invoice_sync(
    *,
    organization_id: int,
    invoice_no: str,
    invoice_date: date | None,
    lines: list[dict[str, Any]],
    external_ref: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    if not lines:
        return {"ok": False, "error": "lines required"}
    no = (invoice_no or "").strip() or f"INV-{date.today().isoformat()}"
    idate = invoice_date or date.today()

    parsed: list[tuple[int, str, Decimal, Decimal, Decimal, Decimal, str | None]] = []
    grand = Decimal("0")
    for idx, ln in enumerate(lines, start=1):
        desc = (ln.get("description") or "Line").strip()[:2000]
        qty = _dec(ln.get("quantity", 1))
        if qty <= 0:
            return {"ok": False, "error": "each line needs positive quantity"}
        up = _dec(ln.get("unit_price_pre_tax"))
        if up < 0:
            return {"ok": False, "error": "unit_price_pre_tax must be non-negative"}
        gstp = _dec(ln.get("gst_rate_percent", 0))
        taxable = (qty * up).quantize(Decimal("0.01"))
        gst_amt = (taxable * gstp / Decimal("100")).quantize(Decimal("0.01"))
        line_total = (taxable + gst_amt).quantize(Decimal("0.01"))
        grand += line_total
        hsn = ln.get("hsn_code")
        hsn_s = (str(hsn).strip()[:16] if hsn is not None else None) or None
        parsed.append((idx, desc, qty, up, gstp, line_total, hsn_s))

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    iid = 0
    with factory() as session:
        with session.begin():
            inv = Invoice(
                organization_id=oid,
                invoice_no=no,
                invoice_date=idate,
                grand_total_inr=grand,
                external_ref=(external_ref or "").strip()[:512] or None,
                status="posted",
                payment_status="unpaid",
            )
            session.add(inv)
            session.flush()
            iid = int(inv.id)
            for idx, desc, qty, up, gstp, lt, hsn_s in parsed:
                session.add(
                    InvoiceItem(
                        invoice_id=iid,
                        line_no=idx,
                        description=desc,
                        quantity=qty,
                        unit_price_pre_tax=up,
                        gst_rate_percent=gstp,
                        line_total_inr=lt,
                        hsn_code=hsn_s,
                    )
                )

    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="invoice",
        metadata={
            "channel": "billing_phase2.create_invoice",
            "invoice_id": iid,
            "invoice_no": no[:64],
            "grand_total_inr": float(grand),
        },
    )
    return {"ok": True, "invoice_id": iid, "grand_total_inr": float(grand), "invoice_no": no}


def list_invoices_sync(*, organization_id: int, limit: int = 200) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 500))
    with factory() as session:
        rows = list(
            session.scalars(
                select(Invoice)
                .where(Invoice.organization_id == oid)
                .order_by(Invoice.id.desc())
                .limit(lim)
            ).all()
        )
        items = [_serialize_invoice(r, session, include_lines=True) for r in rows]
    return {"ok": True, "invoices": items}


def _recompute_payment_status(session: Session, inv: Invoice) -> None:
    total_paid = Decimal("0")
    for p in session.scalars(select(Payment).where(Payment.invoice_id == int(inv.id))).all():
        total_paid += _dec(p.amount_inr)
    due = _dec(inv.grand_total_inr) - total_paid
    if due <= Decimal("0.01"):
        inv.payment_status = "paid"
    elif total_paid > 0:
        inv.payment_status = "partial"
    else:
        inv.payment_status = "unpaid"


def record_payment_sync(
    *,
    organization_id: int,
    invoice_id: int,
    amount_inr: float | Decimal,
    method: str = "bank",
    reference: str | None = None,
    paid_at: datetime | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    iid = int(invoice_id)
    if oid <= 0 or iid <= 0:
        return {"ok": False, "error": "organization_id and invoice_id required"}
    amt = _dec(amount_inr)
    if amt <= 0:
        return {"ok": False, "error": "amount must be positive"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    pid = 0
    with factory() as session:
        try:
            with session.begin():
                inv = session.get(Invoice, iid)
                if inv is None or int(inv.organization_id) != oid:
                    raise LookupError("invoice not found")
                pt = paid_at or datetime.now(timezone.utc)
                pay = Payment(
                    organization_id=oid,
                    invoice_id=iid,
                    amount_inr=amt,
                    method=(method or "bank")[:32],
                    reference=(reference or "").strip() or None,
                    paid_at=pt,
                )
                session.add(pay)
                session.flush()
                pid = int(pay.id)
                _recompute_payment_status(session, inv)
        except LookupError:
            return {"ok": False, "error": "invoice not found"}

    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="payment",
        metadata={
            "channel": "billing_phase2.payment",
            "invoice_id": iid,
            "payment_id": pid,
            "amount_inr": float(amt),
        },
    )
    return {"ok": True, "payment_id": pid, "invoice_id": iid}


def gst_report_sync(
    *,
    organization_id: int,
    period_start: date,
    period_end: date,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Aggregate taxable value and GST from ``invoice_items`` for invoices in date range; upsert ``gst_records``."""
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    if period_end < period_start:
        return {"ok": False, "error": "period_end before period_start"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    by_rate: dict[str, dict[str, float]] = {}
    total_taxable = Decimal("0")
    total_gst = Decimal("0")

    with factory() as session:
        invs = list(
            session.scalars(
                select(Invoice).where(
                    Invoice.organization_id == oid,
                    Invoice.invoice_date.isnot(None),
                    Invoice.invoice_date >= period_start,
                    Invoice.invoice_date <= period_end,
                )
            ).all()
        )
        for inv in invs:
            line_rows = list(
                session.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == int(inv.id))).all()
            )
            for li in line_rows:
                qty = _dec(li.quantity)
                up = _dec(li.unit_price_pre_tax)
                taxable = (qty * up).quantize(Decimal("0.01"))
                gstp = _dec(li.gst_rate_percent)
                gst_amt = (taxable * gstp / Decimal("100")).quantize(Decimal("0.01"))
                total_taxable += taxable
                total_gst += gst_amt
                key = f"{float(gstp):g}"
                if key not in by_rate:
                    by_rate[key] = {"taxable_inr": 0.0, "gst_inr": 0.0}
                by_rate[key]["taxable_inr"] += float(taxable)
                by_rate[key]["gst_inr"] += float(gst_amt)

        inv_count = len(invs)
        data = {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "invoice_count": inv_count,
            "total_taxable_inr": float(total_taxable.quantize(Decimal("0.01"))),
            "total_gst_inr": float(total_gst.quantize(Decimal("0.01"))),
            "by_gst_rate_percent": by_rate,
        }

    with factory() as session:
        with session.begin():
            existing = session.scalars(
                select(GstRecord).where(
                    GstRecord.organization_id == oid,
                    GstRecord.period_start == period_start,
                )
            ).first()
            if existing:
                existing.data = data
            else:
                session.add(
                    GstRecord(organization_id=oid, period_start=period_start, data=data)
                )

    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="gst_report",
        metadata={"channel": "billing_phase2.gst_report", "period_start": period_start.isoformat()},
    )
    return {"ok": True, "report": data, "gst_record_period_start": period_start.isoformat()}
