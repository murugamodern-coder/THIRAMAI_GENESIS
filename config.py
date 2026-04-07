"""
Deployment configuration reference (no secrets in this file).

**PostgreSQL:** set ``DATABASE_URL`` in the repository-root ``.env`` file (or export it before
starting the process). The app and SRE probes read it via ``os.environ`` through ``core.database``.

**Examples** (see also ``.env.example``)::

    DATABASE_URL=postgresql://user:password@localhost:5432/thiramai_db
    # or explicit driver:
    DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/thiramai_db

**Engine:** ``core.database.get_engine()`` builds a pooled engine with ``pool_pre_ping=True``.

**Migrations:** from repo root, ``python -m alembic -c alembic.ini upgrade head`` (or
``python -m services.master_sync`` / ``python -m services.verify_keys --sync``).

**Postgres service:** ensure the server is listening on the host/port in ``DATABASE_URL``
(``pg_isready``, Docker healthcheck, or Windows service).
"""

from __future__ import annotations

DATABASE_URL_ENV = "DATABASE_URL"

__all__ = ["DATABASE_URL_ENV"]
