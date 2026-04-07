"""
Smart manpower suggestions: staff_profiles ↔ work_orders (Phase 6).

Uses department hints, open work-order load, and **maintenance_logs** history (technician_staff_profile_id / name).
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import Department, Equipment, MaintenanceLog, ProjectStage, StaffProfile, User, WorkOrder


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


OPEN_WORK_ORDER_STATUSES = frozenset({"open", "in_progress", "assigned", "scheduled"})


def count_open_work_orders_for_staff(session: Session, *, staff_profile_id: int) -> int:
    q = select(func.count()).select_from(WorkOrder).where(
        WorkOrder.assigned_staff_id == int(staff_profile_id),
        WorkOrder.status.in_(OPEN_WORK_ORDER_STATUSES),
    )
    return int(session.execute(q).scalar_one() or 0)


def count_completed_repairs_for_staff(session: Session, *, organization_id: int, staff_profile_id: int) -> int:
    """Maintenance logs tied to this staff profile (any equipment in org)."""
    oid = int(organization_id)
    spid = int(staff_profile_id)
    q = (
        select(func.count())
        .select_from(MaintenanceLog)
        .join(Equipment, Equipment.id == MaintenanceLog.equipment_id)
        .where(
            Equipment.organization_id == oid,
            MaintenanceLog.technician_staff_profile_id == spid,
            MaintenanceLog.fixed_at.is_not(None),
        )
    )
    return int(session.execute(q).scalar_one() or 0)


def _staff_email_local(session: Session, staff_profile_id: int) -> str:
    sp = session.get(StaffProfile, int(staff_profile_id))
    if sp is None:
        return ""
    u = session.get(User, int(sp.user_id))
    if u is None or not u.email:
        return ""
    return (u.email.split("@")[0] or "").lower()


def count_name_matched_repairs(
    session: Session,
    *,
    organization_id: int,
    staff_profile_id: int,
) -> int:
    """Heuristic: ``technician_name`` contains email local-part (when FK not set on legacy rows)."""
    oid = int(organization_id)
    local = _staff_email_local(session, staff_profile_id)
    if len(local) < 2:
        return 0
    q = (
        select(func.count())
        .select_from(MaintenanceLog)
        .join(Equipment, Equipment.id == MaintenanceLog.equipment_id)
        .where(
            Equipment.organization_id == oid,
            MaintenanceLog.technician_name.is_not(None),
            func.lower(MaintenanceLog.technician_name).contains(local),
            MaintenanceLog.fixed_at.is_not(None),
        )
    )
    return int(session.execute(q).scalar_one() or 0)


def _is_maintenance_adjacent_department(session: Session, department_id: int | None) -> bool:
    if department_id is None:
        return False
    d = session.get(Department, int(department_id))
    if d is None:
        return False
    name = (d.name or "").lower()
    return any(k in name for k in ("maint", "repair", "factory", "production", "plant", "technical"))


def suggest_assignee_for_work_order(
    organization_id: int,
    work_order_id: int,
) -> dict[str, Any]:
    """
    Rank active **staff_profiles** in-org: prefer maintenance-adjacent departments, low open WOs, high repair history.

    Returns best candidate + ranked list (for JARVIS narrative).
    """
    oid = int(organization_id)
    wid = int(work_order_id)
    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database_unavailable"}

    with factory() as session:
        wo = session.get(WorkOrder, wid)
        if wo is None:
            return {"ok": False, "error": "work_order not found"}
        ps = wo.project_stage
        if ps is None or int(ps.organization_id) != oid:
            return {"ok": False, "error": "work_order not found"}

        staff_rows = session.execute(
            select(StaffProfile).where(
                StaffProfile.organization_id == oid,
                StaffProfile.status == "active",
            )
        ).scalars().all()

        scored: list[dict[str, Any]] = []
        for sp in staff_rows:
            sid = int(sp.id)
            open_n = count_open_work_orders_for_staff(session, organization_id=oid, staff_profile_id=sid)
            rep_direct = count_completed_repairs_for_staff(session, organization_id=oid, staff_profile_id=sid)
            rep_name = count_name_matched_repairs(session, organization_id=oid, staff_profile_id=sid)
            dept_bonus = 15 if _is_maintenance_adjacent_department(session, sp.department_id) else 0
            load_penalty = min(30, open_n * 8)
            score = dept_bonus + rep_direct * 12 + rep_name * 6 - load_penalty
            u = session.get(User, int(sp.user_id))
            email = (u.email if u else "") or ""
            scored.append(
                {
                    "staff_profile_id": sid,
                    "user_id": int(sp.user_id),
                    "email": email,
                    "score": float(score),
                    "open_work_orders": open_n,
                    "completed_repairs_profile": rep_direct,
                    "completed_repairs_name_match": rep_name,
                    "maintenance_adjacent_dept": bool(dept_bonus),
                }
            )

        scored.sort(key=lambda x: (-x["score"], x["open_work_orders"], x["staff_profile_id"]))
        best = scored[0] if scored else None

        ai_line = None
        key = (os.getenv("GROQ_API_KEY") or "").strip()
        if key and best:
            try:
                from groq import Groq

                from core.policies.loader import GROQ_MODEL

                eq = session.get(Equipment, int(wo.equipment_id)) if wo.equipment_id else None
                eq_name = eq.name if eq else "equipment"
                sys = (
                    "You are JARVIS. One sentence (max 220 chars): recommend assigning the suggested technician "
                    "for tomorrow's checkup/repair and mention light production load if open_work_orders is 0. "
                    "No markdown. Use the provided name hint from email local-part only if no real name."
                )
                user = (
                    f"Equipment: {eq_name}. Suggested staff_profile_id={best['staff_profile_id']}, "
                    f"email={best['email']}, score={best['score']}, open_WOs={best['open_work_orders']}, "
                    f"past_repairs={best['completed_repairs_profile'] + best['completed_repairs_name_match']}."
                )
                client = Groq(api_key=key)
                comp = client.chat.completions.create(
                    model=(os.getenv("GROQ_MODEL") or GROQ_MODEL),
                    messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
                    temperature=0.25,
                    max_tokens=100,
                )
                ai_line = (comp.choices[0].message.content or "").strip()[:500] or None
            except Exception:
                ai_line = None

        return {
            "ok": True,
            "organization_id": oid,
            "work_order_id": wid,
            "recommended": best,
            "candidates": scored[:12],
            "ai_suggestion_line": ai_line,
        }
