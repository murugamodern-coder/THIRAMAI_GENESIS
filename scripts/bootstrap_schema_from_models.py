#!/usr/bin/env python3
"""
Bootstrap an **empty or nearly empty** PostgreSQL schema without running the Alembic chain.

Use when the DB is inconsistent with migrations (e.g. ``users`` exists but ``organizations`` does not)
and you want a working schema **immediately**.

What it does (**default order** — safest for empty/partial DBs):
  1. ``Base.metadata.create_all()`` — create **missing** tables from ORM models (``core/db/models.py``).
  2. ``alembic stamp head`` — record current head revision (see ``core/migration_head.EXPECTED_ALEMBIC_REVISION``).

Use ``--stamp-first`` for the legacy order (stamp then create_all).

``create_all`` **does not** alter existing tables; if ``users`` already exists with fewer columns than
the model, SQLAlchemy skips that table and a **warning** is printed. Fix by migrating that table
or dropping it on a truly empty database.

**Not** a substitute for normal migrations on a long-lived DB — only for greenfield / broken dev DBs.

Examples::

    cd /var/www/thiramai
    docker compose -f docker-compose.production.yml --env-file .env.production exec -T web \\
      python scripts/bootstrap_schema_from_models.py

    # Legacy order (stamp before DDL):
    python scripts/bootstrap_schema_from_models.py --stamp-first
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stamp Alembic at head and create missing tables from SQLAlchemy models."
    )
    parser.add_argument(
        "--stamp-first",
        action="store_true",
        help="Run alembic stamp head before create_all (legacy). Default: create_all then stamp.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print steps only; do not stamp or create tables.",
    )
    args = parser.parse_args()
    create_first: bool = not bool(args.stamp_first)

    os.chdir(ROOT)

    from dotenv import load_dotenv

    from core.env_bootstrap import load_project_dotenv

    load_project_dotenv(root=ROOT, override=True)
    load_dotenv(ROOT / ".env.production", override=False)

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text as sa_text

    from core.database import get_engine
    from core.db.base import Base
    import core.db.models  # noqa: F401 — register all mapped classes on Base.metadata
    from core.db.models import User
    from core.migration_head import EXPECTED_ALEMBIC_REVISION

    engine = get_engine()
    if engine is None:
        print("FAIL: DATABASE_URL is not set or engine could not be created.", file=sys.stderr)
        return 1
    if engine.dialect.name != "postgresql":
        print(
            f"FAIL: this bootstrap targets PostgreSQL; got dialect {engine.dialect.name!r}.",
            file=sys.stderr,
        )
        return 1

    def stamp() -> None:
        if args.dry_run:
            print("[dry-run] alembic stamp head")
            return
        cfg = Config(str(ROOT / "alembic.ini"))
        command.stamp(cfg, "head")
        with engine.connect() as conn:
            row = conn.execute(sa_text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if row != EXPECTED_ALEMBIC_REVISION:
            print(
                f"WARN: alembic_version is {row!r}; expected {EXPECTED_ALEMBIC_REVISION!r} "
                "(check for multiple heads or outdated core/migration_head.py).",
                file=sys.stderr,
            )
        print(f"OK: alembic_version stamped at head (revision id: {EXPECTED_ALEMBIC_REVISION!r}).")

    def create_all() -> None:
        if args.dry_run:
            print("[dry-run] Base.metadata.create_all(bind=engine)")
            return
        insp = sa_inspect(engine)
        if insp.has_table("users"):
            actual = {c["name"] for c in insp.get_columns("users")}
            expected = {c.key for c in User.__table__.columns}
            missing = expected - actual
            if missing:
                print(
                    "WARN: table `users` exists but is missing model columns "
                    f"{sorted(missing)!s}. create_all will NOT alter `users`. "
                    "On an empty DB you may DROP TABLE users CASCADE; then re-run this script.",
                    file=sys.stderr,
                )
        Base.metadata.create_all(bind=engine)
        print("OK: Base.metadata.create_all() finished (missing tables created).")

    if args.dry_run:
        print(f"ROOT={ROOT}")
        print(f"Expected Alembic head revision: {EXPECTED_ALEMBIC_REVISION}")
        print(f"Order: {'create_all then stamp' if create_first else 'stamp then create_all'}")

    if create_first:
        create_all()
        stamp()
    else:
        stamp()
        create_all()

    if not args.dry_run:
        print(
            "Next: run tenant seed if needed, then "
            "`python scripts/provision_admin_user.py --username ... --password ...`"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
