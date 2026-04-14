"""Upgrade 5 — auto accounting: categorization, CSV, GST, invoice match, receipt preview."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from services.auto_accounting_service import (
    categorize_vendor_sync,
    create_receipt_preview_sync,
    enrich_invoice_lines_with_gst_sync,
    gst_rate_from_hsn_sync,
    import_bank_statement_sync,
    match_unpaid_invoices_sync,
    parse_bank_statement_csv_sync,
)


def test_categorize_swiggy():
    cat, reason = categorize_vendor_sync("Swiggy Ltd", "order food")
    assert cat == "food"
    assert reason == "keyword"


def test_gst_rate_from_hsn():
    out = gst_rate_from_hsn_sync("85171200", "mobile handset")
    assert out["gst_rate_percent"] == 18.0


def test_enrich_invoice_lines_fills_zero_gst():
    lines = [{"description": "Test", "quantity": 1, "unit_price_pre_tax": 100, "gst_rate_percent": 0, "hsn_code": "8517"}]
    out = enrich_invoice_lines_with_gst_sync(lines)
    assert float(out[0]["gst_rate_percent"]) > 0


def test_parse_bank_csv():
    raw = b"Date,Description,Debit,Credit,Balance\n2026-04-01,SWIGGY,850.00,,10000\n"
    p = parse_bank_statement_csv_sync(raw)
    assert p.get("ok") is True
    assert len(p.get("transactions") or []) >= 1


@patch("services.business_depth_service.record_operational_expense")
def test_import_bank_creates_debit(mock_rec):
    mock_rec.return_value = (True, "ok", 99)
    txs = [{"date": "2026-04-01", "description": "SWIGGY FOOD", "debit": 850.0, "credit": None}]
    out = import_bank_statement_sync(organization_id=1, transactions=txs, user_id=1)
    assert out.get("ok") is True
    assert mock_rec.called


@patch("services.billing_phase2_service.list_invoices_sync")
def test_match_unpaid(mock_list):
    mock_list.return_value = {
        "invoices": [
            {
                "id": 5,
                "invoice_no": "INV-1",
                "grand_total_inr": 1000.0,
                "payment_status": "unpaid",
                "payments": [],
            }
        ]
    }
    out = match_unpaid_invoices_sync(organization_id=1, amount_inr=Decimal("1000"))
    assert out.get("ok") is True
    assert len(out.get("matches") or []) == 1


@patch("services.auto_accounting_service._gemini_vision_receipt")
@patch("services.auto_accounting_service._groq_vision_receipt")
def test_scan_receipt_preview(mock_groq, mock_gem):
    mock_groq.return_value = None
    mock_gem.return_value = {
        "vendor_name": "Test Cafe",
        "amount": 120.5,
        "date": "2026-04-01",
        "category": "food",
        "confidence": 0.9,
        "needs_review": False,
        "raw_summary": "coffee",
    }
    out = create_receipt_preview_sync(b"fakeimg", content_type="image/jpeg")
    assert out.get("ok") is True
    assert out.get("preview_token")


@patch("services.personal_command_center_service.create_expense_sync")
@patch("services.auto_accounting_service._preview_pop")
def test_confirm_receipt_creates(mock_pop, mock_create):
    mock_pop.return_value = {"scan": {"ok": True, "vendor_name": "X", "amount": 10, "category": "food", "needs_review": False}}
    mock_create.return_value = (True, "ok", 1)
    from services.auto_accounting_service import confirm_receipt_expense_sync

    ok, msg, eid = confirm_receipt_expense_sync(
        user_id=1,
        preview_token="tok",
        amount=Decimal("10"),
        category="food",
        fernet=None,
    )
    assert ok and eid == 1
    mock_create.assert_called_once()
