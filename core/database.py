"""
THIRAMAI V2.1 data plane: PostgreSQL engine, sessions, and vault readiness probes.

Set ``DATABASE_URL`` in the repository-root ``.env`` (see root ``config.py`` and ``.env.example``).
``get_engine()`` lazily builds one shared engine with ``pool_pre_ping=True`` so pooled
connections are validated before use (avoids "lost connection" / timeout errors after long
idle or laptop sleep). Call ``reset_engine_cache()`` after changing env vars in-process.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator, Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None


def get_database_url() -> Optional[str]:
    u = (os.getenv("DATABASE_URL") or "").strip()
    return u or None


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_engine() -> Optional[Engine]:
    global _engine
    if _engine is not None:
        return _engine
    url = get_database_url()
    if not url:
        return None
    normalized = normalize_database_url(url)
    kw: dict = {"pool_pre_ping": True}
    if normalized.split("://", 1)[0].startswith("sqlite"):
        # PEP 249 transaction semantics: legacy sqlite3 often skips BEGIN on SELECT, which
        # allows lost-update races under concurrent writers; autocommit=False fixes that.
        kw["connect_args"] = {"autocommit": False}
    _engine = create_engine(normalized, **kw)
    return _engine


def reset_engine_cache() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> Optional[sessionmaker[Session]]:
    global _session_factory
    engine = get_engine()
    if engine is None:
        return None
    if _session_factory is None:
        _session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return _session_factory


def session_scope() -> Generator[Session, None, None]:
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not set or engine could not be created.")
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def db_session() -> Iterator[Session]:
    """
    Keep a Session open for the whole ``with`` block (no implicit commit).

    Use ``with session.begin():`` inside for transactional work, then ``session.refresh(obj)``
    before reading attributes if the instance may expire after commit.
    """
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not set or engine could not be created.")
    session = factory()
    try:
        yield session
    finally:
        session.close()


def ping_database() -> tuple[bool, str]:
    engine = get_engine()
    if engine is None:
        return False, "DATABASE_URL not set"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _classify_postgresql_connect_error(exc: BaseException) -> tuple[str, str]:
    """
    Classify connection failures without echoing secrets.
    Returns (category, user_safe_message).
    """
    parts: list[str] = [str(exc).lower()]
    types: list[str] = [type(exc).__name__.lower()]
    o = getattr(exc, "orig", None)
    if o is not None:
        parts.append(str(o).lower())
        types.append(type(o).__name__.lower())
    blob = " ".join(parts)
    tblob = " ".join(types)

    if "password authentication failed" in blob or "invalidpassword" in tblob:
        return (
            "authentication_failed",
            "Likely wrong PostgreSQL password or role (password authentication failed).",
        )
    if (
        "connection refused" in blob
        or "actively refused" in blob
        or "could not connect to server" in blob
        or "10061" in blob
        or "111" in blob
    ):
        return (
            "server_unreachable",
            "PostgreSQL is not reachable (connection refused). The server may be down or not listening on host/port.",
        )
    if "could not translate host name" in blob or "name or service not known" in blob:
        return (
            "server_unreachable",
            "Cannot resolve the database host (DNS / network).",
        )
    if "timeout" in blob or "timed out" in blob:
        return (
            "server_unreachable",
            "Connection timed out (server down, firewall, or wrong host/port).",
        )
    return ("other", f"{type(exc).__name__}: {str(exc)[:400]}")


def diagnose_postgresql_url(url: str) -> dict[str, Any]:
    """
    Open a short-lived engine to ``url`` and run ``SELECT 1``.
    Never logs or returns passwords.
    """
    from urllib.parse import urlparse

    u = (url or "").strip()
    out: dict[str, Any] = {"ok": False, "category": None, "detail": "", "target": {}}
    if not u:
        out["detail"] = "empty database URL"
        return out
    try:
        parsed = urlparse(u.replace("postgresql+psycopg2://", "postgresql://", 1))
        out["target"] = {
            "scheme": (parsed.scheme or "").split("+")[0],
            "host": parsed.hostname or "",
            "port": parsed.port or 5432,
            "database": (parsed.path or "").lstrip("/") or "",
            "user": parsed.username or "",
        }
    except Exception:
        out["target"] = {"parse_error": True}

    normalized = normalize_database_url(u)
    engine = None
    try:
        engine = create_engine(normalized, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        out["ok"] = True
        out["category"] = "ok"
        out["detail"] = "SELECT 1 succeeded"
    except Exception as exc:
        cat, msg = _classify_postgresql_connect_error(exc)
        out["category"] = cat
        out["detail"] = msg
    finally:
        if engine is not None:
            engine.dispose()

    return out


def structured_vault_ready() -> bool:
    """
    True when the DB is reachable and has at least one migrated business row
    (organization + any of assets / inventory / debts). Used to skip redundant CSV vault index.
    """
    factory = get_session_factory()
    if factory is None:
        return False
    try:
        from sqlalchemy import func, select

        from core.db.models import Asset, Debt, Inventory, Organization

        with factory() as session:
            org_ct = session.execute(select(func.count()).select_from(Organization)).scalar_one()
            if int(org_ct or 0) < 1:
                return False
            a = session.execute(select(func.count()).select_from(Asset)).scalar_one()
            i = session.execute(select(func.count()).select_from(Inventory)).scalar_one()
            d = session.execute(select(func.count()).select_from(Debt)).scalar_one()
            return int(a or 0) + int(i or 0) + int(d or 0) > 0
    except Exception:
        return False
