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
from core.db.models import Bill, GstRecord, Invoice, InvoiceItem, Payment
from services import audit_log as system_audit


def _dec(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def _html_escape(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _eway_block_html(inv: Invoice) -> str:
    e = getattr(inv, "eway_bill_no", None) or ""
    v = getattr(inv, "vehicle_no", None) or ""
    t = getattr(inv, "transport_mode", None) or ""
    c = getattr(inv, "consignee_place", None) or ""
    if not any((e, v, t, c)):
        return ""
    parts = []
    if e:
        parts.append(f"E-way bill: {_html_escape(e)}")
    if v:
        parts.append(f"Vehicle: {_html_escape(v)}")
    if t:
        parts.append(f"Transport: {_html_escape(t)}")
    if c:
        parts.append(f"Place of supply: {_html_escape(c)}")
    return "<div class='meta'><strong>E-way / dispatch</strong><br/>" + "<br/>".join(parts) + "</div>"


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
        "eway_bill_no": getattr(inv, "eway_bill_no", None),
        "vehicle_no": getattr(inv, "vehicle_no", None),
        "transport_mode": getattr(inv, "transport_mode", None),
        "consignee_place": getattr(inv, "consignee_place", None),
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
    eway_bill_no: str | None = None,
    vehicle_no: str | None = None,
    transport_mode: str | None = None,
    consignee_place: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    if not lines:
        return {"ok": False, "error": "lines required"}
    no = (invoice_no or "").strip() or f"INV-{date.today().isoformat()}"
    idate = invoice_date or date.today()

    lines_enriched: list[dict[str, Any]] = list(lines)
    try:
        from services.auto_accounting_service import enrich_invoice_lines_with_gst_sync

        lines_enriched = enrich_invoice_lines_with_gst_sync(lines_enriched, supply_intra_state=True)
    except Exception:
        lines_enriched = list(lines)

    parsed: list[tuple[int, str, Decimal, Decimal, Decimal, Decimal, str | None]] = []
    grand = Decimal("0")
    for idx, ln in enumerate(lines_enriched, start=1):
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
                eway_bill_no=(eway_bill_no or "").strip()[:128] or None,
                vehicle_no=(vehicle_no or "").strip()[:64] or None,
                transport_mode=(transport_mode or "").strip()[:32] or None,
                consignee_place=(consignee_place or "").strip()[:512] or None,
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
    try:
        from services.jarvis_agent_event_engine import record_invoice_created_event_sync

        record_invoice_created_event_sync(
            organization_id=oid,
            invoice_id=iid,
            invoice_no=no,
            grand_total_inr=float(grand),
            user_id=user_id,
        )
    except Exception:
        pass
    return {"ok": True, "invoice_id": iid, "grand_total_inr": float(grand), "invoice_no": no}


def list_bills_sync(*, organization_id: int, limit: int = 100) -> dict[str, Any]:
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
                select(Bill).where(Bill.organization_id == oid).order_by(Bill.id.desc()).limit(lim)
            ).all()
        )
        items = [
            {
                "id": int(r.id),
                "total_amount_inr": float(r.total_amount or 0),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "line_count": len(r.items) if isinstance(r.items, list) else 0,
            }
            for r in rows
        ]
    return {"ok": True, "bills": items}


def list_invoices_sync(
    *,
    organization_id: int,
    limit: int = 200,
    status: str | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 500))
    wanted_status = (status or "").strip().lower()
    with factory() as session:
        stmt = select(Invoice).where(Invoice.organization_id == oid)
        if wanted_status:
            if wanted_status == "pending":
                stmt = stmt.where(Invoice.payment_status.in_(("unpaid", "partial")))
            else:
                stmt = stmt.where(Invoice.payment_status == wanted_status)
        rows = list(session.scalars(stmt.order_by(Invoice.id.desc()).limit(lim)).all())
        items = [_serialize_invoice(r, session, include_lines=True) for r in rows]
    return {"ok": True, "invoices": items, "status_filter": wanted_status or None}


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


def create_simple_cash_bill_sync(
    *,
    organization_id: int,
    lines: list[dict[str, Any]],
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Non-GST retail / cash bill: one row per line, ``unit_price_inr`` is tax-inclusive (no GST split).
    """
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    if not lines:
        return {"ok": False, "error": "lines required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    items: list[dict[str, Any]] = []
    grand = Decimal("0")
    for ln in lines:
        desc = str(ln.get("description") or "Item").strip()[:2000]
        qty = _dec(ln.get("quantity", 1))
        if qty <= 0:
            return {"ok": False, "error": "each line needs positive quantity"}
        up = _dec(ln.get("unit_price_inr"))
        if up < 0:
            return {"ok": False, "error": "unit_price_inr must be non-negative"}
        line_tot = (qty * up).quantize(Decimal("0.01"))
        grand += line_tot
        items.append(
            {
                "description": desc,
                "quantity": float(qty),
                "unit_price_pre_tax": float(up),
                "taxable_value": float(line_tot),
                "gst_rate_percent": 0.0,
                "cgst": 0.0,
                "sgst": 0.0,
                "igst": 0.0,
                "gst_total": 0.0,
                "line_total_with_tax": float(line_tot),
                "supply_type": "non_gst_cash",
            }
        )

    bid = 0
    with factory() as session:
        with session.begin():
            bill = Bill(organization_id=oid, items=items, total_amount=grand)
            session.add(bill)
            session.flush()
            bid = int(bill.id)

    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="bill",
        metadata={
            "channel": "billing_phase2.simple_cash_bill",
            "bill_id": bid,
            "grand_total_inr": float(grand),
        },
    )
    return {"ok": True, "bill_id": bid, "total_amount_inr": float(grand)}


def build_structured_invoice_html_sync(
    *,
    organization_id: int,
    invoice_id: int,
    supply_mode: str = "intra",
) -> dict[str, Any]:
    """
    Printable tax invoice HTML. ``supply_mode`` ``intra`` → CGST+SGST split; ``inter`` → IGST.
    """
    oid = int(organization_id)
    iid = int(invoice_id)
    if oid <= 0 or iid <= 0:
        return {"ok": False, "error": "organization_id and invoice_id required"}
    mode = (supply_mode or "intra").strip().lower()
    inter = mode in ("inter", "interstate", "igst")

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    with factory() as session:
        inv = session.get(Invoice, iid)
        if inv is None or int(inv.organization_id) != oid:
            return {"ok": False, "error": "invoice not found"}
        lines = list(
            session.scalars(
                select(InvoiceItem).where(InvoiceItem.invoice_id == iid).order_by(InvoiceItem.line_no)
            ).all()
        )

    rows_html: list[str] = []
    total_taxable = Decimal("0")
    total_gst = Decimal("0")
    total_cgst = Decimal("0")
    total_sgst = Decimal("0")
    total_igst = Decimal("0")

    for li in lines:
        qty = _dec(li.quantity)
        up = _dec(li.unit_price_pre_tax)
        taxable = (qty * up).quantize(Decimal("0.01"))
        gstp = _dec(li.gst_rate_percent)
        gst_amt = (taxable * gstp / Decimal("100")).quantize(Decimal("0.01"))
        if inter:
            cgst = Decimal("0")
            sgst = Decimal("0")
            igst = gst_amt
        else:
            half = (gst_amt / Decimal("2")).quantize(Decimal("0.01"))
            cgst = half
            sgst = gst_amt - half
            igst = Decimal("0")
        total_taxable += taxable
        total_gst += gst_amt
        total_cgst += cgst
        total_sgst += sgst
        total_igst += igst
        hsn = (li.hsn_code or "") or "—"
        rows_html.append(
            "<tr>"
            f"<td>{li.line_no}</td>"
            f"<td>{_html_escape(li.description)}</td>"
            f"<td>{hsn}</td>"
            f"<td class='num'>{float(qty):g}</td>"
            f"<td class='num'>{float(up):.2f}</td>"
            f"<td class='num'>{float(taxable):.2f}</td>"
            f"<td class='num'>{float(gstp):g}%</td>"
            f"<td class='num'>{float(cgst):.2f}</td>"
            f"<td class='num'>{float(sgst):.2f}</td>"
            f"<td class='num'>{float(igst):.2f}</td>"
            f"<td class='num'>{float(li.line_total_inr):.2f}</td>"
            "</tr>"
        )

    grand = _dec(inv.grand_total_inr)
    title = "Tax Invoice (IGST)" if inter else "Tax Invoice (CGST / SGST)"
    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>{_html_escape(inv.invoice_no)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; color: #111; }}
h1 {{ font-size: 1.25rem; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 0.9rem; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; }}
th {{ background: #f4f4f4; text-align: left; }}
td.num {{ text-align: right; }}
.meta {{ margin: 8px 0; color: #444; }}
.totals {{ margin-top: 16px; text-align: right; }}
@media print {{ body {{ margin: 12px; }} }}
</style></head><body>
<h1>{title}</h1>
<div class="meta">Invoice No: <strong>{_html_escape(inv.invoice_no)}</strong>
 &nbsp;|&nbsp; Date: {_html_escape(inv.invoice_date.isoformat() if inv.invoice_date else '')}
 &nbsp;|&nbsp; Status: {_html_escape(inv.payment_status)}</div>
<table>
<thead><tr><th>#</th><th>Description</th><th>HSN</th><th>Qty</th><th>Rate</th><th>Taxable</th><th>GST%</th>
<th>CGST</th><th>SGST</th><th>IGST</th><th>Line total</th></tr></thead>
<tbody>{"".join(rows_html)}</tbody>
</table>
<div class="totals">
<div>Taxable value: ₹{float(total_taxable):,.2f}</div>
<div>CGST: ₹{float(total_cgst):,.2f} &nbsp; SGST: ₹{float(total_sgst):,.2f} &nbsp; IGST: ₹{float(total_igst):,.2f}</div>
<div><strong>Grand total: ₹{float(grand):,.2f}</strong></div>
</div>
{_eway_block_html(inv)}
<p class="meta">Supply: {"Inter-state (IGST)" if inter else "Intra-state (CGST + SGST)"}. Use browser Print → Save as PDF.</p>
</body></html>"""
    return {"ok": True, "html": body}


def build_structured_invoice_pdf_bytes_sync(
    *,
    organization_id: int,
    invoice_id: int,
    supply_mode: str = "intra",
) -> dict[str, Any]:
    """Simple PDF export (requires ``fpdf2``)."""
    try:
        from fpdf import FPDF
    except ImportError:
        return {"ok": False, "error": "fpdf2 not installed (pip install fpdf2)"}

    oid = int(organization_id)
    iid = int(invoice_id)
    if oid <= 0 or iid <= 0:
        return {"ok": False, "error": "organization_id and invoice_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        inv = session.get(Invoice, iid)
        if inv is None or int(inv.organization_id) != oid:
            return {"ok": False, "error": "invoice not found"}
        lines = list(
            session.scalars(
                select(InvoiceItem).where(InvoiceItem.invoice_id == iid).order_by(InvoiceItem.line_no)
            ).all()
        )

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Tax Invoice", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"No: {inv.invoice_no}  Date: {inv.invoice_date or ''}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Payment: {inv.payment_status}  Grand total: Rs. {float(inv.grand_total_inr):,.2f}", new_x="LMARGIN", new_y="NEXT")
    ew = getattr(inv, "eway_bill_no", None) or ""
    if ew:
        pdf.cell(0, 6, f"E-way: {ew}", new_x="LMARGIN", new_y="NEXT")
    vn = getattr(inv, "vehicle_no", None) or ""
    if vn:
        pdf.cell(0, 6, f"Vehicle: {vn}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(10, 7, "#", border=1)
    pdf.cell(70, 7, "Description", border=1)
    pdf.cell(15, 7, "HSN", border=1)
    pdf.cell(15, 7, "Qty", border=1)
    pdf.cell(20, 7, "Total", border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    for li in lines:
        desc = (li.description or "")[:42]
        hsn = (li.hsn_code or "")[:8]
        pdf.cell(10, 6, str(li.line_no), border=1)
        pdf.cell(70, 6, desc, border=1)
        pdf.cell(15, 6, hsn, border=1)
        pdf.cell(15, 6, str(float(li.quantity)), border=1)
        pdf.cell(20, 6, f"{float(li.line_total_inr):.2f}", border=1, new_x="LMARGIN", new_y="NEXT")
    raw = pdf.output(dest="S")
    data = raw if isinstance(raw, (bytes, bytearray)) else raw.encode("latin-1")
    return {"ok": True, "pdf_bytes": bytes(data)}


def build_cash_bill_html_sync(*, organization_id: int, bill_id: int) -> dict[str, Any]:
    """Printable HTML for a non-GST ``bills`` row."""
    oid = int(organization_id)
    bid = int(bill_id)
    if oid <= 0 or bid <= 0:
        return {"ok": False, "error": "organization_id and bill_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        row = session.get(Bill, bid)
        if row is None or int(row.organization_id) != oid:
            return {"ok": False, "error": "bill not found"}
        items = row.items or []
        total = float(row.total_amount or 0)
        created = row.created_at.isoformat() if row.created_at else ""

    rows: list[str] = []
    for i, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            continue
        desc = _html_escape(str(it.get("description") or it.get("sku_name") or "Item"))
        qty = it.get("quantity", 0)
        line_tot = it.get("line_total_with_tax", it.get("taxable_value", 0))
        rows.append(
            f"<tr><td>{i}</td><td>{desc}</td><td class='num'>{qty}</td>"
            f"<td class='num'>{float(line_tot or 0):.2f}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>Bill #{bid}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
th, td {{ border: 1px solid #ccc; padding: 8px; }}
td.num {{ text-align: right; }}
</style></head><body>
<h1>Bill (non-GST)</h1>
<p>Bill #{bid} &nbsp;|&nbsp; {created}</p>
<table><thead><tr><th>#</th><th>Item</th><th>Qty</th><th>Amount</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<p><strong>Total: ₹{total:,.2f}</strong></p>
<p style="color:#555">Print or Save as PDF from your browser.</p>
</body></html>"""
    return {"ok": True, "html": html}
