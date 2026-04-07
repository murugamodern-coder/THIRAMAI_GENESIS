"""
THIRAMAI SaaS Factory — Level 1 billing MVP.

Manual pipe line item: Length (m), Grade, Weight (kg) + rate → basic PDF invoice.
Install: python -m pip install fpdf2
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError as exc:  # pragma: no cover - runtime hint
    raise SystemExit("Install fpdf2: python -m pip install fpdf2") from exc


ROOT = Path(__file__).resolve().parent.parent


def dated_invoice_directory(now: datetime | None = None) -> Path:
    """factory_output/YYYY/MM/Invoices/ (month-year archive)."""
    dt = now or datetime.now()
    return ROOT / "factory_output" / f"{dt.year:04d}" / f"{dt.month:02d}" / "Invoices"


def default_invoice_path(now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return dated_invoice_directory(now) / f"invoice_{stamp}.pdf"


def format_inr_indian(amount: float) -> str:
    """Indian numbering (lakhs/crores style): 12,34,567.89 — always two decimal paisa."""
    neg = amount < 0
    a = abs(amount)
    s = f"{a:.2f}"
    int_part, frac = s.split(".")
    n = len(int_part)
    if n <= 3:
        grouped = int_part
    else:
        chunks: list[str] = [int_part[-3:]]
        i = n - 3
        while i > 0:
            start = max(0, i - 2)
            chunks.insert(0, int_part[start:i])
            i = start
        grouped = ",".join(chunks)
    sign = "-" if neg else ""
    return f"Rs. {sign}{grouped}.{frac}"


class InvoicePDF(FPDF):
    def header(self) -> None:
        self.set_draw_color(55, 55, 52)
        self.set_line_width(0.35)
        m = 9.0
        self.rect(m, m, self.w - 2 * m, self.h - 2 * m)
        self.set_y(m + 4)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(20, 20, 20)
        self.cell(0, 9, "TAX INVOICE", new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(90, 90, 90)
        self.cell(0, 5, "THIRAMAI factory/billing_tool.py - verify with CA before filing", align="C")
        self.ln(6)

    def footer(self) -> None:
        self.set_y(-22)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(70, 70, 70)
        self.cell(0, 5, "Thank you for your business.", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 7)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="C")


def build_invoice_pdf(
    *,
    buyer_name: str,
    buyer_address: str,
    invoice_no: str,
    invoice_date: str,
    length_m: float,
    grade: str,
    weight_kg: float,
    rate_per_kg: float,
    gst_percent: float,
    seller_name: str,
    seller_address: str,
    seller_gstin: str,
    out_path: Path,
    organization_id: int | None = None,
    append_master_index: bool = True,
) -> Path:
    subtotal = weight_kg * rate_per_kg
    gst_amt = subtotal * (gst_percent / 100.0)
    grand = subtotal + gst_amt
    _inr = format_inr_indian

    pdf = InvoicePDF()
    pdf.alias_nb_pages()
    pdf.set_margins(16, 16, 16)
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_page()

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(25, 25, 25)
    pdf.multi_cell(0, 5, f"Seller:\n{seller_name}\n{seller_address}\nGSTIN: {seller_gstin}")
    pdf.ln(3)
    pdf.multi_cell(0, 5, f"Buyer:\n{buyer_name}\n{buyer_address}")
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 7, f"Invoice No: {invoice_no}")
    pdf.cell(0, 7, f"Date: {invoice_date}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(22, 8, "Length (m)", border=1)
    pdf.cell(52, 8, "Grade", border=1)
    pdf.cell(24, 8, "Wt (kg)", border=1)
    pdf.cell(28, 8, "Rate/kg", border=1)
    pdf.cell(0, 8, "Line total", border=1, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    line_total = weight_kg * rate_per_kg
    pdf.cell(22, 8, f"{length_m:.2f}", border=1)
    safe_grade = (grade or "").encode("latin-1", "replace").decode("latin-1")[:32]
    pdf.cell(52, 8, safe_grade, border=1)
    pdf.cell(24, 8, f"{weight_kg:.3f}", border=1)
    pdf.cell(28, 8, _inr(rate_per_kg), border=1)
    pdf.cell(0, 8, _inr(line_total), border=1, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    w_label = 130
    pdf.cell(w_label, 7, "")
    pdf.cell(35, 7, "Subtotal")
    pdf.cell(0, 7, _inr(subtotal), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w_label, 7, "")
    pdf.cell(35, 7, f"GST ({gst_percent:g}%)")
    pdf.cell(0, 7, _inr(gst_amt), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(w_label, 7, "")
    pdf.cell(35, 7, "Grand total")
    pdf.cell(0, 7, _inr(grand), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_draw_color(120, 120, 118)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 5, "Digital signature / company stamp", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    x0, y0 = pdf.get_x(), pdf.get_y()
    pdf.rect(x0, y0, 72, 22, style="D")
    pdf.set_xy(x0 + 2, y0 + 14)
    pdf.set_font("Helvetica", "I", 7)
    pdf.cell(68, 4, "Authorized signatory")
    pdf.set_xy(x0, y0 + 24)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    resolved = out_path.resolve()
    if append_master_index:
        try:
            import asset_portal

            rel = resolved.relative_to(asset_portal.FACTORY_OUTPUT.resolve()).as_posix()
            note = f"grade={grade}; weight_kg={weight_kg}; revenue_inr={grand:.2f}"
            if organization_id is not None:
                note = asset_portal.append_organization_to_index_note(note, int(organization_id))
            asset_portal.append_master_index_row(
                zone="factory",
                relative_path=rel,
                kind="invoice",
                title=f"Invoice {invoice_no}",
                size_bytes=resolved.stat().st_size if resolved.is_file() else 0,
                note=note,
            )
        except Exception:
            pass
    return resolved


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate a simple PDF invoice from pipe Length, Grade, Weight (+ rate)."
    )
    ap.add_argument("--buyer", default="Buyer", help="Buyer name")
    ap.add_argument("--buyer-address", default="", help="Buyer address")
    ap.add_argument("--invoice-no", default="", help="Invoice number (default auto)")
    ap.add_argument("--date", default="", help="Invoice date YYYY-MM-DD (default: today)")
    ap.add_argument("--length", type=float, required=True, help="Pipe length in meters")
    ap.add_argument("--grade", required=True, help="Material grade e.g. HDPE PE100")
    ap.add_argument("--weight", type=float, required=True, help="Weight in kg")
    ap.add_argument("--rate", type=float, required=True, help="INR per kg")
    ap.add_argument("--gst", type=float, default=18.0, help="GST percent on subtotal")
    ap.add_argument("--seller", default="Your legal business name", help="Seller name")
    ap.add_argument("--seller-address", default="", help="Seller address")
    ap.add_argument("--seller-gstin", default="", help="Seller GSTIN")
    ap.add_argument("--out", default="", help="Output .pdf path")
    args = ap.parse_args()

    inv_date = (args.date or "").strip() or date.today().isoformat()
    inv_no = (args.invoice_no or "").strip() or f"INV-{inv_date.replace('-', '')}-01"

    if args.out.strip():
        out = Path(args.out)
    else:
        out = default_invoice_path()

    path = build_invoice_pdf(
        buyer_name=args.buyer,
        buyer_address=args.buyer_address or "-",
        invoice_no=inv_no,
        invoice_date=inv_date,
        length_m=args.length,
        grade=args.grade,
        weight_kg=args.weight,
        rate_per_kg=args.rate,
        gst_percent=args.gst,
        seller_name=args.seller,
        seller_address=args.seller_address or "-",
        seller_gstin=args.seller_gstin or "-",
        out_path=out,
    )
    print(path)


if __name__ == "__main__":
    main()
