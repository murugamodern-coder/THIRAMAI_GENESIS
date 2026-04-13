"""DPR-style business report: LLM (Gemini preferred) + structured JSON + HTML + PDF (fpdf2)."""

from __future__ import annotations

import base64
import logging
from typing import Any

from core.database import get_session_factory
from core.db.models import ResearchDocument
from services.research_common import groq_json_object_sync, long_llm_sync, parse_json_lenient

_log = logging.getLogger("thiramai.dpr_generator")

_DPR_SECTIONS = """Produce a detailed feasibility-style report as STRICT JSON with keys:
- executive_summary (string)
- market_analysis (string)
- technical_plan (string)
- cost_estimation (string)
- financial_projection (string)
- break_even (string)
- roi (string)
Use INR/lakhs/crores where appropriate for India. Be explicit that figures are indicative unless verified by a CA."""


def _html_report(structured: dict[str, Any], *, title: str) -> str:
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>DPR</title>",
        "<style>body{font-family:system-ui,max-width:880px;margin:24px auto;line-height:1.5;color:#111}",
        "h1{border-bottom:2px solid #2563eb;padding-bottom:8px}h2{color:#1e3a8a;margin-top:1.4em}</style></head><body>",
        f"<h1>{title}</h1>",
    ]
    for key, label in [
        ("executive_summary", "Executive summary"),
        ("market_analysis", "Market analysis"),
        ("technical_plan", "Technical plan"),
        ("cost_estimation", "Cost estimation"),
        ("financial_projection", "Financial projection"),
        ("break_even", "Break-even"),
        ("roi", "ROI"),
    ]:
        val = structured.get(key) or ""
        parts.append(f"<h2>{label}</h2><p>{str(val).replace(chr(10), '<br/>')}</p>")
    parts.append("</body></html>")
    return "".join(parts)


def _pdf_bytes(structured: dict[str, Any], *, title: str) -> bytes | None:
    try:
        from fpdf import FPDF

        class Doc(FPDF):
            def footer(self) -> None:
                self.set_y(-15)
                self.set_font("Helvetica", "I", 8)
                self.cell(0, 10, f"Page {self.page_no()}", align="C")

        pdf = Doc()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 10, title[:200])
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 11)
        for key, label in [
            ("executive_summary", "Executive summary"),
            ("market_analysis", "Market analysis"),
            ("technical_plan", "Technical plan"),
            ("cost_estimation", "Cost estimation"),
            ("financial_projection", "Financial projection"),
            ("break_even", "Break-even"),
            ("roi", "ROI"),
        ]:
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 8, label)
            pdf.set_font("Helvetica", "", 10)
            body = str(structured.get(key) or "")[:8000]
            pdf.multi_cell(0, 5, body)
            pdf.ln(2)
        out = pdf.output(dest="S")
        return out if isinstance(out, bytes) else out.encode("latin-1")
    except Exception as exc:
        _log.warning("pdf build failed: %s", exc)
        return None


def generate_dpr_sync(
    business_type: str,
    capacity: str,
    location: str,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    bt = (business_type or "").strip()
    cap = (capacity or "").strip()
    loc = (location or "").strip()
    if not bt:
        return {"ok": False, "error": "business_type required"}
    title = f"DPR — {bt} ({loc or 'India'})"
    prompt = f"""Business: {bt}
Capacity / scale: {cap or 'not specified'}
Location: {loc or 'India'}

{_DPR_SECTIONS}
Return JSON only."""

    long_text = long_llm_sync(
        "You are a senior investment analyst drafting an India-focused project report.",
        prompt,
        prefer_gemini=True,
    )
    structured = parse_json_lenient(long_text) or groq_json_object_sync(
        system="Convert the following report into the JSON shape requested. Fill all keys with strings.",
        user_content=long_text[:20000],
        max_tokens=4096,
    )
    if not structured or not isinstance(structured, dict):
        structured = {
            "executive_summary": long_text[:2000],
            "market_analysis": "",
            "technical_plan": "",
            "cost_estimation": "",
            "financial_projection": "",
            "break_even": "",
            "roi": "",
        }
    html = _html_report(structured, title=title)
    pdf_b = _pdf_bytes(structured, title=title)
    out: dict[str, Any] = {
        "ok": True,
        "title": title,
        "report": structured,
        "html": html,
    }
    if pdf_b:
        out["pdf_base64"] = base64.standard_b64encode(pdf_b).decode("ascii")
    uid = int(user_id) if user_id and int(user_id) > 0 else None
    oid = int(organization_id) if organization_id and int(organization_id) > 0 else None
    if persist and uid:
        fac = get_session_factory()
        if fac is not None:
            try:
                with fac() as session:
                    with session.begin():
                        row = ResearchDocument(
                            user_id=uid,
                            organization_id=oid,
                            type="dpr",
                            query=f"{bt}|{cap}|{loc}"[:2000],
                            content_json={
                                "title": title,
                                "report": structured,
                                "has_pdf": bool(pdf_b),
                            },
                        )
                        session.add(row)
                        session.flush()
                        out["document_id"] = int(row.id)
            except Exception as exc:
                _log.warning("persist dpr: %s", exc)
    return out
