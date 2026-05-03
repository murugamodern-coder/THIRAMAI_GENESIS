#!/usr/bin/env python3
"""
Diagnose authentication / login failures (500, "internal error", etc.).

Loads repo-root .env then .env.production (same as seed_admin_king). If DATABASE_URL
uses the Docker hostname ``db``, run this inside the web container so the DB is reachable::

  docker compose -f docker-compose.production.yml --env-file .env.production exec -T web \\
    python scripts/diagnose_auth.py

Or from the host, set DATABASE_URL to a mapped URL (localhost:5432).
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=ROOT / ".env", override=True)
load_dotenv(dotenv_path=ROOT / ".env.production", override=False)

# Defaults match scripts/seed_admin_king.py and run_local_live_test.sh
DEFAULT_LOGIN_USER = os.getenv("THIRAMAI_DIAGNOSE_AUTH_USERNAME", "admin_king")
DEFAULT_LOGIN_PASSWORD = os.getenv("THIRAMAI_DIAGNOSE_AUTH_PASSWORD", "thiramai_2026")
ALT_EMAIL_LOGIN = os.getenv("THIRAMAI_DIAGNOSE_AUTH_EMAIL", "admin@thiramai.local")


def _compose_base_url() -> str:
    explicit = (os.getenv("THIRAMAI_DIAGNOSE_AUTH_URL") or os.getenv("THIRAMAI_GO_LIVE_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = (os.getenv("WEB_PORT") or "8000").strip()
    env_prod = ROOT / ".env.production"
    if env_prod.is_file():
        for line in env_prod.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("WEB_PORT=") and not s.startswith("#"):
                port = s.split("=", 1)[1].strip().strip('"').strip("'")
                break
    return f"http://127.0.0.1:{port}"


def _secret_key_ok() -> tuple[bool, str]:
    from core.auth import _secret_key  # type: ignore[attr-defined]

    sk = _secret_key()
    if not sk:
        return False, "SECRET_KEY / JWT_SECRET_KEY / JWT_SECRET all empty"
    if sk.startswith("CHANGE_ME") or sk.upper().startswith("CHANGE"):
        return False, "Signing secret still looks like a placeholder"
    return True, f"Signing secret present (length {len(sk)})"


def check_database_connection() -> bool:
    print("\n" + "=" * 70)
    print("DATABASE CONNECTION CHECK")
    print("=" * 70)
    try:
        from sqlalchemy import text

        from core.database import get_session_factory

        factory = get_session_factory()
        if factory is None:
            print("FAIL: get_session_factory() is None (DATABASE_URL unset or invalid)")
            return False
        with factory() as session:
            one = session.execute(text("SELECT 1")).scalar()
        if one == 1:
            print("OK: Database connection and SELECT 1")
            return True
        print("FAIL: Unexpected result from SELECT 1")
        return False
    except Exception as e:
        print(f"FAIL: {e}")
        if "db" in (os.getenv("DATABASE_URL") or "").lower() and "could not translate host name" in str(
            e
        ).lower():
            print(
                "Hint: DATABASE_URL uses hostname `db` (Docker network). "
                "Run this script inside the web container, or point DATABASE_URL at localhost:MAPPED_PORT."
            )
        traceback.print_exc()
        return False


def check_users_table() -> bool:
    print("\n" + "=" * 70)
    print("USERS TABLE CHECK")
    print("=" * 70)
    try:
        from sqlalchemy import func, inspect, select

        from core.database import get_session_factory
        from core.db.models import User

        factory = get_session_factory()
        if factory is None:
            print("FAIL: No session factory")
            return False
        with factory() as session:
            bind = session.get_bind()
            insp = inspect(bind)
            if not insp.has_table("users"):
                print("FAIL: Table `users` missing — run: alembic upgrade head")
                return False
            n = session.execute(select(func.count()).select_from(User)).scalar_one()
        print(f"OK: users table exists, row count = {n}")
        if n == 0:
            print("WARN: No users — run: python scripts/seed_admin_king.py (or inside web container)")
            return False

        with factory() as session:
            u_email = session.execute(
                select(User).where(User.email == ALT_EMAIL_LOGIN.lower())
            ).scalar_one_or_none()
            u_name = session.execute(
                select(User).where(func.lower(User.username) == DEFAULT_LOGIN_USER.lower())
            ).scalar_one_or_none()
        if u_email:
            print(f"OK: Seeded admin email present: {u_email.email!r}, active={u_email.is_active}")
        if u_name:
            print(f"OK: Seeded admin username present: {u_name.username!r}, active={u_name.is_active}")
        if not u_email and not u_name:
            print("WARN: Neither default admin email nor admin_king username found")
            with factory() as session:
                sample = session.execute(select(User.email, User.username).limit(5)).all()
            for row in sample:
                print(f"   sample user: email={row[0]!r} username={row[1]!r}")
            return False
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()
        return False


def check_membership_and_role() -> bool:
    """Catch login 403 / 500 paths: no membership, missing role, JWT RuntimeError."""
    print("\n" + "=" * 70)
    print("MEMBERSHIP / ROLE / JWT SANITY")
    print("=" * 70)
    try:
        from sqlalchemy import func, select

        from core.auth import create_access_token
        from core.database import get_session_factory
        from core.db.models import Role, User, UserOrganizationMembership
        from services.membership_service import first_active_membership

        factory = get_session_factory()
        if factory is None:
            return False
        with factory() as session:
            user = session.execute(
                select(User).where(func.lower(User.username) == DEFAULT_LOGIN_USER.lower())
            ).scalar_one_or_none()
            if user is None:
                user = session.execute(
                    select(User).where(User.email == ALT_EMAIL_LOGIN.lower())
                ).scalar_one_or_none()
            if user is None:
                print("SKIP: No default admin user to check")
                return False
            mem = first_active_membership(session, int(user.id))
            if mem is None:
                print(f"FAIL: User id={user.id} has no active organization membership (login -> 403)")
                return False
            role = session.get(Role, int(mem.role_id))
            if role is None:
                print(f"FAIL: role_id={mem.role_id} missing (login -> 500 Role missing)")
                return False
            print(f"OK: membership org_id={mem.organization_id}, role={role.name!r}")
        try:
            tok = create_access_token(
                sub_user_id=int(user.id),
                org_id=int(mem.organization_id),
                active_org_id=int(mem.organization_id),
                role_name=role.name,
            )
            if not tok:
                print("FAIL: create_access_token returned empty")
                return False
            print("OK: create_access_token produced a token")
            return True
        except RuntimeError as e:
            print(f"FAIL: JWT signing failed (login -> 503): {e}")
            return False
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()
        return False


def check_organizations_table() -> bool:
    print("\n" + "=" * 70)
    print("ORGANIZATIONS TABLE CHECK")
    print("=" * 70)
    try:
        from sqlalchemy import func, inspect, select

        from core.database import get_session_factory
        from core.db.models import Organization

        factory = get_session_factory()
        if factory is None:
            return False
        with factory() as session:
            bind = session.get_bind()
            if not inspect(bind).has_table("organizations"):
                print("FAIL: Table `organizations` missing — run migrations")
                return False
            n = session.execute(select(func.count()).select_from(Organization)).scalar_one()
        print(f"OK: organizations table, count = {n}")
        if n == 0:
            print("WARN: No organizations")
            return False
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()
        return False


def check_migrations() -> bool:
    print("\n" + "=" * 70)
    print("ALEMBIC VERSION CHECK")
    print("=" * 70)
    try:
        from sqlalchemy import text

        from core.database import get_session_factory

        factory = get_session_factory()
        if factory is None:
            return False
        with factory() as session:
            row = session.execute(text("SELECT version_num FROM alembic_version")).first()
        if row and row[0]:
            print(f"OK: alembic_version = {row[0]!r}")
            return True
        print("FAIL: alembic_version empty")
        return False
    except Exception as e:
        print(f"FAIL: {e} (migrations not applied or DB not ready)")
        return False


def check_auth_config() -> bool:
    print("\n" + "=" * 70)
    print("AUTH CONFIG (signing secret)")
    print("=" * 70)
    ok, msg = _secret_key_ok()
    print(("OK: " if ok else "FAIL: ") + msg)
    return ok


def test_password_hash() -> bool:
    print("\n" + "=" * 70)
    print("PASSWORD HASH TEST")
    print("=" * 70)
    try:
        from core.auth import hash_password, verify_password

        plain = "diagnose_auth_probe_9z"
        h = hash_password(plain)
        if verify_password(plain, h):
            print("OK: hash_password / verify_password")
            return True
        print("FAIL: verify_password returned False")
        return False
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()
        return False


def test_login_endpoint(base_url: str, skip_http: bool) -> bool:
    print("\n" + "=" * 70)
    print("LOGIN ENDPOINT HTTP TEST")
    print("=" * 70)
    if skip_http:
        print("SKIP: --skip-http")
        return True
    try:
        import httpx
    except ImportError:
        print("SKIP: httpx not installed (pip install httpx)")
        return True

    url = f"{base_url}/auth/login"
    print(f"POST {url} (username={DEFAULT_LOGIN_USER!r})")
    try:
        r = httpx.post(
            url,
            data={"username": DEFAULT_LOGIN_USER, "password": DEFAULT_LOGIN_PASSWORD},
            timeout=15.0,
        )
        print(f"   HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            if data.get("access_token"):
                print("OK: access_token in JSON")
                return True
            body = repr(data)
            print(f"FAIL: 200 but no access_token: {body[:500]}")
            return False
        try:
            print(f"   body: {r.json()}")
        except Exception:
            print(f"   body: {r.text[:500]}")
        return False
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose auth/login failures")
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="Do not call POST /auth/login (DB-only checks)",
    )
    args = parser.parse_args()

    base_url = _compose_base_url()
    print("=" * 70)
    print("AUTHENTICATION DIAGNOSTICS")
    print("=" * 70)
    print(f"Base URL for HTTP tests: {base_url}")

    checks: dict[str, bool] = {}
    for name, fn in [
        ("Database connection", check_database_connection),
        ("Alembic revision", check_migrations),
        ("Organizations table", check_organizations_table),
        ("Users table", check_users_table),
        ("Membership / JWT", check_membership_and_role),
        ("Auth config (secret)", check_auth_config),
        ("Password hashing", test_password_hash),
    ]:
        try:
            checks[name] = fn()
        except Exception as e:
            print(f"\nCRASH: {name}: {e}")
            traceback.print_exc()
            checks[name] = False

    try:
        checks["Login HTTP"] = test_login_endpoint(base_url, args.skip_http)
    except Exception as e:
        print(f"\nCRASH: Login HTTP: {e}")
        checks["Login HTTP"] = False

    n_ok = sum(1 for v in checks.values() if v)
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for name, ok in checks.items():
        print(f"{'OK ' if ok else 'FAIL'} {name}")
    print("=" * 70)
    print(f"Passed: {n_ok}/{len(checks)}")

    if n_ok < len(checks):
        print("\nFix hints:")
        print("  Migrations: docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic upgrade head")
        print("  Seed admin: docker compose -f docker-compose.production.yml --env-file .env.production exec -T web python scripts/seed_admin_king.py")
        print("  Or run ./scripts/fix_auth.sh")
        print("  JWT secret: set SECRET_KEY and JWT_SECRET_KEY in .env.production")
        if not checks.get("Login HTTP", True) and checks.get("Database connection"):
            print(f"  If API is on another port, set THIRAMAI_DIAGNOSE_AUTH_URL (currently {base_url})")

    return 0 if n_ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
