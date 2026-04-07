"""
Load test: concurrent **retail sell** + **AI chat** (Locust).

Prerequisites:
  - API running (e.g. ``uvicorn app:app --host 0.0.0.0 --port 8000``)
  - Valid JWT: set ``THIRAMAI_LOCUST_TOKEN`` or login in ``on_start`` (below uses env token only)

Run ~100 users::

    locust -f locustfile.py --host http://127.0.0.1:8000 --users 100 --spawn-rate 10

Optional: ``THIRAMAI_LOCUST_SKU`` (default ``TEST-SKU``) must exist / be sellable for your tenant.
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task


class ThiramaiScaleUser(HttpUser):
    wait_time = between(0.3, 1.5)

    def on_start(self) -> None:
        self.token = (os.getenv("THIRAMAI_LOCUST_TOKEN") or "").strip()
        self.sku = (os.getenv("THIRAMAI_LOCUST_SKU") or "TEST-SKU").strip()

    @task(3)
    def ai_chat_query(self) -> None:
        if not self.token:
            return
        self.client.post(
            "/chat/query",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"message": "Give a one-line inventory health summary for my organization."},
            name="POST /chat/query",
        )

    @task(1)
    def retail_sell(self) -> None:
        if not self.token:
            return
        self.client.post(
            "/inventory/retail-sell",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "sku_name": self.sku,
                "quantity": 0.01,
                "location": "locust",
                "interstate_gst": False,
            },
            name="POST /inventory/retail-sell",
        )
