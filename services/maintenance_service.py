"""
Predictive maintenance notifications + billing hold when equipment is **Down** (Phase 6).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import Equipment, Notification
from services import billing_guard


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def normalize_equipment_status(raw: str) -> str:
    t = (raw or "").strip().lower()
    if t == "down":
        return "Down"
    if t in ("maintenance", "maint", "under_maintenance"):
        return "Maintenance"
    return "Running"


def pause_billing_for_equipment_down(*, organization_id: int, equipment: Equipment) -> None:
    """Org-level billing pause (existing guard) with a reason naming the line / project stage."""
    parts = [
        f"Equipment **{equipment.name}** (id={equipment.id}) is **Down**.",
    ]
    if equipment.project_stage_id is not None:
        parts.append(f"Linked project stage id **{equipment.project_stage_id}**.")
    parts.append("Resolve equipment status or clear billing hold when safe.")
    billing_guard.set_factory_billing_paused(int(organization_id), True, reason=" ".join(parts))


def ensure_maintenance_warning_notifications(organization_id: int, *, today: date | None = None) -> dict[str, Any]:
    """
    If ``next_service_due`` is within **7 days** (inclusive), insert a deduped 🟡 **warning** notification.
    """
    oid = int(organization_id)
    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database_unavailable", "inserted": 0}

    d = today or datetime.now(timezone.utc).date()
    horizon = d + timedelta(days=7)
    inserted = 0

    with factory() as session:
        with session.begin():
            rows = session.execute(
                select(Equipment).where(
                    Equipment.organization_id == oid,
                    Equipment.next_service_due.is_not(None),
                    Equipment.next_service_due >= d,
                    Equipment.next_service_due <= horizon,
                    Equipment.status != "Down",
                )
            ).scalars().all()
            for eq in rows:
                due = eq.next_service_due
                if due is None:
                    continue
                dedupe = f"factory_maint_warn:{eq.id}:{due.isoformat()}"
                exists = session.execute(
                    select(Notification.id).where(
                        Notification.organization_id == oid,
                        Notification.dedupe_key == dedupe,
                    ).limit(1)
                ).scalar_one_or_none()
                if exists is not None:
                    continue
                session.add(
                    Notification(
                        organization_id=oid,
                        kind="factory_maintenance_warning",
                        severity="warning",
                        title=f"🟡 Maintenance due soon: {eq.name}",
                        body=(
                            f"**{eq.name}** next service due **{due.isoformat()}** "
                            f"(within 7 days). Schedule service to avoid unplanned downtime."
                        ),
                        reference_type="equipment",
                        reference_id=int(eq.id),
                        payload={
                            "equipment_id": int(eq.id),
                            "next_service_due": due.isoformat(),
                        },
                        dedupe_key=dedupe,
                    )
                )
                inserted += 1

    return {"ok": True, "organization_id": oid, "inserted": inserted}


def set_equipment_status(
    *,
    organization_id: int,
    equipment_id: int,
    new_status: str,
) -> tuple[bool, str]:
    """Update equipment status; **Down** triggers ``billing_guard`` pause for the org."""
    oid = int(organization_id)
    eid = int(equipment_id)
    status = normalize_equipment_status(new_status)
    factory = _factory()
    if factory is None:
        return False, "database_unavailable"

    with factory() as session:
        with session.begin():
            eq = session.get(Equipment, eid)
            if eq is None or int(eq.organization_id) != oid:
                return False, "equipment not found"
            eq.status = status
            if status == "Down":
                pause_billing_for_equipment_down(organization_id=oid, equipment=eq)

    return True, "ok"


def list_equipment_due_soon(
    organization_id: int,
    *,
    today: date | None = None,
    days: int = 7,
) -> list[dict[str, Any]]:
    d = today or datetime.now(timezone.utc).date()
    horizon = d + timedelta(days=max(1, min(days, 90)))
    factory = _factory()
    if factory is None:
        return []
    with factory() as session:
        rows = session.execute(
            select(Equipment).where(
                Equipment.organization_id == int(organization_id),
                Equipment.next_service_due.is_not(None),
                Equipment.next_service_due >= d,
                Equipment.next_service_due <= horizon,
            ).order_by(Equipment.next_service_due.asc())
        ).scalars().all()
        out = []
        for eq in rows:
            due = eq.next_service_due
            if due is None:
                continue
            out.append(
                {
                    "id": int(eq.id),
                    "name": eq.name,
                    "status": eq.status,
                    "next_service_due": due.isoformat(),
                    "days_remaining": (due - d).days,
                    "project_stage_id": int(eq.project_stage_id) if eq.project_stage_id else None,
                }
            )
        return out
