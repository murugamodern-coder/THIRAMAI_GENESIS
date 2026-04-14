"""
Upgrade 5 — Auto accounting AI: receipt vision, bank import, categorization, invoice match, GST hints.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import re
import secrets
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from services.research_common import groq_json_object_sync, parse_json_lenient

_log = logging.getLogger("thiramai.auto_accounting")

_PREVIEW_LOCK = threading.Lock()
_PREVIEW_STORE: dict[str, tuple[float, dict[str, Any]]] = {}
_PREVIEW_TTL_SEC = 3600.0

_VENDOR_KEYWORD_CATEGORY: list[tuple[str, str]] = [
    ("swiggy", "food"),
    ("zomato", "food"),
    ("uber", "transport"),
    ("ola", "transport"),
    ("petrol", "fuel"),
    ("diesel", "fuel"),
    ("hp ", "fuel"),
    ("shell", "fuel"),
    ("indian oil", "fuel"),
    ("bharat", "fuel"),
    ("amazon", "materials"),
    ("flipkart", "materials"),
    ("railway", "transport"),
    ("irctc", "transport"),
    ("hospital", "health"),
    ("pharmacy", "health"),
    ("medical", "health"),
    ("school", "education"),
    ("fees", "education"),
    ("electricity", "utilities"),
    ("tneb", "utilities"),
    ("bsnl", "utilities"),
    ("airtel", "utilities"),
    ("jio", "utilities"),
    ("rent", "housing"),
    ("emi", "loans"),
    ("loan", "loans"),
    ("bank charges", "banking"),
    ("gst", "taxes"),
]

_HSN_PREFIX_RATE: list[tuple[str, Decimal]] = [
    ("0401", Decimal("5")),
    ("0402", Decimal("5")),
    ("1905", Decimal("5")),
    ("2106", Decimal("12")),
    ("8517", Decimal("18")),
    ("8471", Decimal("18")),
    ("9999", Decimal("18")),
]


def _preview_put(payload: dict[str, Any]) -> str:
    tok = secrets.token_urlsafe(24)
    with _PREVIEW_LOCK:
        _prune_previews_locked()
        _PREVIEW_STORE[tok] = (time.monotonic() + _PREVIEW_TTL_SEC, payload)
    return tok


def _preview_get(token: str) -> dict[str, Any] | None:
    with _PREVIEW_LOCK:
        _prune_previews_locked()
        ent = _PREVIEW_STORE.get(token)
        if not ent:
            return None
        exp, payload = ent
        if time.monotonic() > exp:
            _PREVIEW_STORE.pop(token, None)
            return None
        return dict(payload)


def _preview_pop(token: str) -> dict[str, Any] | None:
    with _PREVIEW_LOCK:
        _prune_previews_locked()
        ent = _PREVIEW_STORE.pop(token, None)
        if not ent:
            return None
        exp, payload = ent
        if time.monotonic() > exp:
            return None
        return dict(payload)


def _prune_previews_locked() -> None:
    now = time.monotonic()
    dead = [k for k, (exp, _) in _PREVIEW_STORE.items() if now > exp]
    for k in dead:
        _PREVIEW_STORE.pop(k, None)


def categorize_vendor_sync(vendor: str, description: str = "") -> tuple[str, str]:
    """
    Returns (category, reason) where reason is 'keyword' | 'pattern' | 'llm' | 'default'.
    """
    blob = f"{vendor} {description}".lower()
    for kw, cat in _VENDOR_KEYWORD_CATEGORY:
        if kw in blob:
            return cat, "keyword"
    parsed = groq_json_object_sync(
        system='Output STRICT JSON: {"category":"food|transport|materials|utilities|health|education|housing|loans|banking|taxes|personal|other","confidence":0-1}',
        user_content=f"Vendor: {vendor}\nLine: {description[:500]}",
        max_tokens=120,
    )
    if isinstance(parsed, dict) and parsed.get("category"):
        return str(parsed["category"])[:64], "llm"
    return "other", "default"


def gst_rate_from_hsn_sync(hsn: str | None, description: str = "") -> dict[str, Any]:
    """Suggest GST % (0/5/12/18/28) and intra-state CGST+SGST split metadata."""
    h = (hsn or "").strip()[:8]
    rate: Decimal | None = None
    for prefix, r in _HSN_PREFIX_RATE:
        if h.startswith(prefix):
            rate = r
            break
    if rate is None and h:
        try:
            chapter = int(h[:2])
            if chapter in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                rate = Decimal("5")
            elif chapter in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24):
                rate = Decimal("18")
        except ValueError:
            pass
    if rate is None:
        blob = (description or "").lower()
        if "milk" in blob or "bread" in blob:
            rate = Decimal("5")
        elif "gold" in blob or "jewellery" in blob or "car " in blob:
            rate = Decimal("28")
        else:
            rate = Decimal("18")
    rate = max(Decimal("0"), min(Decimal("28"), rate))
    half = (rate / Decimal("2")).quantize(Decimal("0.01")) if rate > 0 else Decimal("0")
    return {
        "gst_rate_percent": float(rate),
        "cgst_rate_percent": float(half),
        "sgst_rate_percent": float(half),
        "igst_rate_percent": float(rate),
        "supply_intra_state": True,
        "note": "CGST+SGST apply when intra-state; IGST when inter-state — verify place of supply.",
    }


def enrich_invoice_lines_with_gst_sync(
    lines: list[dict[str, Any]],
    *,
    supply_intra_state: bool = True,
) -> list[dict[str, Any]]:
    """Fill missing/zero ``gst_rate_percent`` using HSN + description heuristics."""
    out: list[dict[str, Any]] = []
    for ln in lines:
        row = dict(ln)
        try:
            gstp = Decimal(str(row.get("gst_rate_percent", 0) or 0))
        except Exception:
            gstp = Decimal("0")
        if gstp <= 0:
            sug = gst_rate_from_hsn_sync(row.get("hsn_code"), str(row.get("description") or ""))
            row["gst_rate_percent"] = float(sug["gst_rate_percent"])
            row["gst_intelligence"] = sug
        row["gst_supply_intra_state"] = supply_intra_state
        out.append(row)
    return out


def _groq_vision_receipt(image_bytes: bytes, mime: str) -> dict[str, Any] | None:
    import os

    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.getenv("GROQ_VISION_MODEL") or "meta-llama/llama-3.2-11b-vision-preview").strip()
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    try:
        from groq import Groq

        client = Groq(api_key=key)
        chat = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Read this receipt/bill image. Output STRICT JSON only:\n"
                                '{"vendor_name":"","amount":null,"date":"YYYY-MM-DD or empty",'
                                '"category":"food|transport|materials|utilities|health|education|housing|personal|other",'
                                '"confidence":0-1,"needs_review":true/false,"raw_summary":""}'
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=600,
        )
        text = (chat.choices[0].message.content or "").strip()
        j = parse_json_lenient(text)
        return j if isinstance(j, dict) else None
    except Exception as exc:
        _log.warning("groq vision receipt: %s", exc)
        return None


def _gemini_vision_receipt(image_bytes: bytes, mime: str) -> dict[str, Any] | None:
    import os

    key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        model_name = (os.getenv("GEMINI_VISION_MODEL") or "gemini-2.0-flash").strip()
        model = genai.GenerativeModel(model_name)
        prompt = (
            "Read this receipt. Output STRICT JSON only: "
            '{"vendor_name":"","amount":null,"date":"YYYY-MM-DD or empty",'
            '"category":"food|transport|materials|utilities|health|education|housing|personal|other",'
            '"confidence":0-1,"needs_review":true/false,"raw_summary":""}'
        )
        resp = model.generate_content(
            [
                prompt,
                {"mime_type": mime or "image/jpeg", "data": image_bytes},
            ],
            generation_config={"max_output_tokens": 512, "temperature": 0.1},
        )
        text = (resp.text or "").strip()
        j = parse_json_lenient(text)
        return j if isinstance(j, dict) else None
    except Exception as exc:
        _log.warning("gemini vision receipt: %s", exc)
        return None


def scan_receipt_sync(image_bytes: bytes, *, content_type: str = "image/jpeg") -> dict[str, Any]:
    """
    Extract vendor, amount, date, category from a receipt image (Groq vision preferred, Gemini fallback).
    """
    mime = (content_type or "image/jpeg").split(";")[0].strip().lower() or "image/jpeg"
    parsed = _groq_vision_receipt(image_bytes, mime) or _gemini_vision_receipt(image_bytes, mime)
    if not isinstance(parsed, dict):
        return {
            "ok": False,
            "error": "vision_unavailable",
            "needs_review": True,
            "vendor_name": "",
            "amount": None,
            "date": "",
            "category": "other",
        }
    try:
        amt = parsed.get("amount")
        if amt is not None:
            amt = float(amt)
    except (TypeError, ValueError):
        amt = None
    conf = float(parsed.get("confidence") or 0.4)
    needs = bool(parsed.get("needs_review")) or conf < 0.55 or amt is None
    vendor = str(parsed.get("vendor_name") or "").strip()[:500]
    cat_kw, _reason = categorize_vendor_sync(vendor, str(parsed.get("raw_summary") or ""))
    cat = str(parsed.get("category") or "").strip().lower() or cat_kw
    if cat not in (
        "food",
        "transport",
        "materials",
        "utilities",
        "health",
        "education",
        "housing",
        "personal",
        "other",
        "loans",
        "banking",
        "taxes",
    ):
        cat = cat_kw
    return {
        "ok": True,
        "vendor_name": vendor,
        "amount": amt,
        "date": str(parsed.get("date") or "").strip()[:32],
        "category": cat[:64],
        "confidence": conf,
        "needs_review": needs,
        "raw_summary": str(parsed.get("raw_summary") or "")[:2000],
    }


def create_receipt_preview_sync(image_bytes: bytes, *, content_type: str = "image/jpeg") -> dict[str, Any]:
    scan = scan_receipt_sync(image_bytes, content_type=content_type)
    if not scan.get("ok"):
        tok = _preview_put({"scan": scan, "failed": True})
        return {"ok": False, "preview_token": tok, "scan": scan}
    tok = _preview_put({"scan": scan})
    return {"ok": True, "preview_token": tok, "preview": scan}


def confirm_receipt_expense_sync(
    *,
    user_id: int,
    preview_token: str,
    amount: Decimal | float | str | None = None,
    category: str | None = None,
    title: str | None = None,
    vendor_name: str | None = None,
    spent_at: datetime | None = None,
    fernet: Any = None,
) -> tuple[bool, str, int | None]:
    from services.personal_command_center_service import create_expense_sync

    raw = _preview_pop(preview_token)
    if not raw or not isinstance(raw.get("scan"), dict):
        return False, "invalid or expired preview_token", None
    scan = raw["scan"]
    if not scan.get("ok"):
        return False, "preview was a failed scan", None
    try:
        amt_dec = Decimal(str(amount if amount is not None else scan.get("amount") or 0)).quantize(Decimal("0.01"))
    except Exception:
        return False, "invalid amount", None
    if amt_dec <= 0:
        return False, "amount must be positive", None
    cat = (category or scan.get("category") or "other")[:64]
    vend = (vendor_name or scan.get("vendor_name") or "Receipt")[:500]
    ttl = (title or f"[auto_scan] {vend}")[:2000]
    st = spent_at or datetime.now(timezone.utc)
    if st.tzinfo is None:
        st = st.replace(tzinfo=timezone.utc)
    notes_obj = {
        "source": "auto_scan",
        "needs_review": bool(scan.get("needs_review")),
        "vendor_name": vend,
        "confidence": scan.get("confidence"),
    }
    notes_plain = json.dumps(notes_obj, ensure_ascii=False)[:7999]
    return create_expense_sync(
        user_id=int(user_id),
        amount=amt_dec,
        currency="INR",
        category=cat,
        subcategory="auto_scan",
        spent_at=st,
        title=ttl,
        notes_plain=notes_plain,
        fernet=fernet,
    )


def _parse_date_loose(s: str) -> date | None:
    s = (s or "").strip()[:32]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_bank_statement_csv_sync(raw: bytes) -> dict[str, Any]:
    """Best-effort CSV → list of {date, description, debit, credit, balance}."""
    text = raw.decode("utf-8", errors="replace")
    buf = io.StringIO(text)
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(buf, dialect=dialect)
    rows_out: list[dict[str, Any]] = []
    if not reader.fieldnames:
        return {"ok": False, "error": "no header row", "transactions": []}
    fields = [f.strip().lower() for f in reader.fieldnames if f]
    def pick(*names: str) -> str | None:
        for n in names:
            for f in reader.fieldnames or []:
                if f and f.strip().lower() == n:
                    return f
        for f in reader.fieldnames or []:
            fl = f.strip().lower()
            for n in names:
                if n in fl:
                    return f
        return None

    c_date = pick("date", "txn date", "transaction date", "value date")
    c_desc = pick("description", "narration", "particulars", "remarks")
    c_debit = pick("debit", "withdrawal", "dr")
    c_credit = pick("credit", "deposit", "cr")
    c_bal = pick("balance", "closing balance")
    for row in reader:
        if not row:
            continue
        d_raw = (row.get(c_date) or "").strip() if c_date else ""
        desc = (row.get(c_desc) or "").strip() if c_desc else ""
        dr = (row.get(c_debit) or "").strip().replace(",", "") if c_debit else ""
        cr = (row.get(c_credit) or "").strip().replace(",", "") if c_credit else ""
        bal = (row.get(c_bal) or "").strip().replace(",", "") if c_bal else ""
        def _num(x: str) -> float | None:
            if not x:
                return None
            try:
                return float(x)
            except ValueError:
                return None

        rows_out.append(
            {
                "date": d_raw,
                "description": desc[:2000],
                "debit": _num(dr),
                "credit": _num(cr),
                "balance": _num(bal),
            }
        )
    return {"ok": True, "transactions": rows_out[:500]}


def extract_bank_transactions_from_text_sync(text: str) -> dict[str, Any]:
    """LLM fallback: structured rows from pasted or extracted statement text."""
    blob = (text or "")[:14_000]
    if len(blob.strip()) < 40:
        return {"ok": False, "error": "insufficient text", "transactions": []}
    parsed = groq_json_object_sync(
        system=(
            "From Indian bank statement text, output STRICT JSON: "
            '{"transactions":[{"date":"YYYY-MM-DD","description":"","debit":number|null,"credit":number|null}]} '
            "Use debit for outflows, credit for inflows. Max 120 rows."
        ),
        user_content=blob,
        max_tokens=4000,
    )
    if not isinstance(parsed, dict):
        return {"ok": False, "error": "llm_parse_failed", "transactions": []}
    txs = parsed.get("transactions")
    if not isinstance(txs, list):
        return {"ok": False, "error": "no transactions array", "transactions": []}
    norm: list[dict[str, Any]] = []
    for t in txs[:120]:
        if not isinstance(t, dict):
            continue
        norm.append(
            {
                "date": str(t.get("date") or "")[:32],
                "description": str(t.get("description") or "")[:2000],
                "debit": t.get("debit"),
                "credit": t.get("credit"),
                "balance": t.get("balance"),
            }
        )
    return {"ok": True, "transactions": norm}


def parse_bank_statement_pdf_sync(raw: bytes) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        return {"ok": False, "error": f"pypdf: {exc}", "text": ""}
    try:
        reader = PdfReader(io.BytesIO(raw))
        parts: list[str] = []
        for page in reader.pages[:15]:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t)
        text = "\n".join(parts)[:50_000]
        return {"ok": True, "text": text}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "text": ""}


def classify_bank_line_sync(description: str, debit: float | None, credit: float | None) -> dict[str, Any]:
    desc_l = (description or "").lower()
    kind = "unknown"
    if credit and (not debit or debit == 0):
        kind = "income"
    elif debit and (not credit or credit == 0):
        if "emi" in desc_l or "loan" in desc_l or "ach d" in desc_l:
            kind = "emi"
        elif "neft" in desc_l or "rtgs" in desc_l or "imps" in desc_l or "supplier" in desc_l:
            kind = "supplier_payment"
        else:
            kind = "expense"
    cat, _ = categorize_vendor_sync(description[:120], description)
    return {"kind": kind, "suggested_category": cat}


def import_bank_statement_sync(
    *,
    organization_id: int,
    transactions: list[dict[str, Any]],
    user_id: int | None = None,
) -> dict[str, Any]:
    """Create operational expenses for debit rows (expense / EMI / supplier heuristic)."""
    from services.business_depth_service import record_operational_expense

    oid = int(organization_id)
    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    review: list[dict[str, Any]] = []
    for tx in transactions[:300]:
        debit = tx.get("debit")
        credit = tx.get("credit")
        desc = str(tx.get("description") or "")
        d = _parse_date_loose(str(tx.get("date") or "")) or date.today()
        cl = classify_bank_line_sync(desc, debit if isinstance(debit, (int, float)) else None, credit if isinstance(credit, (int, float)) else None)
        if cl["kind"] not in ("expense", "emi", "supplier_payment"):
            skipped.append(desc[:80] or "(empty)")
            continue
        amt = debit if isinstance(debit, (int, float)) and debit and debit > 0 else None
        if amt is None:
            skipped.append(desc[:80] or "(empty)")
            continue
        try:
            amt_d = Decimal(str(amt)).quantize(Decimal("0.01"))
        except Exception:
            skipped.append(desc[:80])
            continue
        cat = str(cl.get("suggested_category") or "general")[:64]
        if cl["kind"] == "emi":
            cat = "loans"
        elif cl["kind"] == "supplier_payment":
            cat = "supplier"
        tag = "[bank_import]"
        ok, msg, eid = record_operational_expense(
            organization_id=oid,
            expense_date=d,
            category=cat,
            amount_inr=amt_d,
            description=f"{tag} {desc}"[:2000],
        )
        if ok and eid:
            created.append({"expense_id": int(eid), "description": desc[:200], "amount_inr": str(amt_d)})
        else:
            review.append({"description": desc[:200], "error": msg})
    return {"ok": True, "created": created, "skipped_count": len(skipped), "needs_review": review}


def match_unpaid_invoices_sync(
    *,
    organization_id: int,
    amount_inr: Decimal | float | str,
    tolerance_inr: Decimal | float | str = Decimal("1.00"),
) -> dict[str, Any]:
    from services.billing_phase2_service import list_invoices_sync

    oid = int(organization_id)
    try:
        target = Decimal(str(amount_inr)).quantize(Decimal("0.01"))
        tol = Decimal(str(tolerance_inr)).quantize(Decimal("0.01"))
    except Exception:
        return {"ok": False, "error": "invalid amount", "matches": []}
    invs = list_invoices_sync(organization_id=oid, limit=200)
    matches: list[dict[str, Any]] = []
    for inv in invs.get("invoices") or []:
        if str(inv.get("payment_status") or "") == "paid":
            continue
        gt = Decimal(str(inv.get("grand_total_inr") or 0))
        paid = sum(Decimal(str(p.get("amount_inr") or 0)) for p in (inv.get("payments") or []) if isinstance(p, dict))
        due = (gt - paid).quantize(Decimal("0.01"))
        if due <= 0:
            continue
        diff = abs(due - target)
        if diff <= tol:
            matches.append(
                {
                    "invoice_id": int(inv.get("id") or 0),
                    "invoice_no": inv.get("invoice_no"),
                    "amount_due_inr": float(due),
                    "confidence": float(max(Decimal("0"), (tol - diff) / tol)) if tol > 0 else 1.0,
                }
            )
    matches.sort(key=lambda x: -float(x.get("confidence") or 0))
    return {"ok": True, "matches": matches[:10]}


def apply_invoice_payment_match_sync(
    *,
    organization_id: int,
    invoice_id: int,
    amount_inr: Decimal | float | str,
    reference: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    from services.billing_phase2_service import record_payment_sync

    return record_payment_sync(
        organization_id=int(organization_id),
        invoice_id=int(invoice_id),
        amount_inr=amount_inr,
        method="bank",
        reference=reference,
        paid_at=datetime.now(timezone.utc),
        user_id=user_id,
    )


def jarvis_expense_detection_message(scan: dict[str, Any]) -> str:
    if not scan.get("ok"):
        return "I could not read that receipt clearly — try a sharper photo or enter details manually."
    amt = scan.get("amount")
    amt_s = f"₹{amt}" if amt is not None else "an"
    v = scan.get("vendor_name") or "this vendor"
    cat = scan.get("category") or "other"
    return f"I detected {amt_s} {v} expense. Add to {cat} category? Confirm in Personal Finance or use scan-confirm."
