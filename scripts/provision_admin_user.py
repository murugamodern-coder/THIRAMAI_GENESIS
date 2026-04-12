#!/usr/bin/env python3
"""
Provision a production admin user (JWT / POST /auth/login — not Django).

Uses:
  - ``User`` / ``Role`` / ``UserOrganizationMembership`` in ``core/db/models.py``
  - Session factory: ``get_session_factory()`` in ``core/database.py`` (``DATABASE_URL``)
  - Tenant + RBAC seed: ``ensure_organization_id_one_exists``, ``ensure_tenant_defaults`` in
    ``core/db/provisioning.py`` (roles: ``owner``/``admin`` level 1, ``superadmin`` level 0 via extra seeds)
  - Related: ``create_organization_with_owner`` in ``services/org_service.py`` (full org signup)

Idempotent: if the username or derived email already exists, exits 0 without error.

Examples::

    docker compose -f docker-compose.production.yml --env-file .env.production exec -T web \\
      python scripts/provision_admin_user.py --username admin_now --password 'admin123'

    python scripts/provision_admin_user.py --username admin_now --password 'YourLongPass!' --role owner
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from core.auth import hash_password
from core.database import get_session_factory
from core.db.models import Organization, Role, User, UserOrganizationMembership
from core.db.provisioning import ensure_organization_id_one_exists, ensure_tenant_defaults
from services.org_service import get_owner_role

_VALID_ROLES = frozenset({"superadmin", "owner", "admin"})


def _resolve_target_role(session: Session, organization_id: int, role_name: str) -> Role:
    """Return Role row for org; ``owner`` uses org_service; others by name."""
    oid = int(organization_id)
    name = (role_name or "superadmin").strip().lower()
    if name not in _VALID_ROLES:
        raise ValueError(f"Invalid role {role_name!r}; choose from {sorted(_VALID_ROLES)}")

    # First seed pass may omit ``superadmin``; second ``ensure_tenant_defaults`` runs
    # ``_ensure_extra_roles`` (see core/db/provisioning.py).
    ensure_tenant_defaults(session, oid)
    ensure_tenant_defaults(session, oid)

    if name == "owner":
        return get_owner_role(session, oid)

    role = session.execute(
        select(Role).where(Role.organization_id == oid, func.lower(Role.name) == name)
    ).scalar_one_or_none()
    if role is None:
        raise RuntimeError(
            f"Role {name!r} missing for organization_id={oid} after provisioning; check migrations / seed."
        )
    return role


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create THIRAMAI user + org membership (superadmin / owner / admin)."
    )
    parser.add_argument("--username", required=True, help="OAuth2 login username when it has no @.")
    parser.add_argument("--password", required=True, help="Plain password (min 8 characters).")
    parser.add_argument(
        "--email",
        default="",
        help="Optional unique email (default: <username>@provisioned.thiramai.local).",
    )
    parser.add_argument(
        "--role",
        default="superadmin",
        choices=sorted(_VALID_ROLES),
        help="RBAC role for membership (default: superadmin, level 0 in api/dependencies).",
    )
    parser.add_argument("--org-id", type=int, default=1, dest="org_id")
    args = parser.parse_args()

    if len(args.password) < 8:
        print("FAIL: password must be at least 8 characters", file=sys.stderr)
        return 1

    email = (args.email or "").strip().lower() or f"{args.username.lower()}@provisioned.thiramai.local"
    uname = args.username.strip()
    if not uname:
        print("FAIL: username must be non-empty", file=sys.stderr)
        return 1

    factory = get_session_factory()
    if factory is None:
        print("FAIL: DATABASE_URL is not set or engine could not be created.", file=sys.stderr)
        return 1

    with factory() as session:
        bind = session.get_bind()
        insp = inspect(bind)
        if not insp.has_table("users"):
            print("FAIL: table `users` does not exist. Run: alembic upgrade head", file=sys.stderr)
            return 1
        cols = {c["name"] for c in insp.get_columns("users")}
        if "username" not in cols:
            print("FAIL: column `users.username` missing. Run: alembic upgrade head", file=sys.stderr)
            return 1

        existing = session.execute(
            select(User).where(func.lower(User.username) == uname.lower())
        ).scalar_one_or_none()
        if existing is None:
            existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing is not None:
            print(
                f"OK: user already exists (id={existing.id}, email={existing.email!r}, username={existing.username!r}) — skipped."
            )
            return 0

        org = session.get(Organization, args.org_id)
        if org is None:
            if args.org_id == 1:
                org = ensure_organization_id_one_exists(session)
                session.flush()
            else:
                print(f"FAIL: organization id={args.org_id} does not exist", file=sys.stderr)
                return 1

        try:
            target_role = _resolve_target_role(session, int(org.id), args.role)
        except (ValueError, RuntimeError) as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 1

        user = User(
            email=email,
            username=uname,
            password_hash=hash_password(args.password),
            is_active=True,
        )
        session.add(user)
        session.flush()
        session.add(
            UserOrganizationMembership(
                user_id=int(user.id),
                organization_id=int(org.id),
                role_id=int(target_role.id),
                is_active=True,
            )
        )
        session.commit()
        print(
            f"OK: created user id={user.id} username={uname!r} email={email!r} "
            f"org_id={org.id} role={target_role.name!r} (level={target_role.level})"
        )
        print("Login: POST /auth/login (form) username=<username or email> password=<password>")
    return 0


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.production", override=False)
    raise SystemExit(main())
