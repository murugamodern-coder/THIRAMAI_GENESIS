"""
Scheduled autonomous tasks: morning brief (IST), stock alert monitor tick, health heartbeat.

Uses asyncio loops + sync DB/Groq in threads; Redis async client from ``core.redis_cache``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

if TYPE_CHECKING:
    from fastapi import FastAPI

_log = logging.getLogger("thiramai.scheduler")

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc,assignment]

INDIA_TZ = ZoneInfo("Asia/Kolkata") if ZoneInfo else None


def _now_ist() -> datetime:
    if INDIA_TZ:
        return datetime.now(INDIA_TZ)
    return datetime.now(timezone.utc)


def seconds_until_next_ist(hour: int, minute: int = 0) -> float:
    """Seconds until next occurrence of ``hour``:``minute`` in Asia/Kolkata."""
    now = _now_ist()
    if INDIA_TZ:
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= target:
            target = target + timedelta(days=1)
        return max(1.0, (target - now).total_seconds())
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target = target + timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


def distinct_active_organization_ids_sync() -> list[int]:
    """Organizations that have at least one active membership with an active user."""
    from core.database import get_session_factory
    from core.db.models import User, UserOrganizationMembership

    factory = get_session_factory()
    if factory is None:
        return []
    with factory() as session:
        stmt = (
            select(UserOrganizationMembership.organization_id)
            .join(User, UserOrganizationMembership.user_id == User.id)
            .where(
                UserOrganizationMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
            .distinct()
        )
        rows = session.execute(stmt).scalars().all()
        return sorted({int(r) for r in rows if r is not None})


def fetch_stock_alert_rows_sync(limit: int = 50) -> list[tuple[str, int]]:
    """Return (symbol, organization_id) for active alerts."""
    from core.database import get_session_factory
    from core.db.models import StockPriceAlert, User, UserOrganizationMembership

    factory = get_session_factory()
    if factory is None:
        return []
    with factory() as session:
        stmt = (
            select(StockPriceAlert.symbol, UserOrganizationMembership.organization_id)
            .join(User, StockPriceAlert.user_id == User.id)
            .join(UserOrganizationMembership, UserOrganizationMembership.user_id == User.id)
            .where(
                StockPriceAlert.is_active.is_(True),
                User.is_active.is_(True),
                UserOrganizationMembership.is_active.is_(True),
            )
            .distinct()
            .limit(limit)
        )
        rows = session.execute(stmt).all()
        out: list[tuple[str, int]] = []
        for sym, oid in rows:
            if sym is None or oid is None:
                continue
            out.append((str(sym), int(oid)))
        return out


def generate_morning_brief_text_sync(org_id: int) -> tuple[str, str]:
    """Return (brief_text, generated_at_iso)."""
    from services.research_common import long_llm_sync

    _ = org_id

    dt = _now_ist()
    prompt = f"""
நீ Thiramai. இன்றைய நாளுக்கான (
{dt.strftime('%d %B %Y, %A')})
சுருக்கமான daily brief தயார் பண்ணு:

1. 🌅 இன்றைய நாள் எப்படி இருக்கும்
2. ✅ முக்கியமான tasks reminder
3. 📊 Business focus area
4. 💡 ஒரு productive tip

Tamil-ல சுருக்கமா சொல்லு (200 words max).
"""

    brief = long_llm_sync(
        "You are Thiramai, the user's sovereign Tamil–English productivity assistant.",
        prompt.strip(),
        prefer_gemini=False,
    ).strip()
    ts = datetime.now(timezone.utc).isoformat()
    return brief or "Morning brief unavailable right now.", ts


def generate_morning_brief_payload_sync(org_id: int) -> dict[str, Any]:
    brief, ts = generate_morning_brief_text_sync(org_id)
    return {"brief": brief, "generated_at": ts}


async def fetch_or_generate_morning_brief(org_id: int) -> dict[str, Any]:
    """Redis-backed brief or on-demand generation for API."""
    from core.redis_cache import get_redis

    redis = await get_redis()
    key = f"thiramai:morning_brief:{org_id}"
    if redis:
        raw = await redis.get(key)
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("brief"):
                    return {
                        "ok": True,
                        "brief": str(data["brief"]),
                        "generated_at": str(data.get("generated_at") or ""),
                    }
            except (json.JSONDecodeError, TypeError):
                pass
    payload = await asyncio.to_thread(generate_morning_brief_payload_sync, org_id)
    if redis:
        await redis.set(key, json.dumps(payload, ensure_ascii=False), ex=86400)
    return {
        "ok": True,
        "brief": str(payload.get("brief") or ""),
        "generated_at": str(payload.get("generated_at") or ""),
    }


class ThiramaiScheduler:
    """Background asyncio tasks triggered at intervals (IST-aligned daily brief)."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.tasks: list[asyncio.Task[Any]] = []
        self.running = False

    async def start(self) -> None:
        self.running = True
        self.tasks = [
            asyncio.create_task(self.daily_morning_brief()),
            asyncio.create_task(self.stock_alert_monitor()),
            asyncio.create_task(self.system_health_check()),
            asyncio.create_task(self.memory_cleanup()),
        ]

    async def stop(self) -> None:
        self.running = False
        for t in self.tasks:
            t.cancel()
        self.tasks.clear()

    async def daily_morning_brief(self) -> None:
        """Every day at ~8:00 AM IST — generate briefs per active org and store in Redis."""
        while self.running:
            try:
                await asyncio.sleep(seconds_until_next_ist(8, 0))
                if self.running:
                    await self._run_morning_brief()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("daily_morning_brief loop error: %s", exc)
                await asyncio.sleep(60)

    async def _run_morning_brief(self) -> None:
        try:
            from core.redis_cache import get_redis

            redis = await get_redis()
            org_ids = await asyncio.to_thread(distinct_active_organization_ids_sync)
            for oid in org_ids:
                payload = await asyncio.to_thread(generate_morning_brief_payload_sync, oid)
                if redis:
                    key = f"thiramai:morning_brief:{oid}"
                    await redis.set(key, json.dumps(payload, ensure_ascii=False), ex=86400)
        except Exception as exc:
            _log.warning("Morning brief error: %s", exc)

    async def stock_alert_monitor(self) -> None:
        """Every 5 minutes — snapshot active stock alert rules into Redis lists per org."""
        while self.running:
            try:
                await asyncio.sleep(300)
                if self.running:
                    await self._check_stock_alerts()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("stock_alert_monitor loop error: %s", exc)
                await asyncio.sleep(30)

    async def _check_stock_alerts(self) -> None:
        from core.redis_cache import get_redis

        redis = await get_redis()
        if not redis:
            return
        rows = await asyncio.to_thread(fetch_stock_alert_rows_sync, 50)
        now_iso = _now_ist().isoformat()
        by_org: defaultdict[int, list[str]] = defaultdict(list)
        for symbol, org_id in rows:
            by_org[org_id].append(symbol)
        for org_id, syms in by_org.items():
            key = f"thiramai:stock_alert:{org_id}"
            tail = ", ".join(sorted(set(syms))[:12])
            more = "…" if len(set(syms)) > 12 else ""
            msg = json.dumps(
                {
                    "icon": "📊",
                    "message": f"Stock alerts monitored ({len(set(syms))}): {tail}{more}",
                    "time": now_iso,
                    "type": "stock",
                },
                ensure_ascii=False,
            )
            await redis.lpush(key, msg)
            await redis.ltrim(key, 0, 49)
            await redis.expire(key, 3600)

    async def system_health_check(self) -> None:
        """Every 15 minutes — record last scheduler heartbeat in Redis."""
        while self.running:
            try:
                await asyncio.sleep(900)
                if not self.running:
                    break
                from core.redis_cache import get_redis

                redis = await get_redis()
                if redis:
                    await redis.set(
                        "thiramai:last_health_check",
                        _now_ist().isoformat(),
                        ex=1800,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("Health check error: %s", exc)

    async def memory_cleanup(self) -> None:
        """Daily tick — conversation keys already use Redis TTL."""
        while self.running:
            try:
                await asyncio.sleep(86400)
                _log.info("Memory cleanup tick (conversation keys self-expire via TTL)")
            except asyncio.CancelledError:
                break
