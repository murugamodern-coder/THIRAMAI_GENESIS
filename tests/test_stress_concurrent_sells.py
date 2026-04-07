"""
Inventory / billing stress coverage.

- **Serial 100 sells (SQLite file):** proves GST + stock + bill rows stay consistent (CI-safe).
- **100 concurrent sells (PostgreSQL only):** ``SELECT FOR UPDATE`` serializes rows on Postgres;
  SQLite cannot guarantee the same under heavy parallel writers — set ``THIRAMAI_STRESS_DATABASE_URL``.
"""

from __future__ import annotations

import os
import tempfile
import threading
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Bill, FactoryBillingHold, Inventory, Organization
from services.sale_execution import execute_sell_stock_sync


def _sqlite_file_factory():
    import tempfile

    fd, path = tempfile.mkstemp(suffix="_stress.sqlite")
    os.close(fd)
    engine = create_engine(
        f"sqlite+pysqlite:///{path.replace(os.sep, '/')}",
        connect_args={
            "check_same_thread": False,
            "timeout": 60,
            "autocommit": False,
        },
        pool_pre_ping=True,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            FactoryBillingHold.__table__,
            Inventory.__table__,
            Bill.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as s:
        s.add(Organization(id=1, name="StressOrg", plan="free"))
        s.add(
            Inventory(
                id=1,
                organization_id=1,
                sku_name="STRESS-SKU-100",
                quantity=Decimal("200"),
                location="",
                unit_price=Decimal("10.00"),
                gst_rate_percent=Decimal("0"),
            )
        )
        s.commit()
    return engine, SessionLocal, path


@pytest.fixture
def stress_sqlite_factory():
    engine, SessionLocal, path = _sqlite_file_factory()
    try:
        yield SessionLocal
    finally:
        engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def test_100_serial_sells_consistent_stock_and_bills(stress_sqlite_factory):
    """100 sequential sells: inventory and bill count must match (SQLite / CI)."""
    SessionLocal = stress_sqlite_factory
    for i in range(100):
        out = execute_sell_stock_sync(
            1,
            "STRESS-SKU-100",
            1.0,
            "",
            _session_factory=SessionLocal,
        )
        assert out.get("ok"), f"iteration {i}: {out}"

    with SessionLocal() as s:
        qty = s.execute(
            select(Inventory.quantity).where(Inventory.sku_name == "STRESS-SKU-100")
        ).scalar_one()
        assert float(qty) == pytest.approx(100.0)
        bill_ct = s.execute(select(func.count()).select_from(Bill)).scalar_one()
        assert int(bill_ct) == 100


@pytest.mark.skipif(
    not (os.getenv("THIRAMAI_STRESS_DATABASE_URL") or "").strip(),
    reason="Set THIRAMAI_STRESS_DATABASE_URL (PostgreSQL) to run 100-thread concurrent sell stress",
)
def test_100_concurrent_sells_postgres_serializes_row():
    """
    100 parallel threads each sell 1 unit from stock=200 → 100 remain, 100 bills.
    Requires PostgreSQL (row locking semantics).
    """
    url = (os.getenv("THIRAMAI_STRESS_DATABASE_URL") or "").strip()
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.drop_all(
        bind=engine,
        tables=[
            Bill.__table__,
            Inventory.__table__,
            FactoryBillingHold.__table__,
            Organization.__table__,
        ],
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            FactoryBillingHold.__table__,
            Inventory.__table__,
            Bill.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as s:
        s.add(Organization(id=1, name="StressOrg", plan="free"))
        s.add(
            Inventory(
                id=1,
                organization_id=1,
                sku_name="STRESS-PG-100",
                quantity=Decimal("200"),
                location="",
                unit_price=Decimal("10.00"),
                gst_rate_percent=Decimal("0"),
            )
        )
        s.commit()

    n_threads = 100
    results: list[dict] = []
    lock = threading.Lock()

    def worker():
        out = execute_sell_stock_sync(
            1,
            "STRESS-PG-100",
            1.0,
            "",
            _session_factory=SessionLocal,
        )
        with lock:
            results.append(out)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    oks = [r for r in results if r.get("ok")]
    assert len(oks) == n_threads, [r for r in results if not r.get("ok")]
    with SessionLocal() as s:
        qty = s.execute(
            select(Inventory.quantity).where(Inventory.sku_name == "STRESS-PG-100")
        ).scalar_one()
        assert float(qty) == pytest.approx(100.0)
        bill_ct = s.execute(select(func.count()).select_from(Bill)).scalar_one()
        assert int(bill_ct) == n_threads

    engine.dispose()


def test_two_thread_last_unit_still_validates_locking_pattern():
    """Two threads, 1 unit in stock — exactly one sale succeeds (file-backed SQLite + pool)."""
    fd, path = tempfile.mkstemp(suffix="_stress2.sqlite")
    os.close(fd)
    engine = create_engine(
        f"sqlite+pysqlite:///{path.replace(os.sep, '/')}",
        connect_args={
            "check_same_thread": False,
            "timeout": 60,
            "autocommit": False,
        },
        pool_pre_ping=True,
    )
    try:
        Base.metadata.create_all(
            bind=engine,
            tables=[
                Organization.__table__,
                FactoryBillingHold.__table__,
                Inventory.__table__,
                Bill.__table__,
            ],
        )
        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as s:
            s.add(Organization(id=1, name="X", plan="free"))
            s.add(
                Inventory(
                    id=1,
                    organization_id=1,
                    sku_name="OneLeft",
                    quantity=Decimal("1"),
                    location="",
                    unit_price=Decimal("1"),
                    gst_rate_percent=Decimal("0"),
                )
            )
            s.commit()
        results = []
        lock = threading.Lock()

        def w():
            out = execute_sell_stock_sync(1, "OneLeft", 1.0, "", _session_factory=SessionLocal)
            with lock:
                results.append(out)

        t1 = threading.Thread(target=w)
        t2 = threading.Thread(target=w)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len([r for r in results if r.get("ok")]) == 1
    finally:
        engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass
