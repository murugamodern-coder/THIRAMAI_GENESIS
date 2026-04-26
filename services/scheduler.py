"""
Scheduled autonomous tasks: morning brief (IST), stock alert monitor tick, health heartbeat,
continuous brain loop (``brain_continuous_loop_cron`` every 5 minutes), and more.

Uses asyncio loops + sync DB/Groq in threads; Redis async client from ``core.redis_cache``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from core.observability import log_structured

if TYPE_CHECKING:
    from fastapi import FastAPI

_log = logging.getLogger("thiramai.scheduler")

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc,assignment]

INDIA_TZ = ZoneInfo("Asia/Kolkata") if ZoneInfo else None


def _run_command_via_brain_sync(user_id: int, organization_id: int, command: str) -> dict[str, Any]:
    from services.brain_execute import brain_execute

    return brain_execute(str(command or "")[:1200], int(user_id), int(organization_id))


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


def _seconds_until_next_ist_weekday(weekday: int, hour: int, minute: int = 0) -> float:
    """Seconds until next ``weekday`` (0=Mon … 6=Sun) at ``hour``:``minute`` IST."""
    now = _now_ist()
    target = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    days_ahead = (int(weekday) - now.weekday()) % 7
    if days_ahead == 0 and now >= target:
        days_ahead = 7
    target = target + timedelta(days=days_ahead)
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


def distinct_active_user_org_pairs_sync(limit: int = 200) -> list[tuple[int, int]]:
    """Active (user_id, organization_id) pairs for tenant periodic tasks."""
    from core.database import get_session_factory
    from core.db.models import User, UserOrganizationMembership

    factory = get_session_factory()
    if factory is None:
        return []
    with factory() as session:
        stmt = (
            select(UserOrganizationMembership.user_id, UserOrganizationMembership.organization_id)
            .join(User, UserOrganizationMembership.user_id == User.id)
            .where(UserOrganizationMembership.is_active.is_(True), User.is_active.is_(True))
            .limit(max(1, min(int(limit), 2000)))
        )
        rows = session.execute(stmt).all()
        out: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for uid, oid in rows:
            if uid is None or oid is None:
                continue
            pair = (int(uid), int(oid))
            if pair in seen:
                continue
            seen.add(pair)
            out.append(pair)
        return out


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


def _autonomous_business_operator_enabled() -> bool:
    try:
        from services.autonomous_business_operator import is_enabled

        return bool(is_enabled())
    except Exception:  # noqa: BLE001
        return False


def _user_kill_switch_active(user_id: int) -> bool:
    """True when user-level execution kill switch is active."""
    try:
        from services.governance_engine import is_kill_switch_active

        return bool(is_kill_switch_active(int(user_id)))
    except Exception:  # noqa: BLE001
        return False


def _env_int(name: str, default: int, *, low: int = 1, high: int = 100000) -> int:
    try:
        v = int((os.getenv(name) or str(default)).strip() or str(default))
    except Exception:
        v = int(default)
    return max(int(low), min(int(high), int(v)))


def _system_pressure_snapshot_sync(window_minutes: int = 30) -> dict[str, Any]:
    from core.database import get_session_factory
    from core.db.models import ActionExecutionRun

    fn = get_session_factory()
    if fn is None:
        return {"ok": False, "reason": "database_unavailable"}
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=max(1, int(window_minutes)))
    with fn() as session:
        total_rows = session.execute(
            select(ActionExecutionRun.id).where(ActionExecutionRun.created_at >= cutoff).limit(5000)
        ).all()
        success_rows = session.execute(
            select(ActionExecutionRun.id).where(
                ActionExecutionRun.created_at >= cutoff,
                ActionExecutionRun.status == "completed",
            ).limit(5000)
        ).all()
        failed_rows = session.execute(
            select(ActionExecutionRun.id).where(
                ActionExecutionRun.created_at >= cutoff,
                ActionExecutionRun.status == "failed",
            ).limit(5000)
        ).all()
        retry_rows = session.execute(
            select(ActionExecutionRun.id).where(
                ActionExecutionRun.created_at >= cutoff,
                ActionExecutionRun.source_command.ilike("%[auto-retry parent=%"),
            ).limit(5000)
        ).all()
        backlog_rows = session.execute(
            select(ActionExecutionRun.id).where(
                ActionExecutionRun.status.in_(["planned", "awaiting_confirmation", "running"])
            ).limit(5000)
        ).all()
        stuck_rows = session.execute(
            select(ActionExecutionRun.id).where(
                ActionExecutionRun.status == "running",
                ActionExecutionRun.updated_at < (now - timedelta(minutes=20)),
            ).limit(5000)
        ).all()
    total = len(total_rows)
    success = len(success_rows)
    failed = len(failed_rows)
    retries = len(retry_rows)
    backlog = len(backlog_rows)
    stuck = len(stuck_rows)
    return {
        "ok": True,
        "window_minutes": int(window_minutes),
        "total": total,
        "success_rate": (float(success) / float(total)) if total else 0.0,
        "failure_rate": (float(failed) / float(total)) if total else 0.0,
        "retry_rate": (float(retries) / float(total)) if total else 0.0,
        "backlog": backlog,
        "stuck": stuck,
    }


def _rotate_pairs(pairs: list[tuple[int, int]], offset: int) -> list[tuple[int, int]]:
    if not pairs:
        return []
    n = len(pairs)
    o = int(offset) % n
    return pairs[o:] + pairs[:o]


async def _run_bounded_pairs(
    pairs: list[tuple[int, int]],
    *,
    worker_coro,
    max_concurrency: int = 8,
) -> None:
    sem = asyncio.Semaphore(max(1, int(max_concurrency)))

    async def _one(uid: int, oid: int) -> None:
        async with sem:
            await worker_coro(uid, oid)

    tasks = [asyncio.create_task(_one(int(uid), int(oid))) for uid, oid in pairs]
    if not tasks:
        return
    await asyncio.gather(*tasks, return_exceptions=True)


class ThiramaiScheduler:
    """Background asyncio tasks triggered at intervals (IST-aligned daily brief)."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.tasks: list[asyncio.Task[Any]] = []
        self.running = False
        self._loop_cursor: dict[str, int] = defaultdict(int)
        self._guard: dict[str, Any] = {
            "degraded": False,
            "blocked_autonomy": False,
            "reduced_concurrency_factor": 1.0,
            "stable_ticks": 0,
            "degraded_reason": "",
            "last_snapshot": {},
        }

    async def start(self) -> None:
        self.running = True
        self.tasks = [
            asyncio.create_task(self.daily_morning_brief()),
            asyncio.create_task(self.stock_alert_monitor()),
            asyncio.create_task(self.system_health_check()),
            asyncio.create_task(self.memory_cleanup()),
            asyncio.create_task(self.execution_watchdog_cron()),
            asyncio.create_task(self.opportunity_scan_cron()),
            asyncio.create_task(self.learning_optimize_cron()),
            asyncio.create_task(self.automation_scheduled_eval_cron()),
            asyncio.create_task(self.money_loop_cron()),
            asyncio.create_task(self.goal_engine_cron()),
            asyncio.create_task(self.research_loop_cron()),
            asyncio.create_task(self.continuous_thinking_cron()),
            asyncio.create_task(self.brain_continuous_loop_cron()),
            asyncio.create_task(self.strategic_intelligence_cron()),
            asyncio.create_task(self.autonomous_operations_cron()),
            asyncio.create_task(self.continuity_loop_cron()),
            asyncio.create_task(self.domain_weekly_review_cron()),
            asyncio.create_task(self.nightly_research_cron()),
            asyncio.create_task(self.architect_auto_propose_cron()),
            asyncio.create_task(self.world_model_snapshot_cron()),
            asyncio.create_task(self.meta_learning_cycle_cron()),
            asyncio.create_task(self.learning_pipeline_nightly_cron()),
            asyncio.create_task(self.self_evolution_trigger_cron()),
            asyncio.create_task(self.online_learner_resolve_cron()),
            asyncio.create_task(self.causal_graph_populate_cron()),
            asyncio.create_task(self.feature_archive_daily_cron()),
            asyncio.create_task(self.model_ensemble_train_cron()),
            asyncio.create_task(self.ohlcv_daily_fetch_cron()),
            asyncio.create_task(self.hal_state_snapshot_cron()),
            asyncio.create_task(self.paper_trading_cron()),
            asyncio.create_task(self.weekly_backtest_cron()),
        ]
        if _autonomous_business_operator_enabled():
            self.tasks.append(asyncio.create_task(self.autonomous_business_operator_cron()))

    async def stop(self) -> None:
        self.running = False
        for t in self.tasks:
            t.cancel()
        self.tasks.clear()

    async def _refresh_guard(self) -> dict[str, Any]:
        snap = await asyncio.to_thread(_system_pressure_snapshot_sync, _env_int("THIRAMAI_GUARD_WINDOW_MINUTES", 30, low=5, high=240))
        self._guard["last_snapshot"] = snap
        if not bool(snap.get("ok")):
            return self._guard
        fail_thr = float((os.getenv("THIRAMAI_GUARD_FAILURE_RATE_THRESHOLD") or "0.30").strip() or 0.30)
        retry_thr = float((os.getenv("THIRAMAI_GUARD_RETRY_RATE_THRESHOLD") or "0.25").strip() or 0.25)
        backlog_thr = _env_int("THIRAMAI_GUARD_BACKLOG_THRESHOLD", 120, low=10, high=10000)
        stuck_thr = _env_int("THIRAMAI_GUARD_STUCK_THRESHOLD", 1, low=0, high=1000)
        degrade = (
            float(snap.get("failure_rate") or 0.0) > fail_thr
            or float(snap.get("retry_rate") or 0.0) > retry_thr
            or int(snap.get("backlog") or 0) > backlog_thr
            or int(snap.get("stuck") or 0) >= stuck_thr
        )
        if degrade:
            self._guard["degraded"] = True
            self._guard["blocked_autonomy"] = True
            self._guard["reduced_concurrency_factor"] = 0.5
            self._guard["stable_ticks"] = 0
            self._guard["degraded_reason"] = (
                f"fail={snap.get('failure_rate'):.3f},retry={snap.get('retry_rate'):.3f},"
                f"backlog={int(snap.get('backlog') or 0)},stuck={int(snap.get('stuck') or 0)}"
            )
            log_structured("scheduler_guard_degraded", reason=self._guard["degraded_reason"], snapshot=snap)
        else:
            self._guard["stable_ticks"] = int(self._guard.get("stable_ticks") or 0) + 1
            recover_ticks = _env_int("THIRAMAI_GUARD_RECOVERY_TICKS", 3, low=1, high=100)
            if self._guard.get("degraded") and int(self._guard["stable_ticks"]) >= recover_ticks:
                self._guard["degraded"] = False
                self._guard["blocked_autonomy"] = False
                self._guard["reduced_concurrency_factor"] = 1.0
                self._guard["degraded_reason"] = ""
                log_structured("scheduler_guard_recovered", stable_ticks=int(self._guard["stable_ticks"]), snapshot=snap)
        return self._guard

    def _guarded_concurrency(self, base: int) -> int:
        factor = float(self._guard.get("reduced_concurrency_factor") or 1.0)
        return max(1, int(max(1, int(base)) * factor))

    def _load_shed_pairs(self, loop_name: str, pairs: list[tuple[int, int]], *, high_priority_only: bool = False) -> list[tuple[int, int]]:
        items = [(int(uid), int(oid)) for uid, oid in pairs]
        if not items:
            return []
        cur = int(self._loop_cursor.get(loop_name) or 0)
        rotated = _rotate_pairs(items, cur)
        self._loop_cursor[loop_name] = (cur + 1) % len(rotated)
        if not self._guard.get("degraded"):
            return rotated
        max_items = _env_int("THIRAMAI_GUARD_MAX_PAIRS_WHEN_DEGRADED", 30, low=1, high=5000)
        subset = rotated[:max_items]
        if high_priority_only:
            return subset[: max(1, max_items // 2)]
        return subset

    async def autonomous_business_operator_cron(self) -> None:
        """Every 3–5 min (default 4): mega-tick (execution loop, env scan, autonomy) with staggered deal/strategy."""
        from services.autonomous_business_operator import (
            mega_tick_interval_seconds,
            run_business_operator_tick_batch,
        )

        tick_n = 0
        while self.running:
            try:
                if not self.running:
                    break
                tick_n += 1
                await asyncio.to_thread(run_business_operator_tick_batch, tick_n)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                _log.warning("autonomous_business_operator_cron error: %s", exc)
            try:
                await asyncio.sleep(mega_tick_interval_seconds())
            except asyncio.CancelledError:
                break

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

    async def nightly_research_cron(self) -> None:
        """Every day at ~3:00 AM IST — autonomous research agent (Phase 3).

        Disable with ``THIRAMAI_NIGHTLY_RESEARCH_CRON=0``. Hour can be
        overridden with ``THIRAMAI_NIGHTLY_RESEARCH_HOUR_IST`` (default 3).
        """
        if (os.getenv("THIRAMAI_NIGHTLY_RESEARCH_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("nightly_research_cron disabled via env")
            return
        try:
            hour = int((os.getenv("THIRAMAI_NIGHTLY_RESEARCH_HOUR_IST") or "3").strip())
        except ValueError:
            hour = 3
        hour = max(0, min(23, hour))
        while self.running:
            try:
                await asyncio.sleep(seconds_until_next_ist(hour, 0))
                if not self.running:
                    break
                await self._run_nightly_research()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("nightly_research_cron loop error: %s", exc)
                await asyncio.sleep(60)

    async def _run_nightly_research(self) -> None:
        try:
            from services.research.autonomous_researcher import run_nightly_research

            summary = await asyncio.to_thread(run_nightly_research)
            log_structured(
                "nightly_research_done",
                ok=bool(summary.get("ok")),
                users=len(summary.get("users") or []),
            )
        except Exception as exc:
            _log.warning("nightly research run failed: %s", exc)

    async def architect_auto_propose_cron(self) -> None:
        """Self-Evolution Phase 4 — hourly capability-gap auto-propose loop.

        Always sleeps an hour between ticks. The proposer itself is gated by
        ``THIRAMAI_ARCHITECT_AUTO_PROPOSE`` (defaults to off) so the job is safe
        to schedule unconditionally; without the env flag it just no-ops.
        Disable the cron entirely with ``THIRAMAI_ARCHITECT_CRON=0``.
        """
        if (os.getenv("THIRAMAI_ARCHITECT_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("architect_auto_propose_cron disabled via env")
            return
        interval_min = max(15, _env_int("THIRAMAI_ARCHITECT_CRON_MINUTES", 60, low=15, high=720))
        # Stagger initial run so multiple workers don't pile up.
        await asyncio.sleep(min(120, interval_min * 60 // 4))
        while self.running:
            try:
                await self._run_architect_auto_propose()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("architect_auto_propose_cron error: %s", exc)
            await asyncio.sleep(interval_min * 60)

    async def _run_architect_auto_propose(self) -> None:
        try:
            from services.architect.architecture_proposer import auto_propose_loop

            result = await asyncio.to_thread(auto_propose_loop)
            log_structured(
                "architect_auto_propose",
                ok=bool(result.get("ok")),
                skipped=bool(result.get("skipped")),
                reason=result.get("reason") or "",
                proposed=len(result.get("proposed") or []),
            )
        except Exception as exc:
            _log.warning("architect auto-propose failed: %s", exc)

    async def world_model_snapshot_cron(self) -> None:
        """Self-Evolution Phase 4 — periodic Bayesian world-model tick.

        Default cadence: every 30 minutes. Snapshots are persisted to
        ``world_state_snapshots`` and the transition-edge counts are updated
        from the discretised state signature.
        Disable with ``THIRAMAI_WORLD_MODEL_CRON=0``.
        """
        if (os.getenv("THIRAMAI_WORLD_MODEL_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("world_model_snapshot_cron disabled via env")
            return
        interval_min = max(5, _env_int("THIRAMAI_WORLD_MODEL_INTERVAL_MIN", 30, low=5, high=240))
        # Small initial offset so we don't fight the morning brief.
        await asyncio.sleep(60)
        while self.running:
            try:
                await self._run_world_model_snapshot()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("world_model_snapshot_cron error: %s", exc)
            await asyncio.sleep(interval_min * 60)

    async def _run_world_model_snapshot(self) -> None:
        try:
            from services.world_model.bayesian_world_model import snapshot_world_state

            org_ids = await asyncio.to_thread(distinct_active_organization_ids_sync)
            if not org_ids:
                # Fall back to a single null-org snapshot so the engine still warms up.
                org_ids = [None]  # type: ignore[list-item]
            for oid in org_ids:
                try:
                    res = await asyncio.to_thread(
                        snapshot_world_state, organization_id=oid, user_id=None
                    )
                    log_structured(
                        "world_model_snapshot",
                        organization_id=oid,
                        ok=bool(res.get("ok")),
                        signature=str(res.get("state_signature") or ""),
                        evidence_count=int(res.get("evidence_count") or 0),
                    )
                except Exception as exc:
                    _log.debug("world_model snapshot org=%s err=%s", oid, exc)
        except Exception as exc:
            _log.warning("world model snapshot run failed: %s", exc)

    async def meta_learning_cycle_cron(self) -> None:
        """Self-Evolution Phase 4 — weekly meta-learning cycle.

        Runs Sunday 04:00 IST by default. Disable with
        ``THIRAMAI_META_LEARNER_CRON=0``. Override day/hour with
        ``THIRAMAI_META_LEARNER_DAY_IST`` (0=Mon … 6=Sun, default ``6``) and
        ``THIRAMAI_META_LEARNER_HOUR_IST`` (default ``4``).
        """
        if (os.getenv("THIRAMAI_META_LEARNER_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("meta_learning_cycle_cron disabled via env")
            return
        try:
            target_day = int((os.getenv("THIRAMAI_META_LEARNER_DAY_IST") or "6").strip())
        except ValueError:
            target_day = 6
        try:
            target_hour = int((os.getenv("THIRAMAI_META_LEARNER_HOUR_IST") or "4").strip())
        except ValueError:
            target_hour = 4
        target_day = max(0, min(6, target_day))
        target_hour = max(0, min(23, target_hour))
        while self.running:
            try:
                await asyncio.sleep(_seconds_until_next_ist_weekday(target_day, target_hour))
                if not self.running:
                    break
                await self._run_meta_learning_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("meta_learning_cycle_cron error: %s", exc)
                await asyncio.sleep(60)

    async def _run_meta_learning_cycle(self) -> None:
        try:
            from services.ml.meta_learner import run_full_meta_cycle

            tune_for = [
                d.strip()
                for d in (os.getenv("THIRAMAI_META_LEARNER_TUNE_FOR") or "irrigation_manufacturing,equity_trading").split(",")
                if d.strip()
            ]
            result = await asyncio.to_thread(run_full_meta_cycle, tune_hp_for=tune_for)
            log_structured(
                "meta_learning_cycle_done",
                domains=len(result.get("domains") or []),
                fi_runs=sum(
                    1 for r in (result.get("feature_importance") or {}).values() if (r or {}).get("ok")
                ),
                tuned=len(result.get("hyperparameters") or {}),
            )
        except Exception as exc:
            _log.warning("meta learning cycle failed: %s", exc)

    async def learning_pipeline_nightly_cron(self) -> None:
        """Self-Evolution Phase 1 — nightly learning pipeline (pattern mine + retrain).

        Default 02:00 IST. Disable with ``THIRAMAI_LEARNING_NIGHTLY_CRON=0``.
        Override hour with ``THIRAMAI_LEARNING_NIGHTLY_HOUR_IST`` (default 2).
        """
        if (os.getenv("THIRAMAI_LEARNING_NIGHTLY_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("learning_pipeline_nightly_cron disabled via env")
            return
        try:
            hour = int((os.getenv("THIRAMAI_LEARNING_NIGHTLY_HOUR_IST") or "2").strip())
        except ValueError:
            hour = 2
        hour = max(0, min(23, hour))
        while self.running:
            try:
                await asyncio.sleep(seconds_until_next_ist(hour, 0))
                if not self.running:
                    break
                await self._run_learning_pipeline_nightly()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("learning_pipeline_nightly_cron loop error: %s", exc)
                await asyncio.sleep(60)

    async def _run_learning_pipeline_nightly(self) -> None:
        try:
            from services.ml.learning_pipeline import run_nightly

            org_ids = await asyncio.to_thread(distinct_active_organization_ids_sync)
            if not org_ids:
                org_ids = [None]  # type: ignore[list-item]
            patterns_total = 0
            train_ok = 0
            for oid in org_ids:
                try:
                    res = await asyncio.to_thread(run_nightly, oid)
                    patterns_total += int((res or {}).get("patterns_upserted") or 0)
                    if bool(((res or {}).get("train_result") or {}).get("ok")):
                        train_ok += 1
                except Exception as exc:
                    _log.debug("learning_pipeline_nightly org=%s err=%s", oid, exc)
            log_structured(
                "learning_pipeline_nightly_done",
                orgs=len(org_ids),
                patterns_upserted=patterns_total,
                models_trained=train_ok,
            )
        except Exception as exc:
            _log.warning("learning pipeline nightly failed: %s", exc)

    async def self_evolution_trigger_cron(self) -> None:
        """Self-Evolution Phase 1 — hourly trigger check (declining metrics, recurring errors).

        Disable with ``THIRAMAI_SELF_EVOLUTION_TRIGGER_CRON=0``. Hourly cadence
        is overridable via ``THIRAMAI_SELF_EVOLUTION_TRIGGER_MINUTES`` (default 60).
        """
        if (os.getenv("THIRAMAI_SELF_EVOLUTION_TRIGGER_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("self_evolution_trigger_cron disabled via env")
            return
        interval_min = max(15, _env_int("THIRAMAI_SELF_EVOLUTION_TRIGGER_MINUTES", 60, low=15, high=720))
        # Stagger first run by ~3 minutes to avoid bootstrap collisions.
        await asyncio.sleep(180)
        while self.running:
            try:
                await self._run_self_evolution_trigger()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("self_evolution_trigger_cron error: %s", exc)
            await asyncio.sleep(interval_min * 60)

    async def _run_self_evolution_trigger(self) -> None:
        try:
            from services.self_evolution_trigger import check_and_trigger

            org_ids = await asyncio.to_thread(distinct_active_organization_ids_sync)
            if not org_ids:
                org_ids = [None]  # type: ignore[list-item]
            proposals_total = 0
            for oid in org_ids:
                try:
                    res = await asyncio.to_thread(check_and_trigger, organization_id=oid)
                    proposals_total += int((res or {}).get("proposals_count") or 0)
                except Exception as exc:
                    _log.debug("self_evolution_trigger org=%s err=%s", oid, exc)
            log_structured(
                "self_evolution_trigger_done",
                orgs=len(org_ids),
                proposals=proposals_total,
            )
        except Exception as exc:
            _log.warning("self evolution trigger failed: %s", exc)

    async def online_learner_resolve_cron(self) -> None:
        """Self-Evolution Phase 2 — periodic ``predictions_pending`` resolver.

        Every 30 minutes by default. Disable with ``THIRAMAI_ONLINE_LEARNER_CRON=0``.
        Cadence override: ``THIRAMAI_ONLINE_LEARNER_INTERVAL_MIN`` (default 30).
        """
        if (os.getenv("THIRAMAI_ONLINE_LEARNER_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("online_learner_resolve_cron disabled via env")
            return
        interval_min = max(5, _env_int("THIRAMAI_ONLINE_LEARNER_INTERVAL_MIN", 30, low=5, high=240))
        # Small initial offset.
        await asyncio.sleep(120)
        while self.running:
            try:
                await self._run_online_learner_resolve()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("online_learner_resolve_cron error: %s", exc)
            await asyncio.sleep(interval_min * 60)

    async def _run_online_learner_resolve(self) -> None:
        try:
            from services.ml.online_learner import resolve_pending

            org_ids = await asyncio.to_thread(distinct_active_organization_ids_sync)
            if not org_ids:
                org_ids = [None]  # type: ignore[list-item]
            resolved_total = 0
            for oid in org_ids:
                try:
                    res = await asyncio.to_thread(resolve_pending, limit=200, organization_id=oid)
                    resolved_total += int((res or {}).get("resolved") or 0)
                except Exception as exc:
                    _log.debug("online_learner_resolve org=%s err=%s", oid, exc)
            log_structured(
                "online_learner_resolve_done",
                orgs=len(org_ids),
                resolved=resolved_total,
            )
        except Exception as exc:
            _log.warning("online learner resolve failed: %s", exc)

    async def causal_graph_populate_cron(self) -> None:
        """Self-Evolution Phase 2 — daily causal-edge population from ``learning_logs``.

        Default 03:00 IST. Disable with ``THIRAMAI_CAUSAL_GRAPH_CRON=0``.
        Hour override: ``THIRAMAI_CAUSAL_GRAPH_HOUR_IST`` (default 3).
        Lookback override: ``THIRAMAI_CAUSAL_GRAPH_LOOKBACK_DAYS`` (default 30).
        """
        if (os.getenv("THIRAMAI_CAUSAL_GRAPH_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("causal_graph_populate_cron disabled via env")
            return
        try:
            hour = int((os.getenv("THIRAMAI_CAUSAL_GRAPH_HOUR_IST") or "3").strip())
        except ValueError:
            hour = 3
        hour = max(0, min(23, hour))
        lookback = _env_int("THIRAMAI_CAUSAL_GRAPH_LOOKBACK_DAYS", 30, low=1, high=365)
        while self.running:
            try:
                await asyncio.sleep(seconds_until_next_ist(hour, 30))
                if not self.running:
                    break
                await self._run_causal_graph_populate(lookback)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("causal_graph_populate_cron loop error: %s", exc)
                await asyncio.sleep(60)

    async def _run_causal_graph_populate(self, lookback_days: int) -> None:
        try:
            from services.causal.causal_graph import populate_from_learning_log

            org_ids = await asyncio.to_thread(distinct_active_organization_ids_sync)
            if not org_ids:
                org_ids = [None]  # type: ignore[list-item]
            added_total = 0
            for oid in org_ids:
                try:
                    res = await asyncio.to_thread(
                        populate_from_learning_log,
                        lookback_days=int(lookback_days),
                        organization_id=oid,
                    )
                    added_total += int((res or {}).get("added") or 0)
                except Exception as exc:
                    _log.debug("causal_graph_populate org=%s err=%s", oid, exc)
            log_structured(
                "causal_graph_populate_done",
                orgs=len(org_ids),
                added=added_total,
            )
        except Exception as exc:
            _log.warning("causal graph populate failed: %s", exc)

    async def feature_archive_daily_cron(self) -> None:
        """Self-Evolution Phase 2 — daily feature snapshot to ``feature_archive``.

        Default 01:00 IST. Disable with ``THIRAMAI_FEATURE_ARCHIVE_CRON=0``.
        Hour override: ``THIRAMAI_FEATURE_ARCHIVE_HOUR_IST`` (default 1).
        """
        if (os.getenv("THIRAMAI_FEATURE_ARCHIVE_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("feature_archive_daily_cron disabled via env")
            return
        try:
            hour = int((os.getenv("THIRAMAI_FEATURE_ARCHIVE_HOUR_IST") or "1").strip())
        except ValueError:
            hour = 1
        hour = max(0, min(23, hour))
        while self.running:
            try:
                await asyncio.sleep(seconds_until_next_ist(hour, 0))
                if not self.running:
                    break
                await self._run_feature_archive_daily()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("feature_archive_daily_cron loop error: %s", exc)
                await asyncio.sleep(60)

    async def _run_feature_archive_daily(self) -> None:
        try:
            from services.ml.feature_store import run_archive_for_all_orgs

            res = await asyncio.to_thread(run_archive_for_all_orgs)
            log_structured(
                "feature_archive_daily_done",
                orgs=int((res or {}).get("orgs") or 0),
                written=int((res or {}).get("written") or 0),
                errors=int((res or {}).get("errors") or 0),
            )
        except Exception as exc:
            _log.warning("feature archive daily failed: %s", exc)

    async def model_ensemble_train_cron(self) -> None:
        """Self-Evolution Phase 2 — weekly ensemble training (3-model).

        Default Saturday 03:30 IST. Disable with ``THIRAMAI_ENSEMBLE_TRAIN_CRON=0``.
        Day override: ``THIRAMAI_ENSEMBLE_TRAIN_DAY_IST`` (0=Mon … 6=Sun, default 5).
        Hour override: ``THIRAMAI_ENSEMBLE_TRAIN_HOUR_IST`` (default 3).
        """
        if (os.getenv("THIRAMAI_ENSEMBLE_TRAIN_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("model_ensemble_train_cron disabled via env")
            return
        try:
            target_day = int((os.getenv("THIRAMAI_ENSEMBLE_TRAIN_DAY_IST") or "5").strip())
        except ValueError:
            target_day = 5
        try:
            target_hour = int((os.getenv("THIRAMAI_ENSEMBLE_TRAIN_HOUR_IST") or "3").strip())
        except ValueError:
            target_hour = 3
        target_day = max(0, min(6, target_day))
        target_hour = max(0, min(23, target_hour))
        while self.running:
            try:
                await asyncio.sleep(_seconds_until_next_ist_weekday(target_day, target_hour, 30))
                if not self.running:
                    break
                await self._run_model_ensemble_train()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("model_ensemble_train_cron loop error: %s", exc)
                await asyncio.sleep(60)

    async def _run_model_ensemble_train(self) -> None:
        try:
            from services.ml.model_ensemble import train_ensemble

            org_ids = await asyncio.to_thread(distinct_active_organization_ids_sync)
            if not org_ids:
                org_ids = [None]  # type: ignore[list-item]
            ok_count = 0
            for oid in org_ids:
                try:
                    res = await asyncio.to_thread(train_ensemble, organization_id=oid, lookback_days=180, activate=True)
                    if bool((res or {}).get("ok")):
                        ok_count += 1
                except Exception as exc:
                    _log.debug("model_ensemble_train org=%s err=%s", oid, exc)
            log_structured(
                "model_ensemble_train_done",
                orgs=len(org_ids),
                trained_ok=ok_count,
            )
        except Exception as exc:
            _log.warning("model ensemble train failed: %s", exc)

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

    async def execution_watchdog_cron(self) -> None:
        """
        Every few minutes: detect stale execution runs and route them to closure authority.

        Env knobs:
        - ``THIRAMAI_EXECUTION_WATCHDOG_CRON`` (default 1)
        - ``THIRAMAI_EXECUTION_WATCHDOG_INTERVAL_MINUTES`` (default 5)
        - ``THIRAMAI_EXECUTION_RUNNING_TIMEOUT_MINUTES`` (default 15)
        - ``THIRAMAI_EXECUTION_AWAITING_TIMEOUT_MINUTES`` (default 30)
        - ``THIRAMAI_EXECUTION_WATCHDOG_COOLDOWN_MINUTES`` (default 5)
        """
        import os

        from services.execution_watchdog import run_execution_watchdog_scan, run_retry_job_drain

        interval_min = 5
        running_timeout_min = 15
        awaiting_timeout_min = 30
        cooldown_min = 5
        try:
            interval_min = max(1, int((os.getenv("THIRAMAI_EXECUTION_WATCHDOG_INTERVAL_MINUTES") or "5").strip()))
            running_timeout_min = max(1, int((os.getenv("THIRAMAI_EXECUTION_RUNNING_TIMEOUT_MINUTES") or "15").strip()))
            awaiting_timeout_min = max(1, int((os.getenv("THIRAMAI_EXECUTION_AWAITING_TIMEOUT_MINUTES") or "30").strip()))
            cooldown_min = max(1, int((os.getenv("THIRAMAI_EXECUTION_WATCHDOG_COOLDOWN_MINUTES") or "5").strip()))
        except Exception:
            interval_min = 5
            running_timeout_min = 15
            awaiting_timeout_min = 30
            cooldown_min = 5

        while self.running:
            try:
                if (os.getenv("THIRAMAI_EXECUTION_WATCHDOG_CRON") or "1").strip() == "0":
                    await asyncio.sleep(3600)
                    continue
                await asyncio.sleep(interval_min * 60)
                if not self.running:
                    break
                await self._refresh_guard()
                max_runs = _env_int("THIRAMAI_WATCHDOG_MAX_RUNS_PER_SCAN", 200, low=20, high=5000)
                if self._guard.get("degraded"):
                    max_runs = max(20, max_runs // 2)
                await asyncio.to_thread(
                    run_execution_watchdog_scan,
                    running_timeout_min=running_timeout_min,
                    awaiting_confirmation_timeout_min=awaiting_timeout_min,
                    cooldown_min=cooldown_min,
                    max_runs_per_scan=max_runs,
                )
                await asyncio.to_thread(run_retry_job_drain, max_runs=max_runs)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("execution_watchdog_cron error: %s", exc)
                await asyncio.sleep(30)

    async def opportunity_scan_cron(self) -> None:
        """Every 30 minutes: scan opportunities via async queue."""
        from services.async_task_queue import enqueue_task
        from services.opportunity_engine import scan_all_opportunities

        while self.running:
            try:
                await asyncio.sleep(1800)
                if not self.running:
                    break
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 120)
                for uid, oid in pairs:
                    if _user_kill_switch_active(int(uid)):
                        continue
                    queued = enqueue_task("opportunity_scan", {"user_id": uid, "organization_id": oid})
                    if not queued.get("queued"):
                        await asyncio.to_thread(scan_all_opportunities, uid, oid)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("opportunity_scan_cron error: %s", exc)
                await asyncio.sleep(60)

    async def learning_optimize_cron(self) -> None:
        """Hourly strategy optimization."""
        from services.async_task_queue import enqueue_task
        from services.learning_engine import update_strategy_profiles

        while self.running:
            try:
                await asyncio.sleep(3600)
                if not self.running:
                    break
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 200)
                seen_users: set[int] = set()
                for uid, _oid in pairs:
                    if _user_kill_switch_active(int(uid)):
                        continue
                    if uid in seen_users:
                        continue
                    seen_users.add(uid)
                    queued = enqueue_task("learning_optimize", {"user_id": uid})
                    if not queued.get("queued"):
                        await asyncio.to_thread(update_strategy_profiles, uid)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("learning_optimize_cron error: %s", exc)
                await asyncio.sleep(60)

    async def automation_scheduled_eval_cron(self) -> None:
        """Every 20 minutes: evaluate scheduled rules."""
        from services.async_task_queue import enqueue_task
        from services.automation_rule_engine import evaluate_rules

        while self.running:
            try:
                await asyncio.sleep(1200)
                if not self.running:
                    break
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 200)
                for uid, oid in pairs:
                    if _user_kill_switch_active(int(uid)):
                        continue
                    event = {
                        "user_id": uid,
                        "organization_id": oid,
                        "role_name": "owner",
                        "trigger_type": "scheduled_check",
                        "payload": {"source": "scheduler", "ts": _now_ist().isoformat()},
                    }
                    queued = enqueue_task("automation_evaluate", event)
                    if not queued.get("queued"):
                        await asyncio.to_thread(evaluate_rules, event)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("automation_scheduled_eval_cron error: %s", exc)
                await asyncio.sleep(60)

    async def money_loop_cron(self) -> None:
        """Every X minutes run continuous money loop cycle."""

        interval_min = 15
        try:
            import os

            interval_min = max(1, int((os.getenv("THIRAMAI_MONEY_LOOP_INTERVAL_MINUTES") or "15").strip()))
        except Exception:
            interval_min = 15

        while self.running:
            try:
                await asyncio.sleep(interval_min * 60)
                if not self.running:
                    break
                await self._refresh_guard()
                if bool(self._guard.get("blocked_autonomy")):
                    _log.warning("money_loop_cron shed: guard blocked autonomy reason=%s", self._guard.get("degraded_reason"))
                    continue
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 200)
                picked = self._load_shed_pairs(
                    "money_loop_cron",
                    [(uid, oid) for uid, oid in pairs if not _user_kill_switch_active(int(uid))],
                    high_priority_only=True,
                )
                max_concurrency = self._guarded_concurrency(_env_int("THIRAMAI_MONEY_LOOP_MAX_CONCURRENCY", 6, low=1, high=128))

                async def _worker(uid: int, oid: int) -> None:
                    await asyncio.to_thread(
                        _run_command_via_brain_sync,
                        int(uid),
                        int(oid),
                        "Run money loop cycle with governance and safety gates",
                    )

                await _run_bounded_pairs(picked, worker_coro=_worker, max_concurrency=max_concurrency)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("money_loop_cron error: %s", exc)
                await asyncio.sleep(60)

    async def goal_engine_cron(self) -> None:
        """Daily goal refresh and progress advance."""

        while self.running:
            try:
                await asyncio.sleep(6 * 3600)
                if not self.running:
                    break
                await self._refresh_guard()
                if bool(self._guard.get("blocked_autonomy")):
                    _log.warning("goal_engine_cron shed: guard blocked autonomy reason=%s", self._guard.get("degraded_reason"))
                    continue
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 200)
                picked = self._load_shed_pairs(
                    "goal_engine_cron",
                    [(uid, oid) for uid, oid in pairs if not _user_kill_switch_active(int(uid))],
                    high_priority_only=True,
                )
                max_concurrency = self._guarded_concurrency(_env_int("THIRAMAI_GOAL_ENGINE_MAX_CONCURRENCY", 6, low=1, high=128))

                async def _worker(uid: int, oid: int) -> None:
                    await asyncio.to_thread(
                        _run_command_via_brain_sync,
                        int(uid),
                        int(oid),
                        "Refresh strategic goals, snapshot weekly progress, and apply autonomy contract checks",
                    )

                await _run_bounded_pairs(picked, worker_coro=_worker, max_concurrency=max_concurrency)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("goal_engine_cron error: %s", exc)
                await asyncio.sleep(60)

    async def research_loop_cron(self) -> None:
        """Every 4 hours run baseline research-loop experiments."""

        while self.running:
            try:
                await asyncio.sleep(4 * 3600)
                if not self.running:
                    break
                await self._refresh_guard()
                if bool(self._guard.get("blocked_autonomy")):
                    _log.warning("research_loop_cron shed: guard blocked autonomy reason=%s", self._guard.get("degraded_reason"))
                    continue
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 120)
                picked = self._load_shed_pairs(
                    "research_loop_cron",
                    [(uid, oid) for uid, oid in pairs if not _user_kill_switch_active(int(uid))],
                    high_priority_only=False,
                )
                max_concurrency = self._guarded_concurrency(_env_int("THIRAMAI_RESEARCH_LOOP_MAX_CONCURRENCY", 5, low=1, high=128))

                async def _worker(uid: int, oid: int) -> None:
                    await asyncio.to_thread(
                        _run_command_via_brain_sync,
                        int(uid),
                        int(oid),
                        "Run research loop hypothesis experiment compare and promote update",
                    )

                await _run_bounded_pairs(picked, worker_coro=_worker, max_concurrency=max_concurrency)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("research_loop_cron error: %s", exc)
                await asyncio.sleep(60)

    async def brain_continuous_loop_cron(self) -> None:
        """
        Every 5 minutes: ``run_brain_cycle`` for each active user+organization pair.

        Respects global autonomy halt, per-user kill switch (guardrails), and governance
        inside ``run_brain_cycle`` (autonomy mode, ``validate_action``). Set
        ``THIRAMAI_BRAIN_CONTINUOUS_LOOP_CRON=0`` to disable.
        """
        import os

        from services.autonomy_safety_layer import global_autonomy_halted
        from services.continuous_brain_loop import run_brain_cycle
        base_concurrency = max(1, int((os.getenv("THIRAMAI_BRAIN_LOOP_MAX_CONCURRENCY") or "8").strip() or 8))

        while self.running:
            try:
                if (os.getenv("THIRAMAI_BRAIN_CONTINUOUS_LOOP_CRON") or "1").strip() == "0":
                    await asyncio.sleep(3600)
                    continue
                await asyncio.sleep(300)
                if not self.running:
                    break
                if global_autonomy_halted():
                    _log.info("brain_continuous_loop_cron: global autonomy halt; skipping tick")
                    continue
                await self._refresh_guard()
                if bool(self._guard.get("blocked_autonomy")):
                    _log.warning("brain_continuous_loop_cron blocked by guard: %s", self._guard.get("degraded_reason"))
                    continue
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 300)
                active_pairs = self._load_shed_pairs(
                    "brain_continuous_loop_cron",
                    [(int(uid), int(oid)) for uid, oid in pairs if not _user_kill_switch_active(int(uid))],
                    high_priority_only=True,
                )
                max_concurrency = self._guarded_concurrency(base_concurrency)

                async def _brain_worker(uid: int, oid: int) -> None:
                    if not self.running:
                        return
                    await asyncio.to_thread(run_brain_cycle, int(uid), int(oid))

                await _run_bounded_pairs(
                    active_pairs,
                    worker_coro=_brain_worker,
                    max_concurrency=max_concurrency,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                _log.warning("brain_continuous_loop_cron error: %s", exc)
                await asyncio.sleep(30)

    async def continuous_thinking_cron(self) -> None:
        """Every few minutes: think -> prioritize goals -> execute -> learn."""

        interval_min = 5
        try:
            import os

            interval_min = max(1, int((os.getenv("THIRAMAI_CONTINUOUS_THINKING_INTERVAL_MINUTES") or "5").strip()))
        except Exception:
            interval_min = 5

        while self.running:
            try:
                await asyncio.sleep(interval_min * 60)
                if not self.running:
                    break
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 200)
                for uid, oid in pairs:
                    if _user_kill_switch_active(int(uid)):
                        continue
                    await asyncio.to_thread(
                        _run_command_via_brain_sync,
                        int(uid),
                        int(oid),
                        "Run continuous thinking cycle for prioritization and learning",
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("continuous_thinking_cron error: %s", exc)
                await asyncio.sleep(30)

    async def strategic_intelligence_cron(self) -> None:
        """Periodic world-model refresh and strategy generation."""

        while self.running:
            try:
                await asyncio.sleep(30 * 60)
                if not self.running:
                    break
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 150)
                for uid, oid in pairs:
                    if _user_kill_switch_active(int(uid)):
                        continue
                    await asyncio.to_thread(
                        _run_command_via_brain_sync,
                        int(uid),
                        int(oid),
                        "Refresh world model and generate strategic promotion recommendations",
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("strategic_intelligence_cron error: %s", exc)
                await asyncio.sleep(30)

    async def domain_weekly_review_cron(self) -> None:
        """Weekly: domain P&L review, failures, improvements (per active user+org with domain profile enabled)."""
        import os

        from services.domain_dominion_engine import get_or_create_profile, run_weekly_domain_strategy_review

        while self.running:
            try:
                if (os.getenv("THIRAMAI_DOMAIN_WEEKLY_CRON") or "1").strip() == "0":
                    await asyncio.sleep(3600)
                    continue
                await asyncio.sleep(7 * 24 * 3600)
                if not self.running:
                    break
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 200)
                for uid, oid in pairs:
                    if _user_kill_switch_active(int(uid)):
                        continue
                    prof = await asyncio.to_thread(get_or_create_profile, int(uid), int(oid))
                    if not prof or not int(prof.get("id") or 0) or not prof.get("enabled", True):
                        continue
                    await asyncio.to_thread(run_weekly_domain_strategy_review, int(uid), int(oid))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("domain_weekly_review_cron error: %s", exc)
                await asyncio.sleep(60)

    async def continuity_loop_cron(self) -> None:
        """
        Every 5–10 min (``THIRAMAI_CONTINUITY_INTERVAL_MINUTES``, default 6):
        one continuity tick per active user+org (RQ when enabled, else inline thread).
        Set ``THIRAMAI_CONTINUITY_CRON=0`` to disable this loop. Per-tenant gating: ``continuity_user_settings.enabled``.
        """
        import os

        from services.async_task_queue import enqueue_task
        from services.autonomous_continuity_engine import run_continuity_tick

        interval_min = 6
        try:
            interval_min = max(1, int((os.getenv("THIRAMAI_CONTINUITY_INTERVAL_MINUTES") or "6").strip()))
        except Exception:
            interval_min = 6

        while self.running:
            try:
                if (os.getenv("THIRAMAI_CONTINUITY_CRON") or "1").strip() == "0":
                    await asyncio.sleep(3600)
                    continue
                await asyncio.sleep(max(1, interval_min) * 60)
                if not self.running:
                    break
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 200)
                for uid, oid in pairs:
                    if _user_kill_switch_active(int(uid)):
                        continue
                    pl = {
                        "user_id": int(uid),
                        "organization_id": int(oid),
                        "role_name": "owner",
                    }
                    queued = enqueue_task("continuity_tick", pl)
                    if not queued.get("queued"):
                        await asyncio.to_thread(
                            _run_command_via_brain_sync,
                            int(uid),
                            int(oid),
                            "Run continuity tick for autonomous continuity engine",
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("continuity_loop_cron error: %s", exc)
                await asyncio.sleep(30)

    async def autonomous_operations_cron(self) -> None:
        """Run daily business operations with minimal human dependency."""
        from services.multi_org_control_engine import list_user_organizations

        while self.running:
            try:
                await asyncio.sleep(24 * 3600)
                if not self.running:
                    break
                pairs = await asyncio.to_thread(distinct_active_user_org_pairs_sync, 200)
                # Reduce duplicate user runs; each user handles all org lanes via multi-org engine.
                users = sorted({int(uid) for uid, _ in pairs})
                for uid in users:
                    if _user_kill_switch_active(int(uid)):
                        continue
                    orgs = await asyncio.to_thread(list_user_organizations, uid)
                    for org in orgs:
                        oid = int(org.get("organization_id") or 0)
                        if oid <= 0 or bool(org.get("is_disabled")):
                            continue
                        await asyncio.to_thread(
                            _run_command_via_brain_sync,
                            int(uid),
                            int(oid),
                            "Run daily autonomous business operations cycle",
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("autonomous_operations_cron error: %s", exc)
                await asyncio.sleep(60)

    async def ohlcv_daily_fetch_cron(self) -> None:
        """Self-Evolution 90/100 — daily OHLCV pull after market close (16:30 IST).

        Disable with ``THIRAMAI_OHLCV_CRON=0``. Override hour/minute with
        ``THIRAMAI_OHLCV_HOUR_IST`` (default 16) / ``THIRAMAI_OHLCV_MINUTE_IST`` (default 30).
        Silently degrades when Kite credentials are not configured — the worker logs and
        continues sleeping until the next IST window.
        """
        if (os.getenv("THIRAMAI_OHLCV_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("ohlcv_daily_fetch_cron disabled via env")
            return
        try:
            hour = int((os.getenv("THIRAMAI_OHLCV_HOUR_IST") or "16").strip())
        except ValueError:
            hour = 16
        try:
            minute = int((os.getenv("THIRAMAI_OHLCV_MINUTE_IST") or "30").strip())
        except ValueError:
            minute = 30
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        while self.running:
            try:
                await asyncio.sleep(seconds_until_next_ist(hour, minute))
                if not self.running:
                    break
                await self._run_ohlcv_daily_fetch()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("ohlcv_daily_fetch_cron error: %s", exc)
                await asyncio.sleep(60)

    async def _run_ohlcv_daily_fetch(self) -> None:
        try:
            from services.quant.ohlcv_store import fetch_and_store_ohlcv, get_default_symbols

            symbols = get_default_symbols()
            ok = 0
            stored = 0
            for sym in symbols:
                try:
                    res = await asyncio.to_thread(fetch_and_store_ohlcv, sym, "day", 1)
                    if res.get("ok"):
                        ok += 1
                        stored += int(res.get("stored") or 0)
                except Exception as exc:
                    _log.debug("ohlcv_fetch sym=%s err=%s", sym, exc)
            log_structured(
                "ohlcv_daily_fetch_done",
                symbols=len(symbols),
                ok=ok,
                stored=stored,
            )
        except Exception as exc:
            _log.warning("ohlcv_cron_error: %s", exc)

    async def hal_state_snapshot_cron(self) -> None:
        """Self-Evolution 90/100 — every N minutes log a HAL device state snapshot.

        Disable with ``THIRAMAI_HAL_CRON=0``. Override cadence with
        ``THIRAMAI_HAL_INTERVAL_MIN`` (default 5).
        """
        if (os.getenv("THIRAMAI_HAL_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("hal_state_snapshot_cron disabled via env")
            return
        interval_min = max(1, _env_int("THIRAMAI_HAL_INTERVAL_MIN", 5, low=1, high=240))
        # Light initial offset so HAL doesn't fight registration on startup.
        await asyncio.sleep(30)
        while self.running:
            try:
                await self._run_hal_state_snapshot()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("hal_cron_error: %s", exc)
            try:
                await asyncio.sleep(interval_min * 60)
            except asyncio.CancelledError:
                break

    async def _run_hal_state_snapshot(self) -> None:
        try:
            from services.hal.hal_base import DeviceRegistry

            states = await asyncio.to_thread(DeviceRegistry.read_all_states)
            log_structured(
                "hal_snapshot",
                devices=len(states),
                connected=sum(
                    1 for s in states.values() if isinstance(s, dict) and s.get("connected")
                ),
            )
        except Exception as exc:
            _log.warning("hal snapshot run failed: %s", exc)

    async def paper_trading_cron(self) -> None:
        """Self-Evolution 95/100 — every N minutes during NSE hours, run the paper trader.

        Disabled by default; enable with ``THIRAMAI_PAPER_TRADING=1``. Override
        cadence with ``THIRAMAI_PAPER_TRADING_INTERVAL_MIN`` (default 15).
        """
        interval_min = max(1, _env_int("THIRAMAI_PAPER_TRADING_INTERVAL_MIN", 15, low=1, high=240))
        await asyncio.sleep(min(60, interval_min * 60 // 4))
        while self.running:
            try:
                if (os.getenv("THIRAMAI_PAPER_TRADING") or "0").strip() not in ("0", "false", "off", "no"):
                    await self._run_paper_trading_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("paper_trading_cron_error: %s", exc)
            try:
                await asyncio.sleep(interval_min * 60)
            except asyncio.CancelledError:
                break

    async def _run_paper_trading_cycle(self) -> None:
        try:
            from services.quant.paper_trader import PaperTrader

            pt = PaperTrader()
            result = await asyncio.to_thread(pt.auto_run_strategy)
            log_structured(
                "paper_trading_cron",
                ok=bool(result.get("ok")),
                orders_placed=int(result.get("orders_placed") or 0),
                message=str(result.get("message") or ""),
            )
        except Exception as exc:
            _log.warning("paper_trading run failed: %s", exc)

    async def weekly_backtest_cron(self) -> None:
        """Self-Evolution 95/100 — Sunday 02:00 IST, refresh OHLCV via yfinance.

        Disable with ``THIRAMAI_WEEKLY_BACKTEST_CRON=0``. Day/hour overrides:
        ``THIRAMAI_WEEKLY_BACKTEST_DAY_IST`` (0=Mon … 6=Sun, default 6),
        ``THIRAMAI_WEEKLY_BACKTEST_HOUR_IST`` (default 2).
        """
        if (os.getenv("THIRAMAI_WEEKLY_BACKTEST_CRON") or "1").strip() in ("0", "false", "off", "no"):
            _log.info("weekly_backtest_cron disabled via env")
            return
        try:
            target_day = int((os.getenv("THIRAMAI_WEEKLY_BACKTEST_DAY_IST") or "6").strip())
        except ValueError:
            target_day = 6
        try:
            target_hour = int((os.getenv("THIRAMAI_WEEKLY_BACKTEST_HOUR_IST") or "2").strip())
        except ValueError:
            target_hour = 2
        target_day = max(0, min(6, target_day))
        target_hour = max(0, min(23, target_hour))
        while self.running:
            try:
                await asyncio.sleep(_seconds_until_next_ist_weekday(target_day, target_hour))
                if not self.running:
                    break
                await self._run_weekly_backtest_refresh()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.warning("weekly_backtest_cron error: %s", exc)
                await asyncio.sleep(60)

    async def _run_weekly_backtest_refresh(self) -> None:
        try:
            from services.quant.ohlcv_store import fetch_default_symbols_yfinance

            res = await asyncio.to_thread(fetch_default_symbols_yfinance)
            log_structured(
                "weekly_ohlcv_refresh",
                ok=bool(res.get("ok")),
                total=int(res.get("total") or 0),
                stored_total=int(res.get("stored_total") or 0),
            )
        except Exception as exc:
            _log.warning("weekly_backtest_refresh failed: %s", exc)
