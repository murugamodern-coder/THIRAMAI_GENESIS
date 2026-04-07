"""
Shared inventory row mutations (used by execution_engine and sale_execution).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from core.db.models import Inventory

_log = logging.getLogger(__name__)


def apply_inventory_delta(
    session: Session,
    *,
    organization_id: int,
    sku_name: str,
    location: str,
    delta: Decimal,
) -> Inventory:
    """
    Apply a quantity delta to the best-matching inventory row (org-scoped + optional location).

    Raises:
        ValueError: SKU not found when delta < 0, or insufficient stock (negative result).
    """
    loc = (location or "").strip()
    oid = int(organization_id)
    stmt = select(Inventory).where(Inventory.sku_name == sku_name)
    if loc:
        stmt = stmt.where(Inventory.location == loc)
    stmt = stmt.where(or_(Inventory.organization_id == oid, Inventory.organization_id.is_(None)))
    # Prefer tenant-owned row over legacy NULL-org rows; stable tie-break on id.
    prefer_tenant = case((Inventory.organization_id == oid, 0), else_=1)
    stmt = stmt.order_by(prefer_tenant, Inventory.id)
    # Serialize concurrent sells; LIMIT 2 detects ambiguous SKU+org without location.
    stmt = stmt.limit(2).with_for_update()
    rows = list(session.scalars(stmt).all())
    if len(rows) > 1:
        _log.warning(
            "inventory.ambiguous_match sku=%r org_id=%s location=%r rows=%s",
            sku_name,
            oid,
            loc or "(any)",
            len(rows),
        )
        raise ValueError(
            "Ambiguous inventory: more than one row matches this SKU for your organization; "
            "specify location in the sell request."
        )
    row = rows[0] if rows else None
    if row is None:
        if delta < 0:
            raise ValueError(f"SKU not found: {sku_name!r} @ {loc or '(any)'}")
        row = Inventory(
            organization_id=oid,
            sku_name=sku_name,
            quantity=delta,
            location=loc,
        )
        session.add(row)
        session.flush()
        return row
    new_q = (row.quantity or Decimal("0")) + delta
    if new_q < 0:
        raise ValueError("Insufficient stock for deduction")
    row.quantity = new_q
    if row.unit_price is not None:
        row.total_value = (row.quantity * row.unit_price).quantize(Decimal("0.01"))
    elif row.total_value is not None and delta != 0:
        orig = row.quantity - delta
        if orig > 0:
            row.total_value = (row.total_value * (row.quantity / orig)).quantize(Decimal("0.01"))
    session.flush()
    return row
