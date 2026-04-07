#!/usr/bin/env python3
"""
Optional stress: 100 concurrent retail sells (dummy org/SKU) against PostgreSQL.

SQLite is not suitable for proving 100 parallel writers; use a disposable Postgres URL:

  set THIRAMAI_STRESS_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/stress_db
  python scripts/stress_concurrent_sells.py

Creates minimal tables, runs workers, prints OK/fail counts. Drop the DB or schema afterward.
"""

from __future__ import annotations

import os
import sys
import threading
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Bill, Inventory, Organization
from services.sale_execution import execute_sell_stock_sync


def main() -> int:
    url = (os.getenv("THIRAMAI_STRESS_DATABASE_URL") or "").strip()
    if not url:
        print(
            "Set THIRAMAI_STRESS_DATABASE_URL to a PostgreSQL SQLAlchemy URL.",
            file=sys.stderr,
        )
        return 1
    if "postgresql" not in url and "postgres" not in url:
        print("This script expects PostgreSQL.", file=sys.stderr)
        return 1

    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.drop_all(
        bind=engine,
        tables=[Bill.__table__, Inventory.__table__, Organization.__table__],
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[Organization.__table__, Inventory.__table__, Bill.__table__],
    )
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as s:
        s.add(Organization(id=1, name="StressOrg", plan="free"))
        s.add(
            Inventory(
                id=1,
                organization_id=1,
                sku_name="CLI-STRESS-SKU",
                quantity=Decimal("200"),
                location="",
                unit_price=Decimal("10.00"),
                gst_rate_percent=Decimal("0"),
            )
        )
        s.commit()

    n = 100
    results: list[dict] = []
    lock = threading.Lock()

    def worker():
        out = execute_sell_stock_sync(
            1,
            "CLI-STRESS-SKU",
            1.0,
            "",
            _session_factory=SessionLocal,
        )
        with lock:
            results.append(out)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    oks = sum(1 for r in results if r.get("ok"))
    print(f"OK={oks} / {n}  failures={n - oks}")
    with SessionLocal() as s:
        qty = s.execute(
            select(Inventory.quantity).where(Inventory.sku_name == "CLI-STRESS-SKU")
        ).scalar_one()
        bills = s.execute(select(func.count()).select_from(Bill)).scalar_one()
        print(f"remaining_qty={float(qty)}  bills={int(bills)}")

    engine.dispose()
    return 0 if oks == n and float(qty) == 100.0 and int(bills) == n else 2


if __name__ == "__main__":
    raise SystemExit(main())
