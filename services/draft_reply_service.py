"""
Template **draft replies** for routine business inquiries, grounded in Phase 4 Business Snapshot JSON.

Human must review before send — not auto-sent.
"""

from __future__ import annotations

from typing import Any


def draft_reply_for_business_inquiry(
    *,
    business_snapshot: dict[str, Any],
    sender_hint: str = "",
    subject_hint: str = "",
    thread_summary: str = "",
) -> str:
    """
    Produce a professional draft email body (plain text) using snapshot fields when present.

    ``business_snapshot`` should be the object from ``build_business_snapshot`` (``ok`` may be False).
    """
    sender = (sender_hint or "there").strip() or "there"
    subj = (subject_hint or "your message").strip() or "your message"
    extra = (thread_summary or "").strip()[:800]

    lines: list[str] = [
        f"Dear {sender},",
        "",
        f"Thank you for **{subj}**.",
    ]
    if extra:
        lines.extend(["", "We noted the following from your note:", extra, ""])

    lines.append("A quick operational snapshot from our side (for internal alignment — please verify before sending):")

    if business_snapshot.get("ok"):
        st = business_snapshot.get("sales_today") or {}
        pm = business_snapshot.get("profit_month") or {}
        low = business_snapshot.get("low_stock_alerts") or {}
        att = business_snapshot.get("attendance_today") or {}
        lines.append(
            f"- Today’s billed sales (approx.): ₹{st.get('actual_inr', 'n/a')} vs target ₹{st.get('target_inr', 'n/a')}."
        )
        lines.append(f"- Month-to-date net profit (management KPI): ₹{pm.get('net_profit_inr', 'n/a')}.")
        lines.append(f"- Low-stock SKUs flagged: {low.get('count', 'n/a')}.")
        lines.append(
            f"- Staff checked in today: {att.get('checked_in_today', 'n/a')} / {att.get('active_staff', 'n/a')} active."
        )
    else:
        lines.append("- (Business snapshot unavailable — fill in specifics manually.)")

    lines.extend(
        [
            "",
            "We will follow up with any clarifications or a formal quotation as applicable.",
            "",
            "Kind regards,",
            "[Your name]",
            "[Organization]",
        ]
    )
    return "\n".join(lines)


def draft_reply_for_auditor_compliance(
    *,
    subject_hint: str,
    compliance_lines: list[str],
    business_snapshot: dict[str, Any],
) -> str:
    """Shorter draft when the thread is tax/audit oriented (still human-approved)."""
    subj = (subject_hint or "your compliance communication").strip()
    snap_ok = bool(business_snapshot.get("ok"))
    pm = (business_snapshot.get("profit_month") or {}) if snap_ok else {}
    lines = [
        "Dear Sir/Madam,",
        "",
        f"Re: **{subj}**",
        "",
        "We acknowledge receipt and are aligning our records.",
    ]
    if compliance_lines:
        lines.append("Current statutory context on our side:")
        for c in compliance_lines[:6]:
            lines.append(f"- {c}")
        lines.append("")
    if snap_ok:
        lines.append(
            f"High-level operations: month-to-date net (management KPI) ₹{pm.get('net_profit_inr', 'n/a')}. "
            "We can provide supporting schedules on request."
        )
    lines.extend(["", "Please confirm any specific documents you require beyond the standard filings.", "", "Regards,", "[Authorized signatory]"])
    return "\n".join(lines)
