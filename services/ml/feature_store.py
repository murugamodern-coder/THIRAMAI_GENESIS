"""
Self-Evolution Phase 2: Feature Store.

Computes a small, well-defined set of ML features per scope and caches them in
Redis (TTL 1h, falling back to in-process memory when Redis is unavailable).
A daily archive job writes the same features into ``feature_archive`` for
historical training data.

Scopes
------
- ``business``  : revenue_7d_trend, inventory_turnover_rate, cash_position,
                  active_suppliers_count
- ``trading``   : market_regime, volatility_30d, portfolio_exposure
- ``personal``  : founder_energy_score, meeting_load, focus_hours_yesterday

Public API
----------
- ``compute_features(scope, organization_id=None, user_id=None) -> dict``
- ``get_or_compute(scope, organization_id=None, user_id=None, ttl_sec=3600) -> dict``
- ``archive_daily(scopes=..., organization_id=None, user_id=None) -> dict``
- ``run_archive_for_all_orgs() -> dict``

Every function is **defensive** — it never raises on missing tables, missing
Redis, or missing optional dependencies. It always returns a dict with the
documented keys (values may be ``None``/``0.0`` when data is unavailable).
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from sqlalchemy import func, select

_LOG = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "thiramai:fs:"
DEFAULT_TTL_SEC = 3600

SCOPE_BUSINESS = "business"
SCOPE_TRADING = "trading"
SCOPE_PERSONAL = "personal"
ALL_SCOPES = (SCOPE_BUSINESS, SCOPE_TRADING, SCOPE_PERSONAL)

BUSINESS_FEATURES: tuple[str, ...] = (
    "revenue_7d_trend",
    "inventory_turnover_rate",
    "cash_position",
    "active_suppliers_count",
)
TRADING_FEATURES: tuple[str, ...] = (
    "market_regime",
    "volatility_30d",
    "portfolio_exposure",
)
PERSONAL_FEATURES: tuple[str, ...] = (
    "founder_energy_score",
    "meeting_load",
    "focus_hours_yesterday",
)
FEATURES_BY_SCOPE: dict[str, tuple[str, ...]] = {
    SCOPE_BUSINESS: BUSINESS_FEATURES,
    SCOPE_TRADING: TRADING_FEATURES,
    SCOPE_PERSONAL: PERSONAL_FEATURES,
}


# ---------------------------------------------------------------------------
# Redis + in-process fallback
# ---------------------------------------------------------------------------

_MEM: dict[str, tuple[float, str]] = {}
_MEM_LOCK = threading.Lock()


def _redis():
    """Return the shared sync Redis client or ``None``."""
    try:
        from services.worker_heartbeat import redis_client

        return redis_client()
    except Exception as exc:  # pragma: no cover - dependency optional
        _LOG.debug("feature_store redis unavailable: %s", exc)
        return None


def _cache_key(scope: str, organization_id: int | None, user_id: int | None) -> str:
    org = "0" if organization_id is None else str(int(organization_id))
    usr = "0" if user_id is None else str(int(user_id))
    return f"{REDIS_KEY_PREFIX}{scope}:{org}:{usr}"


def _cache_get(key: str) -> dict[str, Any] | None:
    r = _redis()
    if r is not None:
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            _LOG.debug("feature_store redis get failed key=%s err=%s", key[:80], exc)
    with _MEM_LOCK:
        hit = _MEM.get(key)
        if hit and time.monotonic() - hit[0] < hit_ttl_seconds():
            try:
                return json.loads(hit[1])
            except Exception:
                return None
    return None


def _cache_set(key: str, payload: dict[str, Any], ttl_sec: int) -> None:
    blob = json.dumps(payload, default=str)
    r = _redis()
    if r is not None:
        try:
            r.setex(key, max(1, int(ttl_sec)), blob)
            return
        except Exception as exc:
            _LOG.debug("feature_store redis set failed: %s", exc)
    with _MEM_LOCK:
        _MEM[key] = (time.monotonic(), blob)
        if len(_MEM) > 2000:
            cutoff = time.monotonic() - float(ttl_sec)
            for k in list(_MEM.keys())[:500]:
                if _MEM.get(k, (0,))[0] < cutoff:
                    _MEM.pop(k, None)


def hit_ttl_seconds() -> int:
    """In-process fallback TTL (matches Redis TTL by default)."""
    try:
        return max(60, int(os.getenv("THIRAMAI_FS_MEM_TTL_SEC") or DEFAULT_TTL_SEC))
    except ValueError:
        return DEFAULT_TTL_SEC


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


def _factory_or_none():
    try:
        from core.database import get_session_factory

        return get_session_factory()
    except Exception as exc:
        _LOG.debug("feature_store session factory unavailable: %s", exc)
        return None


def _safe(fn: Callable[[Any], float | None]) -> Callable[[Any], float | None]:
    """Wrap a feature computer so it returns ``None`` on any error."""

    def wrapper(*args: Any, **kwargs: Any) -> float | None:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            _LOG.debug("feature compute %s failed: %s", getattr(fn, "__name__", "?"), exc)
            return None

    wrapper.__name__ = getattr(fn, "__name__", "wrapped")
    return wrapper


# ---------------------------------------------------------------------------
# Business features
# ---------------------------------------------------------------------------


@_safe
def _f_revenue_7d_trend(session: Any, organization_id: int | None) -> float | None:
    """
    Slope-ish trend of last 7d revenue vs preceding 7d revenue.

    Returns a unitless ratio: ``(this_week / max(prev_week, 1)) - 1``. Positive
    = growing, negative = shrinking, ``0.0`` = flat / no signal.
    """
    if organization_id is None:
        return 0.0
    from core.db.models import Invoice

    today = datetime.now(timezone.utc).date()
    week_ago = today - timedelta(days=7)
    two_weeks_ago = today - timedelta(days=14)

    def _sum(start: date, end: date) -> float:
        stmt = (
            select(func.coalesce(func.sum(Invoice.grand_total_inr), 0))
            .where(Invoice.organization_id == int(organization_id))
            .where(Invoice.invoice_date >= start)
            .where(Invoice.invoice_date < end)
        )
        return float(session.execute(stmt).scalar() or 0.0)

    this_week = _sum(week_ago, today)
    prev_week = _sum(two_weeks_ago, week_ago)
    if prev_week <= 0.0:
        return 0.0 if this_week <= 0.0 else 1.0
    return round((this_week / prev_week) - 1.0, 6)


@_safe
def _f_inventory_turnover_rate(session: Any, organization_id: int | None) -> float | None:
    """
    Turnover proxy: ``out_30d / max(avg_quantity, 1)``.

    Uses ``stock_movements.delta_qty`` (negative outflows) over the past 30 days
    against the current average ``inventory_items.quantity``.
    """
    if organization_id is None:
        return 0.0
    from core.db.models import InventoryItem, StockMovement

    avg_q_stmt = (
        select(func.coalesce(func.avg(InventoryItem.quantity), 0))
        .where(InventoryItem.organization_id == int(organization_id))
    )
    avg_q = float(session.execute(avg_q_stmt).scalar() or 0.0)

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    out_stmt = (
        select(func.coalesce(func.sum(func.abs(StockMovement.quantity_delta)), 0))
        .where(StockMovement.organization_id == int(organization_id))
        .where(StockMovement.created_at >= cutoff)
    )
    try:
        out_qty = float(session.execute(out_stmt).scalar() or 0.0)
    except Exception:
        out_qty = 0.0
    if avg_q <= 0.0:
        return 0.0
    return round(out_qty / max(avg_q, 1.0), 6)


@_safe
def _f_cash_position(session: Any, organization_id: int | None) -> float | None:
    """Cash + bank balance from ``organization_liquidity`` (₹)."""
    if organization_id is None:
        return 0.0
    from core.db.models import OrganizationLiquidity

    stmt = select(
        func.coalesce(OrganizationLiquidity.cash_inr, 0)
        + func.coalesce(OrganizationLiquidity.bank_inr, 0)
    ).where(OrganizationLiquidity.organization_id == int(organization_id))
    val = session.execute(stmt).scalar()
    return float(val or 0.0)


@_safe
def _f_active_suppliers_count(session: Any, organization_id: int | None) -> float | None:
    """Distinct suppliers seen on a purchase order in the last 90 days."""
    if organization_id is None:
        return 0.0
    from core.db.models import PurchaseOrder

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    stmt = (
        select(func.count(func.distinct(PurchaseOrder.supplier_id)))
        .where(PurchaseOrder.organization_id == int(organization_id))
        .where(PurchaseOrder.created_at >= cutoff)
    )
    try:
        return float(session.execute(stmt).scalar() or 0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Trading features
# ---------------------------------------------------------------------------


def _live_regime_and_vol() -> tuple[float | None, float | None]:
    """
    Pull the most recent NIFTY-50 close history (or whatever the stock service
    exposes) to derive a regime score and 30d stddev. Both return ``None`` if
    no live price source is configured — callers must treat that as "unknown".
    """
    closes: list[float] = []
    try:
        from services.stock_market_service import (  # type: ignore[attr-defined]
            fetch_recent_closes,
        )

        closes = list(fetch_recent_closes("^NSEI", days=30) or [])
    except Exception:
        closes = []
    if len(closes) < 5:
        return None, None
    pct: list[float] = []
    for prev, cur in zip(closes[:-1], closes[1:]):
        try:
            if float(prev) > 0:
                pct.append((float(cur) - float(prev)) / float(prev) * 100.0)
        except Exception:
            continue
    if not pct:
        return None, None
    avg = sum(pct) / len(pct)
    if avg > 0.3:
        regime = 1.0
    elif avg < -0.3:
        regime = -1.0
    else:
        regime = round(max(-1.0, min(1.0, avg / 0.3)), 4)
    try:
        vol = float(statistics.pstdev(pct))
    except statistics.StatisticsError:
        vol = 0.0
    return regime, round(vol, 6)


@_safe
def _f_market_regime(session: Any, organization_id: int | None) -> float | None:
    """Regime score in [-1.0, +1.0] (+1 bull, 0 sideways, -1 bear).

    Returns ``0.0`` (sideways/unknown) when no live price source is wired in.
    """
    regime, _ = _live_regime_and_vol()
    return 0.0 if regime is None else regime


@_safe
def _f_volatility_30d(session: Any, organization_id: int | None) -> float | None:
    """Stddev of last-30-days daily percent change. ``0.0`` if no source."""
    _, vol = _live_regime_and_vol()
    return 0.0 if vol is None else vol


@_safe
def _f_portfolio_exposure(session: Any, organization_id: int | None) -> float | None:
    """Total notional of ``equity_portfolio_positions`` at average buy price (₹)."""
    try:
        from core.db.models import EquityPortfolioPosition
    except Exception:
        return 0.0
    try:
        stmt = select(
            func.coalesce(
                func.sum(
                    EquityPortfolioPosition.quantity
                    * EquityPortfolioPosition.avg_buy_price_inr
                ),
                0,
            )
        )
        return float(session.execute(stmt).scalar() or 0.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Personal features
# ---------------------------------------------------------------------------


@_safe
def _f_founder_energy_score(session: Any, user_id: int | None) -> float | None:
    """
    Heuristic energy proxy in [0, 1]:
        ``completed_habits_7d / max(scheduled_habits_7d, 1)``.

    Falls back to ``0.5`` if no habit data exists (neutral).
    """
    if user_id is None:
        return 0.5
    try:
        from core.db.models import Habit, HabitLog
    except Exception:
        return 0.5
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    try:
        habits_stmt = (
            select(func.count(Habit.id)).where(Habit.user_id == int(user_id))
        )
        scheduled = float(session.execute(habits_stmt).scalar() or 0) * 7.0
    except Exception:
        scheduled = 0.0
    try:
        logs_stmt = (
            select(func.count(HabitLog.id))
            .join(Habit, Habit.id == HabitLog.habit_id)
            .where(Habit.user_id == int(user_id))
            .where(HabitLog.completed_at >= cutoff)
        )
        completed = float(session.execute(logs_stmt).scalar() or 0)
    except Exception:
        completed = 0.0
    if scheduled <= 0.0:
        return 0.5
    return round(min(1.0, completed / scheduled), 4)


@_safe
def _f_meeting_load(session: Any, user_id: int | None) -> float | None:
    """Number of scheduled meetings for the next 24h for ``user_id``."""
    if user_id is None:
        return 0.0
    from core.db.models import PersonalMeeting

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=24)
    stmt = (
        select(func.count(PersonalMeeting.id))
        .where(PersonalMeeting.user_id == int(user_id))
        .where(PersonalMeeting.scheduled_at >= now)
        .where(PersonalMeeting.scheduled_at < horizon)
        .where(PersonalMeeting.status == "scheduled")
    )
    return float(session.execute(stmt).scalar() or 0)


@_safe
def _f_focus_hours_yesterday(session: Any, user_id: int | None) -> float | None:
    """
    Focus-hour proxy: counts ``LearningLog`` rows attributed to ``user_id``
    yesterday × 0.5h each (capped at 12h). Falls back to ``0.0`` when no logs.
    """
    if user_id is None:
        return 0.0
    from core.db.models import LearningLog

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count(LearningLog.id))
        .where(LearningLog.user_id == int(user_id))
        .where(LearningLog.created_at >= start)
        .where(LearningLog.created_at < end)
    )
    n = int(session.execute(stmt).scalar() or 0)
    return round(min(12.0, n * 0.5), 2)


# ---------------------------------------------------------------------------
# Compute orchestrators
# ---------------------------------------------------------------------------


def _compute_business(session: Any, organization_id: int | None) -> dict[str, Any]:
    return {
        "revenue_7d_trend": _f_revenue_7d_trend(session, organization_id),
        "inventory_turnover_rate": _f_inventory_turnover_rate(session, organization_id),
        "cash_position": _f_cash_position(session, organization_id),
        "active_suppliers_count": _f_active_suppliers_count(session, organization_id),
    }


def _compute_trading(session: Any, organization_id: int | None) -> dict[str, Any]:
    return {
        "market_regime": _f_market_regime(session, organization_id),
        "volatility_30d": _f_volatility_30d(session, organization_id),
        "portfolio_exposure": _f_portfolio_exposure(session, organization_id),
    }


def _compute_personal(session: Any, user_id: int | None) -> dict[str, Any]:
    return {
        "founder_energy_score": _f_founder_energy_score(session, user_id),
        "meeting_load": _f_meeting_load(session, user_id),
        "focus_hours_yesterday": _f_focus_hours_yesterday(session, user_id),
    }


def _empty_features(scope: str) -> dict[str, Any]:
    return {name: None for name in FEATURES_BY_SCOPE.get(scope, ())}


def compute_features(
    scope: str,
    *,
    organization_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Compute features for ``scope`` directly from the database (no cache).

    Always returns a dict keyed by the feature names defined in
    ``FEATURES_BY_SCOPE[scope]``; values may be ``None`` if data is missing.
    """
    factory = _factory_or_none()
    if factory is None:
        return _empty_features(scope)
    if scope not in FEATURES_BY_SCOPE:
        return {}
    try:
        with factory() as session:
            if scope == SCOPE_BUSINESS:
                return _compute_business(session, organization_id)
            if scope == SCOPE_TRADING:
                return _compute_trading(session, organization_id)
            if scope == SCOPE_PERSONAL:
                return _compute_personal(session, user_id)
    except Exception as exc:
        _LOG.warning("feature_store.compute_features scope=%s failed: %s", scope, exc)
    return _empty_features(scope)


def get_or_compute(
    scope: str,
    *,
    organization_id: int | None = None,
    user_id: int | None = None,
    ttl_sec: int = DEFAULT_TTL_SEC,
) -> dict[str, Any]:
    """Cache-first variant of :func:`compute_features` (Redis 1h, mem fallback)."""
    if scope not in FEATURES_BY_SCOPE:
        return {}
    key = _cache_key(scope, organization_id, user_id)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    fresh = compute_features(scope, organization_id=organization_id, user_id=user_id)
    payload = {
        "scope": scope,
        "organization_id": organization_id,
        "user_id": user_id,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "features": fresh,
    }
    _cache_set(key, payload, ttl_sec)
    return payload


def invalidate(
    scope: str | None = None,
    *,
    organization_id: int | None = None,
    user_id: int | None = None,
) -> int:
    """Drop cached features for one or all scopes. Returns number of keys cleared."""
    keys: list[str] = []
    scopes = (scope,) if scope else ALL_SCOPES
    for s in scopes:
        keys.append(_cache_key(s, organization_id, user_id))
    cleared = 0
    r = _redis()
    if r is not None:
        for k in keys:
            try:
                cleared += int(r.delete(k) or 0)
            except Exception:
                continue
    with _MEM_LOCK:
        for k in keys:
            if _MEM.pop(k, None) is not None:
                cleared += 1
    return cleared


# ---------------------------------------------------------------------------
# Daily archive (idempotent per (org/user, scope, feature, date))
# ---------------------------------------------------------------------------


def archive_daily(
    *,
    organization_id: int | None = None,
    user_id: int | None = None,
    captured_date: date | None = None,
    scopes: Iterable[str] = ALL_SCOPES,
) -> dict[str, int]:
    """
    Persist today's features into ``feature_archive`` (idempotent per day).

    Returns ``{"written": N, "skipped": M, "errors": E}``.
    """
    factory = _factory_or_none()
    if factory is None:
        return {"written": 0, "skipped": 0, "errors": 1}
    if captured_date is None:
        captured_date = datetime.now(timezone.utc).date()

    from core.db.models import FeatureArchive

    written = 0
    skipped = 0
    errors = 0

    with factory() as session:
        for scope in scopes:
            if scope not in FEATURES_BY_SCOPE:
                continue
            payload = compute_features(
                scope, organization_id=organization_id, user_id=user_id
            )
            for feature_name, value in payload.items():
                try:
                    exists_stmt = select(FeatureArchive.id).where(
                        FeatureArchive.organization_id == organization_id,
                        FeatureArchive.scope == scope,
                        FeatureArchive.feature_name == feature_name,
                        FeatureArchive.captured_date == captured_date,
                    )
                    if session.execute(exists_stmt).scalar() is not None:
                        skipped += 1
                        continue
                    row = FeatureArchive(
                        organization_id=organization_id,
                        scope=scope,
                        feature_name=feature_name,
                        value=(float(value) if isinstance(value, (int, float)) else None),
                        payload={"user_id": user_id, "raw": value} if not isinstance(value, (int, float)) else {"user_id": user_id},
                        captured_date=captured_date,
                    )
                    session.add(row)
                    written += 1
                except Exception as exc:
                    errors += 1
                    _LOG.debug(
                        "feature_archive write failed scope=%s feature=%s err=%s",
                        scope,
                        feature_name,
                        exc,
                    )
        try:
            session.commit()
        except Exception as exc:
            errors += 1
            _LOG.warning("feature_archive commit failed: %s", exc)
            session.rollback()

    return {"written": written, "skipped": skipped, "errors": errors}


def run_archive_for_all_orgs(*, captured_date: date | None = None) -> dict[str, Any]:
    """
    Archive features for every active organization (business + trading) and a
    representative ``user_id`` per organization (the first owner). Designed for
    a daily scheduled job.
    """
    factory = _factory_or_none()
    if factory is None:
        return {"orgs": 0, "written": 0, "errors": 1}
    from core.db.models import Organization, UserOrganizationMembership

    summary = {"orgs": 0, "written": 0, "skipped": 0, "errors": 0}
    with factory() as session:
        org_ids: list[int] = list(session.execute(select(Organization.id)).scalars().all())
        for org_id in org_ids:
            summary["orgs"] += 1
            owner_stmt = (
                select(UserOrganizationMembership.user_id)
                .where(UserOrganizationMembership.organization_id == int(org_id))
                .order_by(UserOrganizationMembership.id.asc())
                .limit(1)
            )
            try:
                owner_id = session.execute(owner_stmt).scalar()
            except Exception:
                owner_id = None
            res = archive_daily(
                organization_id=int(org_id),
                user_id=int(owner_id) if owner_id else None,
                captured_date=captured_date,
                scopes=ALL_SCOPES,
            )
            summary["written"] += int(res.get("written", 0))
            summary["skipped"] += int(res.get("skipped", 0))
            summary["errors"] += int(res.get("errors", 0))
    return summary


__all__ = [
    "ALL_SCOPES",
    "BUSINESS_FEATURES",
    "DEFAULT_TTL_SEC",
    "FEATURES_BY_SCOPE",
    "PERSONAL_FEATURES",
    "REDIS_KEY_PREFIX",
    "SCOPE_BUSINESS",
    "SCOPE_PERSONAL",
    "SCOPE_TRADING",
    "TRADING_FEATURES",
    "archive_daily",
    "compute_features",
    "get_or_compute",
    "invalidate",
    "run_archive_for_all_orgs",
]
