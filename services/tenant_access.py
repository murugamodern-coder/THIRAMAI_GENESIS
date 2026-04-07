"""
Tenant-scoped resource lookups (IDOR protection).

Service code should use the ``get_*_for_organization`` helpers that return ``None`` when the row
is missing or belongs to another organization. HTTP handlers may map ``None`` to **404**.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Asset, Bill, ProductionLog


def get_bill_for_organization(session: Session, bill_id: int, organization_id: int) -> Bill | None:
    bill = session.get(Bill, int(bill_id))
    if bill is None or int(bill.organization_id) != int(organization_id):
        return None
    return bill


def get_production_log_for_organization(
    session: Session, production_log_id: int, organization_id: int
) -> ProductionLog | None:
    stmt = (
        select(ProductionLog)
        .join(ProductionLog.asset)
        .where(
            ProductionLog.id == int(production_log_id),
            Asset.organization_id == int(organization_id),
        )
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_asset_for_organization(session: Session, asset_id: int, organization_id: int) -> Asset | None:
    ast = session.get(Asset, int(asset_id))
    if ast is None or int(ast.organization_id) != int(organization_id):
        return None
    return ast


def bill_for_tenant_or_404(session: Session, bill_id: int, organization_id: int) -> Bill:
    row = get_bill_for_organization(session, bill_id, organization_id)
    if row is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return row
