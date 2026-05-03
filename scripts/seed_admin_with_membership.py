#!/usr/bin/env python3
"""
Seed the admin user and verify the user_organization_memberships row.

This is a thin wrapper around ``scripts/seed_admin_king.py`` that:

1. Re-runs the canonical seeding (idempotent) — creates the organization,
   the ``superadmin`` role, the user, and the **user_organization_memberships**
   row that the auth flow requires.
2. Reads the result back and prints a side-by-side verification block in the
   format requested by the deployment guide.

The actual schema does NOT have a ``users.organization_id`` column or a
``user_organization_memberships.role`` (string) column — membership is the
join row ``(user_id, organization_id, role_id)``. See ``core/db/models.py``::

    class UserOrganizationMembership(Base):
        __tablename__ = "user_organization_memberships"
        __table_args__ = (UniqueConstraint("user_id", "organization_id", ...),)
        ...
        role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ...))

Usage (from inside the web container):

    docker compose -f docker-compose.production.yml --env-file .env.production \\
        exec web python scripts/seed_admin_with_membership.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from core.database import get_session_factory  # noqa: E402
from core.db.models import (  # noqa: E402
    Organization,
    Role,
    User,
    UserOrganizationMembership,
)

# Reuse the canonical, schema-correct seeder so we never drift from it.
from scripts.seed_admin_king import (  # noqa: E402
    ADMIN_EMAIL,
    ADMIN_PASSWORD_PLAIN,
    ADMIN_USERNAME,
    TARGET_ORG_ID,
    main as seed_main,
)


def _verify() -> int:
    """Read back the seeded rows and print a verification block.

    Returns 0 if everything is wired up correctly, 1 otherwise.
    """
    factory = get_session_factory()
    if factory is None:
        print("ERROR: DATABASE_URL is not set; cannot verify seed.", file=sys.stderr)
        return 1

    with factory() as session:
        org = session.get(Organization, TARGET_ORG_ID)
        user = session.execute(
            select(User).where(User.email == ADMIN_EMAIL)
        ).scalar_one_or_none()
        membership = None
        role_name = None
        if user is not None:
            membership = session.execute(
                select(UserOrganizationMembership).where(
                    UserOrganizationMembership.user_id == int(user.id),
                    UserOrganizationMembership.organization_id == TARGET_ORG_ID,
                )
            ).scalar_one_or_none()
            if membership is not None:
                role = session.get(Role, int(membership.role_id))
                role_name = role.name if role is not None else None

    problems: list[str] = []
    if org is None:
        problems.append(f"organizations.id={TARGET_ORG_ID} missing")
    if user is None:
        problems.append(f"users WHERE email={ADMIN_EMAIL!r} missing")
    if membership is None:
        problems.append(
            "user_organization_memberships row missing for "
            f"(user_id, organization_id={TARGET_ORG_ID})"
        )

    print()
    print("=== Verification ===")
    if problems:
        print("FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("ADMIN USER READY:")
    print(f"   User id:           {int(user.id)}")
    print(f"   Email:             {user.email}")
    print(f"   Username:          {user.username}")
    print(f"   Organization id:   {TARGET_ORG_ID}")
    print(f"   Membership row id: {int(membership.id)}")
    print(f"   Membership active: {bool(membership.is_active)}")
    print(f"   Membership role:   {role_name} (role_id={int(membership.role_id)})")
    print()
    print("LOGIN CREDENTIALS:")
    print(f"   Username: {ADMIN_USERNAME}")
    print(f"   Password: {ADMIN_PASSWORD_PLAIN}")
    print("   URL:      http://localhost:8000/static/command_center/index.html#/login")
    return 0


def main() -> int:
    seed_rc = seed_main()
    if seed_rc != 0:
        return seed_rc
    return _verify()


if __name__ == "__main__":
    raise SystemExit(main())
