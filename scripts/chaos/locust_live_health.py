"""
Live chaos-safe load profile against public health endpoints.

Usage:
  set THIRAMAI_LOAD_TEST_HOST=https://app.thiramai.co.in
  locust -f scripts/chaos/locust_live_health.py --users 100 --spawn-rate 20 --run-time 2m --headless
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

HOST = (os.getenv("THIRAMAI_LOAD_TEST_HOST") or "https://app.thiramai.co.in").rstrip("/")


class LiveHealthUser(HttpUser):
    host = HOST
    wait_time = between(0.1, 0.6)

    @task(4)
    def health_live(self) -> None:
        self.client.get("/health/live", name="GET /health/live")

    @task(1)
    def health_ready(self) -> None:
        self.client.get("/health/ready", name="GET /health/ready")
