#!/usr/bin/env python3
"""
Upsert the built-in admin account (org 1, superadmin).

  Username: admin_king  (OAuth login ``username`` field — no @)
  Email:    admin@thiramai.local
  Password: thiramai_2026  (hashed with ``core.auth.hash_password`` / bcrypt)

Requires DATABASE_URL, migrations applied (``users`` table + optional ``username`` column).

Usage (from repo root):

  python scripts/seed_admin_king.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

load_dotenv(dotenv_path=ROOT / ".env", override=True)

from core.auth import hash_password
from core.database import get_session_factory
from core.db.models import Organization, Role, User, UserOrganizationMembership
from core.db.provisioning import ensure_organization_id_one_exists, ensure_tenant_defaults


ADMIN_EMAIL = "admin@thiramai.local"
ADMIN_USERNAME = "admin_king"
ADMIN_PASSWORD_PLAIN = "thiramai_2026"
TARGET_ORG_ID = 1


def _ensure_superadmin_role(session: Session, organization_id: int) -> Role:
    oid = int(organization_id)
    row = session.execute(
        select(Role).where(Role.organization_id == oid, Role.name == "superadmin")
    ).scalar_one_or_none()
    if row is not None:
        return row
    r = Role(organization_id=oid, name="superadmin", level=0)
    session.add(r)
    session.flush()
    return r


def main() -> int:
    factory = get_session_factory()
    if factory is None:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    with factory() as session:
        bind = session.get_bind()
        insp = inspect(bind)
        if not insp.has_table("users"):
            print(
                "ERROR: table `users` does not exist. Run: alembic upgrade head",
                file=sys.stderr,
            )
            return 1
        cols = {c["name"] for c in insp.get_columns("users")}
        if "username" not in cols:
            print(
                "ERROR: column `users.username` missing. Run: alembic upgrade head",
                file=sys.stderr,
            )
            return 1

        with session.begin():
            org = ensure_organization_id_one_exists(session)
            if org is None or int(org.id) != TARGET_ORG_ID:
                # org 1 might exist without ensure returning id 1 if get returned something else
                org = session.get(Organization, TARGET_ORG_ID)
                if org is None:
                    org = Organization(id=TARGET_ORG_ID, name="Modern Corporation", plan="free")
                    session.add(org)
                    session.flush()
            ensure_tenant_defaults(session, TARGET_ORG_ID)
            super_role = _ensure_superadmin_role(session, TARGET_ORG_ID)

            user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one_or_none()
            pw = hash_password(ADMIN_PASSWORD_PLAIN)
            if user is None:
                user = User(
                    email=ADMIN_EMAIL,
                    username=ADMIN_USERNAME,
                    password_hash=pw,
                    is_active=True,
                )
                session.add(user)
                session.flush()
            else:
                user.username = ADMIN_USERNAME
                user.password_hash = pw
                user.is_active = True
                session.flush()

            mem = session.execute(
                select(UserOrganizationMembership).where(
                    UserOrganizationMembership.user_id == int(user.id),
                    UserOrganizationMembership.organization_id == TARGET_ORG_ID,
                )
            ).scalar_one_or_none()
            if mem is None:
                session.add(
                    UserOrganizationMembership(
                        user_id=int(user.id),
                        organization_id=TARGET_ORG_ID,
                        role_id=int(super_role.id),
                        is_active=True,
                    )
                )
            else:
                mem.role_id = int(super_role.id)
                mem.is_active = True

    print("OK: admin user ready.")
    print(f"  Sign in with username: {ADMIN_USERNAME}  (or email: {ADMIN_EMAIL})")
    print(f"  Password: {ADMIN_PASSWORD_PLAIN}")
    print(f"  Organization id: {TARGET_ORG_ID}  Role: superadmin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
