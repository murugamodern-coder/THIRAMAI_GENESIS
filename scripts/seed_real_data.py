#!/usr/bin/env python3
"""
Phase 4: seed 50+ realistic inventory rows (GST slabs, low/zero stock) for AI / dashboard stress tests.

Requires DATABASE_URL. Uses organization id from THIRAMAI_SEED_ORG_ID (default 1) — ensure the org exists.

  python scripts/seed_real_data.py

Idempotent-ish: upserts by (organization_id, sku_name, location) by updating quantity/gst if row exists.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from core.database import get_session_factory
from core.db.models import Inventory, Organization

# GST slabs common in India (total %); mix with 0% exempt
_GST_SLABS = (Decimal("0"), Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28"))

# Sample HSN chapters for seed data (not exhaustive; verify for production SKUs).
_CATEGORY_HSN = {
    "Rice": "1006",
    "Lentils": "0713",
    "Oil": "1517",
    "Spice": "0910",
    "Beverage": "2202",
    "Snacks": "1905",
    "Dairy": "0401",
    "Cleaning": "3402",
    "Electronics": "8517",
    "Hardware": "7326",
    "Textile": "5208",
    "Stationery": "4820",
}

_CATEGORIES = (
    "Rice",
    "Lentils",
    "Oil",
    "Spice",
    "Beverage",
    "Snacks",
    "Dairy",
    "Cleaning",
    "Electronics",
    "Hardware",
    "Textile",
    "Stationery",
)


def _build_rows(org_id: int) -> list[dict]:
    rows: list[dict] = []
    n = 0
    for cat in _CATEGORIES:
        for i in range(5):
            n += 1
            gst = _GST_SLABS[(n + i) % len(_GST_SLABS)]
            sku = f"{cat}-SKU-{n:03d}"
            base_price = Decimal("20") + Decimal(n % 47) * Decimal("3.5")
            # Vary stock: plenty, low (1–2), zero
            if n % 7 == 0:
                qty = Decimal("0")
            elif n % 5 == 0:
                qty = Decimal("1")
            elif n % 11 == 0:
                qty = Decimal("2")
            else:
                qty = Decimal(str(15 + (n % 40)))
            loc = "Main" if n % 2 == 0 else "Warehouse-A"
            rows.append(
                {
                    "organization_id": org_id,
                    "sku_name": sku,
                    "quantity": qty,
                    "location": loc,
                    "unit_price": base_price.quantize(Decimal("0.01")),
                    "gst_rate_percent": gst,
                    "hsn_code": _CATEGORY_HSN.get(cat, "9999"),
                }
            )
    # Pad beyond 50 if needed
    while len(rows) < 52:
        n += 1
        rows.append(
            {
                "organization_id": org_id,
                "sku_name": f"Extra-Item-{n:03d}",
                "quantity": Decimal(str(n % 3)),
                "location": "Overflow",
                "unit_price": Decimal("99.99"),
                "gst_rate_percent": Decimal("18"),
                "hsn_code": "9983",
            }
        )
    return rows


def upsert_inventory(session: Session, org_id: int) -> int:
    count = 0
    for spec in _build_rows(org_id):
        stmt = (
            select(Inventory)
            .where(
                Inventory.organization_id == org_id,
                Inventory.sku_name == spec["sku_name"],
                Inventory.location == spec["location"],
            )
            .limit(1)
        )
        row = session.execute(stmt).scalar_one_or_none()
        tv = spec["quantity"] * spec["unit_price"]
        if row is None:
            session.add(
                Inventory(
                    organization_id=org_id,
                    sku_name=spec["sku_name"],
                    quantity=spec["quantity"],
                    location=spec["location"],
                    unit_price=spec["unit_price"],
                    total_value=tv.quantize(Decimal("0.01")),
                    gst_rate_percent=spec["gst_rate_percent"],
                    hsn_code=spec.get("hsn_code"),
                )
            )
        else:
            row.quantity = spec["quantity"]
            row.unit_price = spec["unit_price"]
            row.gst_rate_percent = spec["gst_rate_percent"]
            row.total_value = tv.quantize(Decimal("0.01"))
            if spec.get("hsn_code"):
                row.hsn_code = spec["hsn_code"]
        count += 1
    return count


def main() -> int:
    factory = get_session_factory()
    if factory is None:
        print("DATABASE_URL is not set; cannot seed.", file=sys.stderr)
        return 1
    org_id = int((os.getenv("THIRAMAI_SEED_ORG_ID") or "1").strip() or "1")
    with factory() as session:
        with session.begin():
            org = session.get(Organization, org_id)
            if org is None:
                print(f"Organization id={org_id} not found.", file=sys.stderr)
                return 1
            n = upsert_inventory(session, org_id)
    print(f"Seeded/updated {n} inventory rows for organization_id={org_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
