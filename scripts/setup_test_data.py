#!/usr/bin/env python3
"""
Set up test data for real flow validation (uses DATABASE_URL from env).

Creates or ensures:
- Test organization (by name)
- Test user (by email) with password hash
- Owner membership linking user ↔ org

Idempotent: safe to run multiple times. Uses ``get_session_factory()`` (not FastAPI ``get_db()``,
which requires an authenticated request).

Usage (from repo root):
    python scripts/setup_test_data.py

    python scripts/setup_test_data.py \\
        --email admin@company.com \\
        --password SecurePass123! \\
        --org-name "Production Company"
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv(ROOT / ".env", override=False)
load_dotenv(ROOT / ".env.production", override=False)

from core.auth import hash_password  # noqa: E402
from core.database import get_session_factory  # noqa: E402
from core.db.models import Organization, User, UserOrganizationMembership  # noqa: E402
from core.db.provisioning import ensure_tenant_defaults, provision_new_organization  # noqa: E402
from services.org_service import get_owner_role, seed_default_business_units  # noqa: E402


def _display_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    return local.replace(".", " ").replace("_", " ").strip().title() or "User"


def setup_test_data(
    *,
    email: str,
    password: str,
    org_name: str,
) -> bool:
    """Provision org + user + owner membership in a single transaction (no nested ``begin()``)."""
    factory = get_session_factory()
    if factory is None:
        print("ERROR: DATABASE_URL is not set (cannot connect).", file=sys.stderr)
        return False

    email_norm = email.strip().lower()
    org_name_stripped = org_name.strip()
    print(f"Setting up test data for {email_norm!r} / org {org_name_stripped!r}...")

    session = factory()
    try:
        org = session.execute(
            select(Organization).where(Organization.name == org_name_stripped)
        ).scalar_one_or_none()

        if org is None:
            org = provision_new_organization(session, name=org_name_stripped, plan="free")
            session.flush()
            seed_default_business_units(session, int(org.id))
            print(f"✅ Created organization: {org.name} (ID: {org.id})")
        else:
            ensure_tenant_defaults(session, int(org.id))
            seed_default_business_units(session, int(org.id))
            print(f"✅ Organization exists: {org.name} (ID: {org.id})")

        owner_role = get_owner_role(session, int(org.id))

        user = session.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
        if user is None:
            user = User(
                email=email_norm,
                password_hash=hash_password(password),
                name=_display_name_from_email(email_norm),
                is_active=True,
            )
            session.add(user)
            session.flush()
            print(f"✅ Created user: {user.email} (ID: {user.id})")
        else:
            print(f"✅ User exists: {user.email} (ID: {user.id})")

        membership = session.execute(
            select(UserOrganizationMembership).where(
                UserOrganizationMembership.user_id == int(user.id),
                UserOrganizationMembership.organization_id == int(org.id),
            )
        ).scalar_one_or_none()

        if membership is None:
            session.add(
                UserOrganizationMembership(
                    user_id=int(user.id),
                    organization_id=int(org.id),
                    role_id=int(owner_role.id),
                    is_active=True,
                )
            )
            print(
                f"✅ Created membership: User {user.id} → Org {org.id} (role: {owner_role.name})"
            )
        elif int(membership.role_id) != int(owner_role.id):
            membership.role_id = int(owner_role.id)
            membership.is_active = True
            print(
                f"✅ Updated membership to owner: User {user.id} → Org {org.id}"
            )
        else:
            if not membership.is_active:
                membership.is_active = True
                print(f"✅ Reactivated membership: User {user.id} → Org {org.id}")
            else:
                print(f"✅ Membership exists: User {user.id} → Org {org.id} (owner)")

        session.commit()

        print("\n" + "=" * 60)
        print("TEST DATA READY")
        print("=" * 60)
        print("\nLogin credentials:")
        print(f"  Email:    {email_norm}")
        print(f"  Password: {password}")
        print(f"  Org:      {org_name_stripped}")
        print("\nYou can now test the real user flow.")
        return True

    except Exception as exc:
        print(f"❌ Error setting up test data: {exc}", file=sys.stderr)
        traceback.print_exc()
        session.rollback()
        return False

    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo tenant + owner user for Thiramai Genesis")
    parser.add_argument("--email", default="trader@test.com", help="User email")
    parser.add_argument("--password", default="testpass123", help="Plain password (stored hashed)")
    parser.add_argument("--org-name", default="Test Trading Firm", help="Organization display name")
    args = parser.parse_args()

    ok = setup_test_data(
        email=args.email,
        password=args.password,
        org_name=args.org_name,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
