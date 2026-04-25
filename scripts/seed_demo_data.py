"""
Seed demo data for CEO demo.
Run once to populate realistic business data.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import inspect, text

# Allow `python scripts/seed_demo_data.py` from repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.database import get_engine


def _ensure_admin_operational_role(conn) -> tuple[int | None, int | None]:
    """
    Ensure admin@thiramai.local has an active org membership in an operational role.
    Prefers owner/admin/staff/worker and updates user_organization_memberships (+ users.role_id fallback).
    """
    row = conn.execute(
        text(
            """
            SELECT u.id AS user_id, u.email
            FROM users u
            WHERE lower(u.email) = 'admin@thiramai.local'
            LIMIT 1
            """
        )
    ).mappings().first()
    if not row:
        print("[ERROR] admin@thiramai.local not found")
        return None, None
    user_id = int(row["user_id"])

    org_row = conn.execute(text("SELECT id FROM organizations ORDER BY id LIMIT 1")).mappings().first()
    if not org_row:
        print("[ERROR] no organizations found")
        return user_id, None
    org_id = int(org_row["id"])

    role_row = conn.execute(
        text(
            """
            SELECT id, name
            FROM roles
            WHERE org_id = :org_id
              AND lower(name) IN ('owner','admin','staff','worker')
            ORDER BY CASE lower(name)
                WHEN 'owner' THEN 1
                WHEN 'admin' THEN 2
                WHEN 'staff' THEN 3
                WHEN 'worker' THEN 4
                ELSE 99
            END
            LIMIT 1
            """
        ),
        {"org_id": org_id},
    ).mappings().first()
    if not role_row:
        print("[ERROR] no operational role found in roles table for org", org_id)
        return user_id, org_id
    role_id = int(role_row["id"])
    role_name = str(role_row["name"])

    existing = conn.execute(
        text(
            """
            SELECT id
            FROM user_organization_memberships
            WHERE user_id = :user_id AND organization_id = :org_id
            LIMIT 1
            """
        ),
        {"user_id": user_id, "org_id": org_id},
    ).mappings().first()
    if existing:
        conn.execute(
            text(
                """
                UPDATE user_organization_memberships
                SET role_id = :role_id, is_active = :active
                WHERE id = :id
                """
            ),
            {"role_id": role_id, "active": True, "id": int(existing["id"])},
        )
    else:
        conn.execute(
            text(
                """
                INSERT INTO user_organization_memberships
                    (user_id, organization_id, role_id, is_active)
                VALUES (:user_id, :org_id, :role_id, :active)
                """
            ),
            {"user_id": user_id, "org_id": org_id, "role_id": role_id, "active": True},
        )
    conn.execute(
        text("UPDATE users SET role_id = :role_id WHERE id = :user_id"),
        {"role_id": role_id, "user_id": user_id},
    )
    print(f"[OK] admin role fixed: user_id={user_id}, org_id={org_id}, role={role_name}")
    return user_id, org_id


def _inventory_insert_rows() -> list[dict[str, Any]]:
    return [
        {"sku_name": "Solar Water Pump 1HP", "external_ref": "SWP-001", "quantity": Decimal("50"), "unit_price": Decimal("15000"), "location": "Pumps"},
        {"sku_name": "HDPE Pipe 63mm", "external_ref": "HDPE-063", "quantity": Decimal("200"), "unit_price": Decimal("450"), "location": "Pipes"},
        {"sku_name": "Drip Irrigation Kit", "external_ref": "DRK-001", "quantity": Decimal("30"), "unit_price": Decimal("8500"), "location": "Irrigation"},
        {"sku_name": "Submersible Pump 2HP", "external_ref": "SUB-002", "quantity": Decimal("25"), "unit_price": Decimal("22000"), "location": "Pumps"},
        {"sku_name": "PVC Pipe 50mm", "external_ref": "PVC-050", "quantity": Decimal("500"), "unit_price": Decimal("180"), "location": "Pipes"},
    ]


def seed_inventory() -> None:
    engine = get_engine()
    if engine is None:
        print("[ERROR] DATABASE_URL is not configured")
        return

    insp = inspect(engine)
    if not insp.has_table("inventory_items"):
        print("[ERROR] inventory_items table not found")
        return
    columns = [c["name"] for c in insp.get_columns("inventory_items")]
    print(f"Columns: {columns}")

    required = {"organization_id", "sku_name", "quantity", "location"}
    if not required.issubset(set(columns)):
        print("[ERROR] inventory_items missing required columns:", sorted(required - set(columns)))
        return

    with engine.begin() as conn:
        _user_id, org_id = _ensure_admin_operational_role(conn)
        if org_id is None:
            print("[ERROR] cannot continue without organization id")
            return

        rows = _inventory_insert_rows()
        seeded = 0
        for row in rows:
            payload: dict[str, Any] = {
                "organization_id": org_id,
                "sku_name": row["sku_name"],
                "quantity": row["quantity"],
                "location": row["location"],
            }
            # Optional columns only if present in this deployment schema.
            if "unit" in columns:
                payload["unit"] = "pcs"
            if "unit_price" in columns:
                payload["unit_price"] = row["unit_price"]
            if "external_ref" in columns:
                payload["external_ref"] = row["external_ref"]
            if "total_value" in columns:
                payload["total_value"] = row["quantity"] * row["unit_price"]
            if "reorder_point" in columns:
                payload["reorder_point"] = Decimal("10")

            # Upsert-like behavior on unique (org, sku_name, location).
            existing = conn.execute(
                text(
                    """
                    SELECT id FROM inventory_items
                    WHERE organization_id = :organization_id
                      AND sku_name = :sku_name
                      AND location = :location
                    LIMIT 1
                    """
                ),
                {
                    "organization_id": payload["organization_id"],
                    "sku_name": payload["sku_name"],
                    "location": payload["location"],
                },
            ).mappings().first()
            if existing:
                set_cols = [k for k in payload.keys() if k != "organization_id"]
                assignments = ", ".join(f"{k} = :{k}" for k in set_cols)
                params = dict(payload)
                params["id"] = int(existing["id"])
                conn.execute(text(f"UPDATE inventory_items SET {assignments} WHERE id = :id"), params)
            else:
                cols = ", ".join(payload.keys())
                vals = ", ".join(f":{k}" for k in payload.keys())
                conn.execute(text(f"INSERT INTO inventory_items ({cols}) VALUES ({vals})"), payload)
            seeded += 1
            print(f"[OK] Seeded: {row['sku_name']}")

        total = conn.execute(
            text("SELECT count(*) AS c FROM inventory_items WHERE organization_id = :org_id"),
            {"org_id": org_id},
        ).mappings().first()
        print(f"\n[DONE] Demo seed complete! inserted_or_updated={seeded}, inventory_total={int((total or {}).get('c', 0))}")


if __name__ == "__main__":
    seed_inventory()
