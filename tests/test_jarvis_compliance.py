"""GST statutory lines, email classification, JARVIS helpers."""

from __future__ import annotations

from decimal import Decimal

from tools.email_reader import EmailCategory, classify_email, is_jarvis_emergency, jarvis_alert_tier
from services.gst_compute import (
    StatutoryLineInput,
    build_invoice_from_inventory_sale,
    build_statutory_invoice_line,
    format_invoice_lines_statutory_text,
)


def test_classify_government_tax():
    c = classify_email(
        subject="GSTR-3B filing reminder — due date approaching",
        from_addr="noreply@gst.gov.in",
        body="Please file your return before the due date to avoid late fee.",
    )
    assert c is EmailCategory.government_tax


def test_classify_customer_order():
    c = classify_email(
        subject="Purchase Order #4421 — dispatch requested",
        from_addr="buyer@example.com",
        body="Please confirm 200 units SKU-A at earliest.",
    )
    assert c is EmailCategory.customer_order


def test_jarvis_emergency_gov_notice():
    assert is_jarvis_emergency(
        EmailCategory.government_tax,
        "Demand notice under Section 74",
        "Outstanding tax demand; reply within 7 days.",
    )


def test_jarvis_not_emergency_generic_order():
    assert not is_jarvis_emergency(
        EmailCategory.customer_order,
        "PO 99 attached",
        "Standard delivery next week.",
    )


def test_jarvis_emergency_urgent_order_subject():
    assert is_jarvis_emergency(
        EmailCategory.customer_order,
        "URGENT: PO revision",
        "Need shipment today.",
    )
    assert jarvis_alert_tier(EmailCategory.customer_order, "Rush order", "qty 10") == "emergency"


def test_statutory_line_intra_state():
    line = build_statutory_invoice_line(
        StatutoryLineInput(
            description="HDPE Pipe 90mm",
            hsn_sac_code="3917",
            quantity=Decimal("4"),
            unit_price_pre_tax=Decimal("250.00"),
            gst_rate_percent=Decimal("18"),
        ),
        use_igst=False,
        line_no=1,
    )
    assert line["hsn_sac"] == "3917"
    assert line["supply_type"] == "intra_state_cgst_sgst"
    assert line["cgst"] > 0 and line["sgst"] > 0 and line["igst"] == 0


def test_statutory_line_inter_state():
    line = build_invoice_from_inventory_sale(
        sku_name="Item",
        hsn_code="1006",
        quantity=Decimal("2"),
        unit_price_pre_tax=Decimal("100"),
        gst_rate_percent=Decimal("5"),
        use_igst=True,
    )
    assert line["igst"] > 0
    assert line["cgst"] == 0 and line["sgst"] == 0


def test_format_invoice_statutory_text():
    text = format_invoice_lines_statutory_text(
        [
            {
                "sku_name": "Rice 1kg",
                "hsn_sac": "1006",
                "quantity": 2,
                "taxable_value": 200.0,
                "gst_rate_percent": 5.0,
                "cgst": 5.0,
                "sgst": 5.0,
                "igst": 0.0,
                "line_total_with_tax": 210.0,
            }
        ],
        seller_gstin="29AAAAA0000A1Z5",
        invoice_no="INV-1",
    )
    assert "TAX INVOICE" in text
    assert "1006" in text
