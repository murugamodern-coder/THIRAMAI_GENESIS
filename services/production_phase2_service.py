"""
Phase 2 production operations: daily logs, equipment (machines), maintenance, raw materials.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from core.database import get_session_factory
from core.db.models import Asset, Equipment, MaintenanceLog, ProductionLog, RawMaterial
from services import audit_log as system_audit


def _dec(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def create_production_log_sync(
    *,
    organization_id: int,
    asset_id: int,
    production_unit: str = "general",
    cement_in: float | Decimal | None = None,
    sand_in: float | Decimal | None = None,
    blocks_out: float | Decimal | None = None,
    raw_material_in: float | Decimal | None = None,
    yield_out: float | Decimal | None = None,
    labor_cost: float | Decimal | None = None,
    external_ref: str | None = None,
    raw_consumptions: list[dict[str, Any]] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    aid = int(asset_id)
    if oid <= 0 or aid <= 0:
        return {"ok": False, "error": "organization_id and asset_id required"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    log_id = 0
    try:
        with factory() as session:
            with session.begin():
                ast = session.get(Asset, aid)
                if ast is None or int(ast.organization_id) != oid:
                    raise LookupError("asset not found")
                row = ProductionLog(
                    asset_id=aid,
                    production_unit=(production_unit or "general")[:64],
                    cement_in=_dec(cement_in) if cement_in is not None else None,
                    sand_in=_dec(sand_in) if sand_in is not None else None,
                    blocks_out=_dec(blocks_out) if blocks_out is not None else None,
                    raw_material_in=_dec(raw_material_in) if raw_material_in is not None else None,
                    yield_out=_dec(yield_out) if yield_out is not None else None,
                    labor_cost=_dec(labor_cost) if labor_cost is not None else None,
                    external_ref=(external_ref or "").strip() or None,
                )
                session.add(row)
                session.flush()
                log_id = int(row.id)

                if raw_consumptions:
                    for rc in raw_consumptions:
                        rm_id = int(rc.get("raw_material_id") or 0)
                        qty = _dec(rc.get("quantity", 0))
                        if rm_id <= 0 or qty <= 0:
                            raise ValueError("raw_consumptions need raw_material_id and positive quantity")
                        rm = session.get(RawMaterial, rm_id)
                        if rm is None or int(rm.organization_id) != oid:
                            raise LookupError(f"raw_material {rm_id} not found")
                        new_q = _dec(rm.quantity_on_hand) - qty
                        if new_q < 0:
                            raise ValueError(f"insufficient raw material on hand for id {rm_id}")
                        rm.quantity_on_hand = new_q
    except LookupError as exc:
        return {"ok": False, "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="production_log",
        metadata={"channel": "production_phase2.log", "production_log_id": log_id, "asset_id": aid},
    )
    return {"ok": True, "production_log_id": log_id}


def production_summary_sync(
    *,
    organization_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    with factory() as session:
        stmt = (
            select(
                func.count(ProductionLog.id),
                func.coalesce(func.sum(ProductionLog.yield_out), 0),
                func.coalesce(func.sum(ProductionLog.blocks_out), 0),
                func.coalesce(func.sum(ProductionLog.labor_cost), 0),
            )
            .join(Asset, Asset.id == ProductionLog.asset_id)
            .where(Asset.organization_id == oid)
        )
        if start_date is not None:
            stmt = stmt.where(func.date(ProductionLog.timestamp) >= start_date)
        if end_date is not None:
            stmt = stmt.where(func.date(ProductionLog.timestamp) <= end_date)
        cnt, yld, blk, lab = session.execute(stmt).one()
        return {
            "ok": True,
            "log_count": int(cnt or 0),
            "total_yield_out": float(_dec(yld)),
            "total_blocks_out": float(_dec(blk)),
            "total_labor_cost_inr": float(_dec(lab)),
        }


def list_machines_sync(*, organization_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        rows = list(
            session.scalars(
                select(Equipment)
                .where(Equipment.organization_id == oid)
                .order_by(Equipment.name)
            ).all()
        )
    items = [
        {
            "id": int(r.id),
            "name": r.name,
            "model": r.model,
            "status": r.status,
            "purchase_date": r.purchase_date.isoformat() if r.purchase_date else None,
            "last_service_date": r.last_service_date.isoformat() if r.last_service_date else None,
            "next_service_due": r.next_service_due.isoformat() if r.next_service_due else None,
        }
        for r in rows
    ]
    return {"ok": True, "machines": items}


def create_maintenance_log_sync(
    *,
    organization_id: int,
    equipment_id: int,
    issue_description: str,
    cost: float | Decimal = 0,
    technician_name: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    eid = int(equipment_id)
    if oid <= 0 or eid <= 0:
        return {"ok": False, "error": "organization_id and equipment_id required"}
    desc = (issue_description or "").strip()
    if not desc:
        return {"ok": False, "error": "issue_description required"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    mid = 0
    try:
        with factory() as session:
            with session.begin():
                eq = session.get(Equipment, eid)
                if eq is None or int(eq.organization_id) != oid:
                    raise LookupError("equipment not found")
                row = MaintenanceLog(
                    equipment_id=eid,
                    issue_description=desc[:4000],
                    cost=_dec(cost),
                    technician_name=(technician_name or "").strip() or None,
                    fixed_at=datetime.now(timezone.utc),
                )
                session.add(row)
                session.flush()
                mid = int(row.id)
    except LookupError as exc:
        return {"ok": False, "error": str(exc)}

    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="maintenance_log",
        metadata={"channel": "production_phase2.maintenance", "maintenance_log_id": mid},
    )
    return {"ok": True, "maintenance_log_id": mid}
