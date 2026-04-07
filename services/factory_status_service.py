"""
Factory Dashboard v2 payload: equipment, work orders, manpower efficiency (Phase 6).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import Equipment, ProjectStage, StaffProfile, WorkOrder
from services import billing_guard, project_engine
from services.maintenance_service import ensure_maintenance_warning_notifications


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


ACTIVE_WO = frozenset({"open", "in_progress", "assigned", "scheduled"})


def build_factory_status_v2(organization_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database_unavailable", "organization_id": oid}

    try:
        ensure_maintenance_warning_notifications(oid)
    except Exception:
        pass

    projects = project_engine.list_projects(oid)
    project_items = [
        {
            "id": int(p.id),
            "project_name": p.project_name,
            "current_stage": int(p.current_stage),
            "stage_label": project_engine.stage_label(int(p.current_stage)),
            "machine_failed": bool(p.machine_failed),
            "asset_id": int(p.asset_id) if p.asset_id else None,
        }
        for p in projects
    ]

    with factory() as session:
        equipment_rows = session.execute(
            select(Equipment).where(Equipment.organization_id == oid).order_by(Equipment.name.asc())
        ).scalars().all()
        equipment = [
            {
                "id": int(e.id),
                "name": e.name,
                "model": e.model,
                "status": e.status,
                "purchase_date": e.purchase_date.isoformat() if e.purchase_date else None,
                "last_service_date": e.last_service_date.isoformat() if e.last_service_date else None,
                "next_service_due": e.next_service_due.isoformat() if e.next_service_due else None,
                "project_stage_id": int(e.project_stage_id) if e.project_stage_id else None,
            }
            for e in equipment_rows
        ]

        wo_rows = session.execute(
            select(WorkOrder)
            .join(ProjectStage, ProjectStage.id == WorkOrder.project_stage_id)
            .where(
                ProjectStage.organization_id == oid,
                WorkOrder.status.in_(ACTIVE_WO),
            )
            .order_by(WorkOrder.created_at.desc())
        ).scalars().all()
        work_orders_active = [
            {
                "id": int(w.id),
                "title": w.title or "(work order)",
                "status": w.status,
                "priority": w.priority,
                "project_stage_id": int(w.project_stage_id),
                "equipment_id": int(w.equipment_id) if w.equipment_id else None,
                "assigned_staff_id": int(w.assigned_staff_id) if w.assigned_staff_id else None,
            }
            for w in wo_rows
        ]

        active_staff_n = session.execute(
            select(func.count())
            .select_from(StaffProfile)
            .where(StaffProfile.organization_id == oid, StaffProfile.status == "active")
        ).scalar_one()
        active_staff_n = int(active_staff_n or 0)

        assigned_n = session.execute(
            select(func.count(func.distinct(WorkOrder.assigned_staff_id)))
            .select_from(WorkOrder)
            .join(ProjectStage, ProjectStage.id == WorkOrder.project_stage_id)
            .where(
                ProjectStage.organization_id == oid,
                WorkOrder.status.in_(ACTIVE_WO),
                WorkOrder.assigned_staff_id.is_not(None),
            )
        ).scalar_one()
        assigned_n = int(assigned_n or 0)

    efficiency: float | None
    if active_staff_n > 0:
        efficiency = round(assigned_n / active_staff_n, 4)
    else:
        efficiency = None

    down_machines = [e for e in equipment if (e.get("status") or "").lower() == "down"]

    return {
        "ok": True,
        "organization_id": oid,
        "billing_paused": billing_guard.is_billing_paused(oid),
        "billing_pause_detail": billing_guard.billing_pause_message(oid) or None,
        "projects": project_items,
        "equipment": equipment,
        "equipment_down_count": len(down_machines),
        "work_orders_active": work_orders_active,
        "manpower": {
            "active_staff_profiles": active_staff_n,
            "distinct_staff_assigned_open_work_orders": assigned_n,
            "assignment_load_ratio": efficiency,
        },
    }
