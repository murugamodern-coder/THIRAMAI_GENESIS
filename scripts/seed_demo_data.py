"""
Seed demo data for CEO demo.
Run once to populate realistic business data.
"""

from __future__ import annotations

import asyncio

import httpx

BASE_URL = "http://localhost:8000"


async def _login(client: httpx.AsyncClient) -> str | None:
    form = await client.post(
        f"{BASE_URL}/auth/login",
        data={"username": "admin@thiramai.local", "password": "thiramai_2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if form.status_code == 200:
        return str(form.json().get("access_token") or "")
    fallback = await client.post(
        f"{BASE_URL}/auth/login",
        json={"email": "admin@thiramai.local", "password": "thiramai_2026"},
    )
    if fallback.status_code == 200:
        return str(fallback.json().get("access_token") or "")
    return None


async def seed_demo_data() -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        token = await _login(client)
        if not token:
            print("❌ Login failed")
            return
        headers = {"Authorization": f"Bearer {token}"}
        print("✅ Logged in")

        products = [
            {"name": "Solar Water Pump 1HP", "sku": "SWP-001", "quantity": 50, "unit_price": 15000, "category": "Pumps"},
            {"name": "HDPE Pipe 63mm", "sku": "HDPE-063", "quantity": 200, "unit_price": 450, "category": "Pipes"},
            {"name": "Drip Irrigation Kit", "sku": "DRK-001", "quantity": 30, "unit_price": 8500, "category": "Irrigation"},
            {"name": "Submersible Pump 2HP", "sku": "SUB-002", "quantity": 25, "unit_price": 22000, "category": "Pumps"},
            {"name": "PVC Pipe 50mm", "sku": "PVC-050", "quantity": 500, "unit_price": 180, "category": "Pipes"},
        ]

        for product in products:
            payload = {
                "sku_name": product["name"],
                "quantity": product["quantity"],
                "unit_price": product["unit_price"],
                "external_ref": product["sku"],
                "location": product["category"],
                "unit": "pcs",
            }
            r = await client.post(f"{BASE_URL}/inventory/item", headers=headers, json=payload)
            status = "✅" if r.status_code in [200, 201] else "⚠️"
            print(f"{status} Product: {product['name']} -> {r.status_code}")

        print("\n🎯 Demo seed complete!")
        print("Now your dashboard shows real inventory data.")


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
