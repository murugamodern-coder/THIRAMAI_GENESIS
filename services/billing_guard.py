"""
Factory OS billing hold: when Stage-2 (income) machine failure is flagged, pause invoice/production billing paths.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import FactoryBillingHold


def is_billing_paused(
    organization_id: int,
    *,
    _session_factory: Optional[sessionmaker[Session]] = None,
) -> bool:
    oid = int(organization_id)
    if oid <= 0:
        return False
    factory = _session_factory or get_session_factory()
    if factory is None:
        return False
    with factory() as session:
        row = session.get(FactoryBillingHold, oid)
        return bool(row and row.billing_paused)


def billing_pause_message(
    organization_id: int,
    *,
    _session_factory: Optional[sessionmaker[Session]] = None,
) -> str:
    oid = int(organization_id)
    factory = _session_factory or get_session_factory()
    if factory is None:
        return "Billing is paused (database unavailable)."
    with factory() as session:
        row = session.get(FactoryBillingHold, oid)
        if not row or not row.billing_paused:
            return ""
        r = (row.pause_reason or "").strip()
        return r or "Factory billing is paused due to an operational hold."


def set_factory_billing_paused(
    organization_id: int,
    paused: bool,
    *,
    reason: str = "",
) -> None:
    oid = int(organization_id)
    if oid <= 0:
        return
    factory = get_session_factory()
    if factory is None:
        return
    with factory() as session:
        with session.begin():
            row = session.get(FactoryBillingHold, oid)
            if row is None:
                session.add(
                    FactoryBillingHold(
                        organization_id=oid,
                        billing_paused=paused,
                        pause_reason=(reason or "")[:4000] if paused else None,
                    )
                )
            else:
                row.billing_paused = paused
                row.pause_reason = (reason or "")[:4000] if paused else None


def upsert_hold_in_session(
    session: Session,
    organization_id: int,
    paused: bool,
    reason: str = "",
) -> None:
    oid = int(organization_id)
    row = session.get(FactoryBillingHold, oid)
    if row is None:
        session.add(
            FactoryBillingHold(
                organization_id=oid,
                billing_paused=paused,
                pause_reason=(reason or "")[:4000] if paused else None,
            )
        )
    else:
        row.billing_paused = paused
        row.pause_reason = (reason or "")[:4000] if paused else None


def assert_billing_not_paused(organization_id: int) -> None:
    if is_billing_paused(organization_id):
        raise RuntimeError(billing_pause_message(organization_id) or "Factory billing is paused.")
