"""Async OS health checks with short in-memory caching."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx


class OSHealthChecker:
    """Real dependency checks for Central Brain OS tiles."""

    CACHE_TTL_SEC = 30.0
    HTTP_TIMEOUT_SEC = 3.0

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _status_for_ratio(ok_count: int, total: int) -> str:
        if total <= 0:
            return "offline"
        if ok_count == total:
            return "healthy"
        if ok_count > 0:
            return "degraded"
        return "offline"

    @staticmethod
    def _entry(status: str, latency_ms: int, reason: str | None = None) -> dict[str, Any]:
        return {
            "status": status,
            "latency_ms": int(latency_ms),
            "last_checked": OSHealthChecker._now_iso(),
            "degraded_reason": reason,
        }

    async def _http_ping(self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, json_body: dict[str, Any] | None = None) -> tuple[bool, int, str | None]:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.HTTP_TIMEOUT_SEC) as client:
                resp = await client.request(method, url, headers=headers, json=json_body)
            latency = int((time.perf_counter() - t0) * 1000)
            ok = 200 <= int(resp.status_code) < 300
            return ok, latency, None if ok else f"http_{resp.status_code}"
        except Exception as exc:
            latency = int((time.perf_counter() - t0) * 1000)
            return False, latency, str(exc)

    async def _check_stock(self, user_id: int) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            from services.broker.probe import test_broker_connection

            result = await asyncio.to_thread(test_broker_connection, int(user_id), execution_mode="live")
            ok = bool(isinstance(result, dict) and result.get("ok"))
            latency = int((time.perf_counter() - t0) * 1000)
            if ok:
                return self._entry("healthy", latency, None)
            detail = str((result or {}).get("error") or (result or {}).get("reason") or "broker_unavailable")
            return self._entry("offline", latency, detail[:300])
        except Exception as exc:
            latency = int((time.perf_counter() - t0) * 1000)
            return self._entry("offline", latency, str(exc)[:300])

    async def _check_research(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
            tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()
            checks: list[tuple[bool, int, str | None]] = []
            if groq_key:
                checks.append(
                    await self._http_ping(
                        "https://api.groq.com/openai/v1/models",
                        method="GET",
                        headers={"Authorization": f"Bearer {groq_key}"},
                    )
                )
            else:
                checks.append((False, 0, "missing_GROQ_API_KEY"))
            if tavily_key:
                checks.append(
                    await self._http_ping(
                        "https://api.tavily.com/search",
                        method="POST",
                        headers={"Authorization": f"Bearer {tavily_key}"},
                        json_body={"query": "health check", "max_results": 1},
                    )
                )
            else:
                checks.append((False, 0, "missing_TAVILY_API_KEY"))
            ok_count = sum(1 for ok, _, _ in checks if ok)
            total = len(checks)
            status = self._status_for_ratio(ok_count, total)
            latency = int((time.perf_counter() - t0) * 1000)
            if status == "healthy":
                return self._entry("healthy", latency, None)
            reasons = ", ".join(r for ok, _, r in checks if not ok and r)
            return self._entry(status, latency, reasons[:300] or "provider_health_failed")
        except Exception as exc:
            latency = int((time.perf_counter() - t0) * 1000)
            return self._entry("offline", latency, str(exc)[:300])

    async def _check_agentic_web(self) -> dict[str, Any]:
        base = (os.getenv("OPENHANDS_BASE_URL") or "").strip()
        if not base:
            return self._entry("offline", 0, "missing_OPENHANDS_BASE_URL")
        ok, latency, reason = await self._http_ping(base.rstrip("/") + "/")
        return self._entry("healthy" if ok else "offline", latency, reason)

    async def _check_personal(self) -> dict[str, Any]:
        base = (os.getenv("N8N_BASE_URL") or "").strip()
        if not base:
            return self._entry("degraded", 0, "missing_N8N_BASE_URL")
        ok, latency, reason = await self._http_ping(base.rstrip("/") + "/healthz")
        return self._entry("healthy" if ok else "offline", latency, reason)

    async def _check_business(self) -> dict[str, Any]:
        base = (os.getenv("ERPNEXT_BASE_URL") or "").strip()
        if not base:
            return self._entry("degraded", 0, "missing_ERPNEXT_BASE_URL")
        ok, latency, reason = await self._http_ping(base.rstrip("/") + "/api/method/ping")
        return self._entry("healthy" if ok else "offline", latency, reason)

    async def check_os(self, os_key: str, *, user_id: int) -> dict[str, Any]:
        norm = (os_key or "").strip().lower()
        if norm == "agentic":
            norm = "agentic_web"
        async with self._lock:
            cached = self._cache.get(norm)
            now = time.time()
            if cached and (now - cached[0]) <= self.CACHE_TTL_SEC:
                return dict(cached[1])
        if norm == "stock":
            result = await self._check_stock(user_id)
        elif norm == "research":
            result = await self._check_research()
        elif norm == "agentic_web":
            result = await self._check_agentic_web()
        elif norm == "business":
            result = await self._check_business()
        elif norm == "personal":
            result = await self._check_personal()
        else:
            result = self._entry("offline", 0, f"unknown_os:{norm}")
        async with self._lock:
            self._cache[norm] = (time.time(), dict(result))
        return result
