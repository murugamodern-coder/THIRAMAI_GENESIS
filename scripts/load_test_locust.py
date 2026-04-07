#!/usr/bin/env python3
"""
Locust load test: concurrent users hit POST /chat/query with Bearer JWT.

Prerequisites:
  pip install locust

Usage (from repo root):
  set THIRAMAI_LOAD_TEST_HOST=http://127.0.0.1:8000
  set THIRAMAI_LOAD_TEST_JWT=<paste access_token from POST /auth/login>
  locust -f scripts/load_test_locust.py --users 80 --spawn-rate 10 --run-time 2m --headless

UI mode:
  locust -f scripts/load_test_locust.py
  Open http://localhost:8089 — set host to your API base URL.

Notes:
  - Use a user with **staff** or **admin** role if you need ``sell_stock`` auto-execution under load.
  - Default JWT expiry may end long runs; refresh token or raise JWT_EXPIRE_MINUTES for tests only.
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

HOST = (os.getenv("THIRAMAI_LOAD_TEST_HOST") or "http://127.0.0.1:8000").rstrip("/")
TOKEN = (os.getenv("THIRAMAI_LOAD_TEST_JWT") or "").strip()

GENERAL_MESSAGES = [
    "Give a one-line status for operations.",
    "Summarize inventory risk in one sentence.",
    "What should we watch this week financially?",
]

SALE_MESSAGES = [
    "Sell 1 unit of Item A.",
    "Sell 2 units of Item A",
    "Please sell 1 unit of Item A.",
]


class ChatQueryUser(HttpUser):
    host = HOST
    wait_time = between(0.5, 2.5)

    def on_start(self) -> None:
        if not TOKEN:
            raise RuntimeError(
                "Set THIRAMAI_LOAD_TEST_JWT to a valid Bearer access_token (from POST /auth/login)."
            )
        self._headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        }

    @task(3)
    def chat_general(self) -> None:
        msg = random.choice(GENERAL_MESSAGES)
        self.client.post("/chat/query", json={"message": msg}, headers=self._headers, name="/chat/query")

    @task(1)
    def chat_sale_intent(self) -> None:
        msg = random.choice(SALE_MESSAGES)
        self.client.post("/chat/query", json={"message": msg}, headers=self._headers, name="/chat/query [sale]")
