"""
JARVIS / council appendix: Factory OS v2 narrative from ``build_factory_status_v2`` + staffing hint.
"""

from __future__ import annotations

from typing import Any

from services.factory_status_service import build_factory_status_v2
from services.maintenance_service import list_equipment_due_soon
from services.resource_allocation_service import suggest_assignee_for_work_order


def format_factory_os_v2_markdown(
    *,
    organization_id: int,
    max_chars: int = 2800,
) -> str:
    oid = int(organization_id)
    if oid <= 0:
        return ""

    snap = build_factory_status_v2(oid)
    if not snap.get("ok"):
        return ""

    lines: list[str] = [
        "## Factory OS v2 (digital twin)",
        f"- **organization_id:** {oid}",
        f"- **Billing paused:** {snap.get('billing_paused')} — {snap.get('billing_pause_detail') or '—'}",
        f"- **Equipment down:** {snap.get('equipment_down_count', 0)}",
        "",
    ]

    mp = snap.get("manpower") or {}
    lines.append("### Manpower")
    lines.append(
        f"- Active staff profiles: **{mp.get('active_staff_profiles', 0)}**; "
        f"distinct assignees on open work orders: **{mp.get('distinct_staff_assigned_open_work_orders', 0)}** "
        f"(load ratio **{mp.get('assignment_load_ratio')}**)."
    )
    lines.append("")

    due = list_equipment_due_soon(oid, days=7)
    lines.append("### Service due (≤7 days)")
    if due:
        for row in due[:8]:
            lines.append(
                f"- **{row['name']}** — due in **{row['days_remaining']}** day(s) "
                f"({row['next_service_due']}), status **{row['status']}**"
            )
    else:
        lines.append("- _(No equipment in the 7-day service window.)_")
    lines.append("")

    wos = snap.get("work_orders_active") or []
    lines.append(f"### Open work orders (**{len(wos)}**)")
    for w in wos[:6]:
        lines.append(
            f"- WO **{w['id']}** [{w['status']}] {w['title'][:80]} — equipment_id={w.get('equipment_id')}, "
            f"assigned_staff_id={w.get('assigned_staff_id')}"
        )

    if wos:
        first_id = int(wos[0]["id"])
        sug = suggest_assignee_for_work_order(oid, first_id)
        if sug.get("ok") and sug.get("recommended"):
            rec = sug["recommended"]
            lines.append("")
            lines.append("### JARVIS staffing hint (first open WO)")
            lines.append(
                f"- Suggested **staff_profile_id {rec.get('staff_profile_id')}** "
                f"({rec.get('email', '')}) — score **{rec.get('score')}**, "
                f"open WOs **{rec.get('open_work_orders')}**, "
                f"past repairs **{rec.get('completed_repairs_profile', 0) + rec.get('completed_repairs_name_match', 0)}**."
            )
            if sug.get("ai_suggestion_line"):
                lines.append(f"- _{sug['ai_suggestion_line']}_")

    lines.append("")
    lines.append(
        "### Council directive\n"
        "Correlate **equipment service dates** with **Stage-2 production** and **staff load**: "
        "if a machine is due soon and a strong technician has **low open work orders**, prefer scheduling "
        "checkups when **billing is not paused** unless maintenance is already planned."
    )

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        return text[: max_chars - 40] + "\n\n_[… clipped …]_"
    return text
