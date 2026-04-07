"""
Indian GST line computation for retail bills (taxable value + CGST/SGST or IGST).

``unit_price`` is treated as **pre-tax** (taxable) per unit. ``gst_rate_percent`` is the total rate
(e.g. 18 for 18%). Amounts are quantized to **2 decimal places** (paise).

Statutory helpers: HSN/SAC-labelled line items and plain-text invoice blocks for PDFs / prints.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def compute_gst_line(
    taxable_value: Decimal,
    gst_rate_percent: Decimal,
    *,
    use_igst: bool,
) -> dict[str, Decimal]:
    """
    Return taxable, component taxes, gst_total, grand_total (all quantized to 0.01).

    Intra-state: CGST + SGST each half the nominal rate (e.g. 9% + 9% of taxable for 18% slab).
    Inter-state: full rate as IGST.
    """
    tv = taxable_value.quantize(Decimal("0.01"))
    rate = (gst_rate_percent or Decimal("0")).quantize(Decimal("0.01"))
    if rate <= 0:
        return {
            "taxable_value": tv,
            "cgst": Decimal("0.00"),
            "sgst": Decimal("0.00"),
            "igst": Decimal("0.00"),
            "gst_total": Decimal("0.00"),
            "grand_total": tv,
        }
    gst_total = (tv * rate / Decimal("100")).quantize(Decimal("0.01"))
    if use_igst:
        igst = gst_total
        cgst = Decimal("0.00")
        sgst = Decimal("0.00")
    else:
        igst = Decimal("0.00")
        cgst = (gst_total / Decimal("2")).quantize(Decimal("0.01"))
        sgst = (gst_total - cgst).quantize(Decimal("0.01"))
    grand = (tv + gst_total).quantize(Decimal("0.01"))
    return {
        "taxable_value": tv,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "gst_total": gst_total,
        "grand_total": grand,
    }


def _money_inr(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01")))


@dataclass(frozen=True)
class StatutoryLineInput:
    """One invoice line before GST split."""

    description: str
    hsn_sac_code: str
    quantity: Decimal
    unit_price_pre_tax: Decimal
    gst_rate_percent: Decimal


def build_statutory_invoice_line(
    line: StatutoryLineInput,
    *,
    use_igst: bool,
    line_no: int = 1,
) -> dict[str, Any]:
    """
    Full line dict for bills / PDFs: HSN/SAC, taxable value, rate, CGST/SGST or IGST, totals.

    CGST/SGST are each half the nominal slab rate applied to taxable value; IGST is the full slab.
    """
    qty = (line.quantity or Decimal("0")).quantize(Decimal("0.0001"))
    unit = (line.unit_price_pre_tax or Decimal("0")).quantize(Decimal("0.01"))
    taxable = (qty * unit).quantize(Decimal("0.01"))
    rate = (line.gst_rate_percent or Decimal("0")).quantize(Decimal("0.01"))
    parts = compute_gst_line(taxable, rate, use_igst=use_igst)
    hsn = (line.hsn_sac_code or "").strip() or "—"
    desc = (line.description or "").strip() or "Item"
    return {
        "line_no": int(line_no),
        "description": desc,
        "hsn_sac": hsn,
        "quantity": float(qty),
        "unit_price_pre_tax": float(unit),
        "taxable_value": float(parts["taxable_value"]),
        "gst_rate_percent": float(rate),
        "cgst": float(parts["cgst"]),
        "sgst": float(parts["sgst"]),
        "igst": float(parts["igst"]),
        "gst_total": float(parts["gst_total"]),
        "line_total_with_tax": float(parts["grand_total"]),
        "supply_type": "inter_state_igst" if use_igst else "intra_state_cgst_sgst",
    }


def format_invoice_lines_statutory_text(
    lines: list[dict[str, Any]],
    *,
    seller_gstin: str = "",
    buyer_gstin: str = "",
    invoice_no: str = "",
    invoice_date_iso: str = "",
    place_of_supply: str = "",
) -> str:
    """
    Human-readable statutory block (India GST style). Not legal advice; verify with your CA.

    ``lines`` should match keys from ``build_statutory_invoice_line`` or bill ``items`` with
    compatible fields (``hsn_sac`` or ``hsn_code``, ``description`` or ``sku_name``).
    """
    header = [
        "TAX INVOICE (STATUTORY SUMMARY)",
        "--------------------------------",
    ]
    if seller_gstin:
        header.append(f"Supplier GSTIN: {seller_gstin}")
    if buyer_gstin:
        header.append(f"Recipient GSTIN: {buyer_gstin}")
    if invoice_no:
        header.append(f"Invoice No.: {invoice_no}")
    if invoice_date_iso:
        header.append(f"Invoice Date: {invoice_date_iso}")
    if place_of_supply:
        header.append(f"Place of supply: {place_of_supply}")
    header.append("")
    header.append(
        f"{'#':<3} {'HSN/SAC':<10} {'Description':<22} {'Qty':>8} {'Taxable':>12} "
        f"{'Rate%':>6} {'CGST':>10} {'SGST':>10} {'IGST':>10} {'Total':>12}"
    )
    header.append("-" * 110)
    rows: list[str] = []
    grand_taxable = Decimal("0")
    grand_gst = Decimal("0")
    grand_total = Decimal("0")
    for i, raw in enumerate(lines, start=1):
        if not isinstance(raw, dict):
            continue
        hsn = str(raw.get("hsn_sac") or raw.get("hsn_code") or "—")[:16]
        desc = str(raw.get("description") or raw.get("sku_name") or "Item")[:22]
        qty = Decimal(str(raw.get("quantity") or 0))
        tv = Decimal(str(raw.get("taxable_value") or 0)).quantize(Decimal("0.01"))
        rate = Decimal(str(raw.get("gst_rate_percent") or 0)).quantize(Decimal("0.01"))
        cg = Decimal(str(raw.get("cgst") or 0)).quantize(Decimal("0.01"))
        sg = Decimal(str(raw.get("sgst") or 0)).quantize(Decimal("0.01"))
        ig = Decimal(str(raw.get("igst") or 0)).quantize(Decimal("0.01"))
        lt = Decimal(str(raw.get("line_total_with_tax") or tv + cg + sg + ig)).quantize(Decimal("0.01"))
        grand_taxable += tv
        grand_gst += cg + sg + ig
        grand_total += lt
        rows.append(
            f"{i:<3} {hsn:<10} {desc:<22} {str(qty):>8} {_money_inr(tv):>12} "
            f"{str(rate):>6} {_money_inr(cg):>10} {_money_inr(sg):>10} {_money_inr(ig):>10} {_money_inr(lt):>12}"
        )
    footer = [
        "-" * 110,
        f"{'TOTAL':<46} {_money_inr(grand_taxable):>12} {'':>6} {'':>10} {'':>10} {'':>10} {_money_inr(grand_total):>12}",
        f"Total GST (CGST+SGST+IGST): ₹{_money_inr(grand_gst)}",
        "",
        "Amounts in INR. Rounding per line to 2 decimals.",
    ]
    return "\n".join(header + rows + footer)


def build_invoice_from_inventory_sale(
    *,
    sku_name: str,
    hsn_code: str | None,
    quantity: Decimal,
    unit_price_pre_tax: Decimal,
    gst_rate_percent: Decimal,
    use_igst: bool,
) -> dict[str, Any]:
    """Convenience: one statutory line from a retail SKU sale."""
    return build_statutory_invoice_line(
        StatutoryLineInput(
            description=sku_name,
            hsn_sac_code=(hsn_code or "").strip(),
            quantity=quantity,
            unit_price_pre_tax=unit_price_pre_tax,
            gst_rate_percent=gst_rate_percent,
        ),
        use_igst=use_igst,
        line_no=1,
    )
