"""
Multi-tenant provisioning: new organizations get RBAC roles + default department.

Use `provision_new_organization` when creating a tenant; use `ensure_tenant_defaults` on startup
to backfill orgs created before departments existed or with missing role rows.
"""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from core.db.models import Department, Inventory, Organization, Role


def sync_organizations_id_sequence(session: Session) -> None:
    """After inserting ``organizations`` with an explicit ``id``, realign PostgreSQL sequence."""
    try:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        seq: str | None = None
        for rel in ("public.organizations", "organizations"):
            row = session.execute(
                text("SELECT pg_get_serial_sequence(:rel, 'id')").bindparams(rel=rel)
            ).scalar_one_or_none()
            if row:
                seq = str(row)
                break
        if not seq:
            return
        # Sequence name comes from pg_catalog (not user input).
        _seq = seq.replace("'", "''")
        session.execute(
            text(f"SELECT setval('{_seq}', (SELECT COALESCE(MAX(id), 1) FROM organizations))")
        )
    except ProgrammingError:
        pass
    except Exception:
        pass


def ensure_organization_id_one_exists(session: Session) -> Organization | None:
    """
    Dashboard / dev default tenant: ensure ``organizations.id = 1`` exists (Modern Corporation).

    Idempotent; seeds roles + General department when creating the row.
    """
    existing = session.get(Organization, 1)
    if existing is not None:
        return existing
    org = Organization(id=1, name="Modern Corporation", plan="free")
    session.add(org)
    session.flush()
    ensure_tenant_defaults(session, 1)
    try:
        sync_organizations_id_sequence(session)
    except Exception:
        pass
    return org


_MODERN_CORPORATION_NAME = "Modern Corporation"


def ensure_modern_corporation_org(session: Session, organization_id: int = 3) -> Organization:
    """
    Ensure tenant ``organization_id`` (default **3**) exists with canonical name **Modern Corporation**.

    Creates the row + default roles / General department when missing; repairs empty/wrong name.
    Used after migrations / ``verify_keys --sync`` to fix ``organization_integrity``.
    """
    oid = int(organization_id)
    org = session.get(Organization, oid)
    if org is None:
        org = Organization(id=oid, name=_MODERN_CORPORATION_NAME, plan="free")
        session.add(org)
        session.flush()
        ensure_tenant_defaults(session, oid)
        try:
            sync_organizations_id_sequence(session)
        except Exception:
            pass
        return org
    name = (org.name or "").strip()
    if not name or name != _MODERN_CORPORATION_NAME:
        org.name = _MODERN_CORPORATION_NAME
        session.flush()
    ensure_tenant_defaults(session, oid)
    try:
        sync_organizations_id_sequence(session)
    except Exception:
        pass
    return org


def _existing_role_names(session: Session, organization_id: int) -> set[str]:
    oid = int(organization_id)
    rows = session.execute(select(Role.name).where(Role.organization_id == oid)).scalars().all()
    return {str(n).lower() for n in rows if n}


def _ensure_extra_roles(session: Session, organization_id: int) -> None:
    """Idempotent: add ``admin`` / ``staff`` / ``customer`` if missing."""
    oid = int(organization_id)
    have = _existing_role_names(session, oid)
    for name, level in _EXTRA_ROLE_SEEDS:
        if name.lower() in have:
            continue
        session.add(Role(organization_id=oid, name=name, level=level))
    session.flush()

# Owner / Manager / Worker per product spec; Supervisor kept so existing routes using
# require_roles(..., "supervisor") continue to work for newly provisioned tenants.
_DEFAULT_ROLE_SEEDS: tuple[tuple[str, int], ...] = (
    ("owner", 1),
    ("admin", 1),
    ("manager", 2),
    ("supervisor", 3),
    ("worker", 4),
    ("staff", 4),
    ("customer", 5),
)

# Backfill for orgs created before admin/staff existed (Phase 2 / POS).
_EXTRA_ROLE_SEEDS: tuple[tuple[str, int], ...] = (
    ("superadmin", 0),
    ("admin", 1),
    ("staff", 4),
    ("customer", 5),
)

DEFAULT_DEPARTMENT_NAME = "General"


def _seed_default_roles(session: Session, organization_id: int) -> None:
    oid = int(organization_id)
    for name, level in _DEFAULT_ROLE_SEEDS:
        session.add(Role(organization_id=oid, name=name, level=level))
    session.flush()


def _ensure_default_department(session: Session, organization_id: int, *, name: str = DEFAULT_DEPARTMENT_NAME) -> None:
    oid = int(organization_id)
    exists = session.execute(
        select(func.count()).select_from(Department).where(Department.organization_id == oid)
    ).scalar_one()
    if int(exists or 0) > 0:
        return
    session.add(Department(organization_id=oid, name=name.strip() or DEFAULT_DEPARTMENT_NAME))
    session.flush()


def provision_new_organization(
    session: Session,
    *,
    name: str,
    plan: str = "free",
    gst_number: str | None = None,
    industry: str | None = None,
) -> Organization:
    """
    Insert a new organization, seed default roles (Owner, Manager, Supervisor, Worker),
    and create the default **General** department. Caller must commit the transaction.
    """
    org = Organization(
        name=(name or "").strip(),
        plan=(plan or "free").strip() or "free",
        gst_number=(gst_number or "").strip() or None,
        industry=(industry or "").strip() or None,
    )
    session.add(org)
    session.flush()
    oid = int(org.id)
    _seed_default_roles(session, oid)
    _ensure_default_department(session, oid)
    return org


MASS_SUCCESS_AGRO_AGENCY_ID = 2
MASS_SUCCESS_AGRO_AGENCY_NAME = "Mass Success Agro Agency"


def ensure_mass_success_agro_agency_org(session: Session) -> Organization:
    """
    Ensure tenant ``organizations.id = 2`` exists for **Mass Success Agro Agency**.

    Does not modify **Modern Corporation** (typically ``id = 3`` via ``ensure_modern_corporation_org``).
    Idempotent: creates row + roles / General department, or repairs name / tenant defaults.
    """
    oid = int(MASS_SUCCESS_AGRO_AGENCY_ID)
    org = session.get(Organization, oid)
    if org is None:
        org = Organization(
            id=oid,
            name=MASS_SUCCESS_AGRO_AGENCY_NAME,
            plan="free",
            industry="Agro distribution · Solar manufacturing (DPR)",
        )
        session.add(org)
        session.flush()
        ensure_tenant_defaults(session, oid)
        try:
            sync_organizations_id_sequence(session)
        except Exception:
            pass
        return org
    name = (org.name or "").strip()
    if name != MASS_SUCCESS_AGRO_AGENCY_NAME:
        org.name = MASS_SUCCESS_AGRO_AGENCY_NAME
    if org.industry is None or not str(org.industry).strip():
        org.industry = "Agro distribution · Solar manufacturing (DPR)"
    session.flush()
    ensure_tenant_defaults(session, oid)
    try:
        sync_organizations_id_sequence(session)
    except Exception:
        pass
    return org


def seed_inventory_skus_if_missing(
    session: Session,
    *,
    organization_id: int,
    sku_specs: list[tuple[str, str]],
) -> int:
    """
    Insert inventory rows for ``(sku_name, location)`` when no row exists for that SKU in-org.

    Returns count of newly inserted rows.
    """
    from decimal import Decimal

    oid = int(organization_id)
    inserted = 0
    for sku_name, location in sku_specs:
        sn = (sku_name or "").strip()
        if not sn:
            continue
        loc = (location or "Main").strip() or "Main"
        exists = session.execute(
            select(Inventory.id)
            .where(Inventory.organization_id == oid, Inventory.sku_name == sn)
            .limit(1)
        ).scalar_one_or_none()
        if exists is not None:
            continue
        session.add(
            Inventory(
                organization_id=oid,
                sku_name=sn,
                quantity=Decimal("0"),
                location=loc,
                unit_cost_pre_tax=None,
                unit_price=None,
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


def ensure_tenant_defaults(session: Session, organization_id: int) -> None:
    """
    If an organization has no roles, seed defaults; if it has no departments, add **General**.
    Safe to call repeatedly (idempotent).
    """
    oid = int(organization_id)
    role_ct = session.execute(
        select(func.count()).select_from(Role).where(Role.organization_id == oid)
    ).scalar_one()
    if int(role_ct or 0) == 0:
        _seed_default_roles(session, oid)
    else:
        _ensure_extra_roles(session, oid)
    _ensure_default_department(session, oid)
