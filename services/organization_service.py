"""
Tenant provisioning helpers (scripts + ops). Keeps **Modern Corporation** flows unchanged.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Role, User, UserOrganizationMembership
from core.db.provisioning import (
    MASS_SUCCESS_AGRO_AGENCY_ID,
    ensure_mass_success_agro_agency_org,
    seed_inventory_skus_if_missing,
)
from services.membership_service import membership_for_organization


MASS_SUCCESS_INITIAL_SKUS: tuple[tuple[str, str], ...] = (
    ("90mm PVC Pipe", "Main"),
    ("Solar Cells", "Main"),
)


def provision_mass_success_agro_agency(
    session: Session,
    *,
    link_user_ids: list[int] | None = None,
) -> dict[str, Any]:
    """
    Ensure org **Mass Success Agro Agency** (id=2), seed default SKUs, optionally link users as owner.
    Caller must ``commit`` the transaction.
    """
    org = ensure_mass_success_agro_agency_org(session)
    oid = int(org.id)
    n_skus = seed_inventory_skus_if_missing(
        session,
        organization_id=oid,
        sku_specs=list(MASS_SUCCESS_INITIAL_SKUS),
    )
    linked: list[int] = []
    if link_user_ids:
        owner_role = session.execute(
            select(Role).where(Role.organization_id == oid, Role.name == "owner").limit(1)
        ).scalar_one_or_none()
        if owner_role is not None:
            for uid in link_user_ids:
                u = session.get(User, int(uid))
                if u is None:
                    continue
                if membership_for_organization(session, int(u.id), oid) is not None:
                    linked.append(int(u.id))
                    continue
                session.add(
                    UserOrganizationMembership(
                        user_id=int(u.id),
                        organization_id=oid,
                        role_id=int(owner_role.id),
                        is_active=True,
                    )
                )
                linked.append(int(u.id))
            session.flush()
    return {
        "ok": True,
        "organization_id": oid,
        "organization_name": org.name,
        "inventory_skus_inserted": n_skus,
        "memberships_linked_user_ids": linked,
    }


def default_saas_modules_for_organization(organization_id: int) -> list[str]:
    """Enabled product modules for dashboard / AI context (in-memory convention; no extra DB column)."""
    oid = int(organization_id)
    if oid == int(MASS_SUCCESS_AGRO_AGENCY_ID):
        return ["Accounting", "Inventory", "Billing", "Solar Division"]
    return ["Accounting", "Inventory", "Billing"]
