"""
Self-Evolution Phase 2: Causal Graph.

Builds and queries a directed graph of ``cause_variable → effect_variable``
edges where each edge stores the **running mean and variance** of observed
strengths (signed effect magnitudes). Edges are persisted in ``causal_edges``
so multiple processes can update the graph concurrently without rebuilding
from raw history every time.

The implementation is intentionally simple — it is *not* a full do-calculus
causal engine. It approximates causal influence using observational
correlation strength, weighted by the number of observations. This is enough
to surface "strongest levers" and answer counterfactual *estimates* of the form
"if I increase X by Δ, the average historical effect on Y was strength·Δ".

Public API
----------
- ``CausalGraph.add_observation(cause, effect, strength, *, organization_id=None, evidence=None)``
- ``CausalGraph.query_causes(effect, ..., min_observations=1, top_k=20) -> list[dict]``
- ``CausalGraph.query_effects(cause, ..., min_observations=1, top_k=20) -> list[dict]``
- ``CausalGraph.counterfactual(cause, value, ..., effect=None) -> dict``
- ``CausalGraph.get_strongest_levers(*, organization_id=None, top_k=10) -> list[dict]``

Bulk ingestion
--------------
- ``populate_from_learning_log(lookback_days=30, organization_id=None) -> dict``

This walks recent ``LearningLog`` rows and turns them into observations such
as:
    "When I increased inventory → revenue +X%"
    "When energy was low → decisions worse"
    "When market volatile → trading losses"
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select

_LOG = logging.getLogger(__name__)

# Cause/effect "vocab" — keep these stable, they are used as DB keys.
CAUSE_INVENTORY_INCREASED = "inventory_increased"
CAUSE_INVENTORY_DECREASED = "inventory_decreased"
CAUSE_ENERGY_LOW = "energy_low"
CAUSE_ENERGY_HIGH = "energy_high"
CAUSE_MARKET_VOLATILE = "market_volatile"
CAUSE_MARKET_CALM = "market_calm"
CAUSE_MEETING_HEAVY_DAY = "meeting_heavy_day"
CAUSE_FOCUS_DEEP = "focus_deep"
CAUSE_LOW_CASH = "low_cash"

EFFECT_REVENUE = "revenue"
EFFECT_DECISION_QUALITY = "decision_quality"
EFFECT_TRADING_PNL = "trading_pnl"
EFFECT_INVENTORY_TURNOVER = "inventory_turnover"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _factory_or_none():
    try:
        from core.database import get_session_factory

        return get_session_factory()
    except Exception as exc:
        _LOG.debug("causal_graph session factory unavailable: %s", exc)
        return None


def _confidence_from_running_stats(
    n: int, sum_x: float, sum_x2: float
) -> tuple[float, float]:
    """Return ``(mean, confidence)`` for the running stats.

    ``confidence`` is bounded to [0, 1]:
        confidence = (1 / (1 + stddev)) * tanh(n / 10)
    so a single observation with stddev=0 yields ~0.10 confidence and 30
    observations with stddev=0 yield ~1.0 (saturated).
    """
    if n <= 0:
        return 0.0, 0.0
    mean = sum_x / float(n)
    if n == 1:
        var = 0.0
    else:
        var = max(0.0, (sum_x2 / float(n)) - (mean * mean))
    stddev = math.sqrt(var)
    sample_strength = math.tanh(float(n) / 10.0)
    base_conf = 1.0 / (1.0 + stddev)
    return mean, max(0.0, min(1.0, base_conf * sample_strength))


class CausalGraph:
    """Directed cause→effect graph backed by ``causal_edges``."""

    def __init__(self, organization_id: int | None = None) -> None:
        self.organization_id = organization_id

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_observation(
        self,
        cause: str,
        effect: str,
        strength: float,
        *,
        organization_id: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> bool:
        """
        Add a single ``(cause → effect)`` observation with signed strength.

        ``strength`` is the standardised effect magnitude (e.g. percentage
        change). Positive = effect increased; negative = effect decreased.
        """
        cause_key = str(cause or "").strip()[:128]
        effect_key = str(effect or "").strip()[:128]
        if not cause_key or not effect_key:
            return False
        try:
            s = float(strength)
        except Exception:
            return False
        if math.isnan(s) or math.isinf(s):
            return False

        org_id = organization_id if organization_id is not None else self.organization_id
        factory = _factory_or_none()
        if factory is None:
            return False

        from core.db.models import CausalEdge

        with factory() as session:
            stmt = select(CausalEdge).where(
                CausalEdge.cause_variable == cause_key,
                CausalEdge.effect_variable == effect_key,
            )
            if org_id is None:
                stmt = stmt.where(CausalEdge.organization_id.is_(None))
            else:
                stmt = stmt.where(CausalEdge.organization_id == int(org_id))
            existing: CausalEdge | None = session.execute(stmt).scalar_one_or_none()

            if existing is None:
                row = CausalEdge(
                    organization_id=int(org_id) if org_id is not None else None,
                    cause_variable=cause_key,
                    effect_variable=effect_key,
                    sum_strength=s,
                    sum_strength_sq=s * s,
                    observation_count=1,
                    strength=s,
                    confidence=_confidence_from_running_stats(1, s, s * s)[1],
                    evidence_payload=dict(evidence or {}),
                    last_updated=_now(),
                )
                session.add(row)
            else:
                n = int(existing.observation_count or 0) + 1
                sum_x = float(existing.sum_strength or 0.0) + s
                sum_x2 = float(existing.sum_strength_sq or 0.0) + s * s
                mean, conf = _confidence_from_running_stats(n, sum_x, sum_x2)
                existing.sum_strength = sum_x
                existing.sum_strength_sq = sum_x2
                existing.observation_count = n
                existing.strength = round(mean, 6)
                existing.confidence = round(conf, 6)
                existing.last_updated = _now()
                if evidence:
                    payload = dict(existing.evidence_payload or {})
                    samples = list(payload.get("samples") or [])
                    if len(samples) < 5:
                        samples.append(evidence)
                        payload["samples"] = samples
                    existing.evidence_payload = payload
            try:
                session.commit()
                return True
            except Exception as exc:
                _LOG.warning("causal add_observation commit failed: %s", exc)
                session.rollback()
                return False

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _serialize(self, row: Any) -> dict[str, Any]:
        return {
            "cause": row.cause_variable,
            "effect": row.effect_variable,
            "strength": float(row.strength or 0.0),
            "confidence": float(row.confidence or 0.0),
            "observation_count": int(row.observation_count or 0),
            "organization_id": row.organization_id,
            "last_updated": row.last_updated.isoformat() if row.last_updated else None,
        }

    def query_causes(
        self,
        effect: str,
        *,
        organization_id: int | None = None,
        min_observations: int = 1,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """Causes most strongly explaining ``effect``, ranked by |strength|·confidence."""
        factory = _factory_or_none()
        if factory is None:
            return []
        org_id = organization_id if organization_id is not None else self.organization_id
        from core.db.models import CausalEdge

        with factory() as session:
            stmt = select(CausalEdge).where(
                CausalEdge.effect_variable == str(effect)[:128],
                CausalEdge.observation_count >= max(1, int(min_observations)),
            )
            if org_id is not None:
                stmt = stmt.where(CausalEdge.organization_id == int(org_id))
            rows = list(session.execute(stmt).scalars().all())
        ranked = sorted(
            rows,
            key=lambda r: abs(float(r.strength or 0.0)) * float(r.confidence or 0.0),
            reverse=True,
        )
        return [self._serialize(r) for r in ranked[: max(1, int(top_k))]]

    def query_effects(
        self,
        cause: str,
        *,
        organization_id: int | None = None,
        min_observations: int = 1,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """Effects most strongly produced by ``cause``."""
        factory = _factory_or_none()
        if factory is None:
            return []
        org_id = organization_id if organization_id is not None else self.organization_id
        from core.db.models import CausalEdge

        with factory() as session:
            stmt = select(CausalEdge).where(
                CausalEdge.cause_variable == str(cause)[:128],
                CausalEdge.observation_count >= max(1, int(min_observations)),
            )
            if org_id is not None:
                stmt = stmt.where(CausalEdge.organization_id == int(org_id))
            rows = list(session.execute(stmt).scalars().all())
        ranked = sorted(
            rows,
            key=lambda r: abs(float(r.strength or 0.0)) * float(r.confidence or 0.0),
            reverse=True,
        )
        return [self._serialize(r) for r in ranked[: max(1, int(top_k))]]

    def counterfactual(
        self,
        cause: str,
        value: float,
        *,
        effect: str | None = None,
        organization_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Estimate the effect on each effect-variable of setting ``cause`` to
        ``value`` (interpreted as a delta in cause-units). Returns:

        ``{"cause": ..., "value": ..., "predictions": [{"effect": ...,
            "estimated_delta": strength * value, "confidence": ..., ...}, ...]}``
        """
        try:
            v = float(value)
        except Exception:
            v = 0.0
        all_effects = self.query_effects(
            cause, organization_id=organization_id, min_observations=1, top_k=50
        )
        if effect is not None:
            all_effects = [e for e in all_effects if e["effect"] == str(effect)]
        predictions = []
        for e in all_effects:
            est = float(e["strength"]) * v
            predictions.append(
                {
                    "effect": e["effect"],
                    "estimated_delta": round(est, 6),
                    "strength": e["strength"],
                    "confidence": e["confidence"],
                    "observation_count": e["observation_count"],
                }
            )
        return {
            "cause": cause,
            "value": v,
            "scope_organization_id": organization_id
            if organization_id is not None
            else self.organization_id,
            "predictions": predictions,
        }

    def get_strongest_levers(
        self,
        *,
        organization_id: int | None = None,
        top_k: int = 10,
        min_observations: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Return the highest |strength|·confidence edges across the whole graph
        (filtered to ``min_observations``+ samples). These are the actions /
        conditions that historically moved outcomes the most.
        """
        factory = _factory_or_none()
        if factory is None:
            return []
        org_id = organization_id if organization_id is not None else self.organization_id
        from core.db.models import CausalEdge

        with factory() as session:
            stmt = select(CausalEdge).where(
                CausalEdge.observation_count >= max(1, int(min_observations))
            )
            if org_id is not None:
                stmt = stmt.where(CausalEdge.organization_id == int(org_id))
            rows = list(session.execute(stmt).scalars().all())
        ranked = sorted(
            rows,
            key=lambda r: abs(float(r.strength or 0.0)) * float(r.confidence or 0.0),
            reverse=True,
        )
        return [self._serialize(r) for r in ranked[: max(1, int(top_k))]]


# ---------------------------------------------------------------------------
# Bulk ingestion from LearningLog
# ---------------------------------------------------------------------------


def _pair_from_log(row: Any) -> tuple[str, str, float] | None:
    """Translate a ``LearningLog`` row into a (cause, effect, strength) triple.

    Heuristic: matches on action_type / outcome / context keywords. Returns
    ``None`` when no clear pair can be derived.
    """
    action = str(getattr(row, "action_type", "") or "").lower()
    outcome = str(getattr(row, "outcome", "") or "").lower()
    success = bool(getattr(row, "success", False) or outcome in ("success", "ok", "applied", "approved"))
    ctx = getattr(row, "context", None) or {}
    if not isinstance(ctx, dict):
        ctx = {}

    sign = 1.0 if success else -1.0
    magnitude = abs(float(ctx.get("delta_pct") or ctx.get("change_pct") or 0.0))
    if magnitude <= 0.0:
        magnitude = 5.0

    if "inventory" in action and ("increase" in action or "restock" in action or "po" in action):
        return CAUSE_INVENTORY_INCREASED, EFFECT_REVENUE, sign * magnitude
    if "inventory" in action and ("decrease" in action or "stockout" in action):
        return CAUSE_INVENTORY_DECREASED, EFFECT_REVENUE, sign * magnitude

    if "decision" in action or "approval" in action or "council" in action:
        if (ctx.get("energy_score") or 0) and float(ctx.get("energy_score")) < 0.4:
            return CAUSE_ENERGY_LOW, EFFECT_DECISION_QUALITY, -magnitude
        return CAUSE_FOCUS_DEEP, EFFECT_DECISION_QUALITY, sign * magnitude

    if "trade" in action or "trading" in action or "intraday" in action or "swing" in action:
        if (ctx.get("volatility") or 0) and float(ctx.get("volatility")) > 0.02:
            return CAUSE_MARKET_VOLATILE, EFFECT_TRADING_PNL, sign * magnitude
        return CAUSE_MARKET_CALM, EFFECT_TRADING_PNL, sign * magnitude

    if "meeting" in action and ((ctx.get("meeting_count") or 0) >= 3):
        return CAUSE_MEETING_HEAVY_DAY, EFFECT_DECISION_QUALITY, -magnitude

    return None


def populate_from_learning_log(
    *,
    lookback_days: int = 30,
    organization_id: int | None = None,
    limit: int = 5000,
) -> dict[str, int]:
    """
    Walk recent ``LearningLog`` rows and add observations to ``causal_edges``.
    Idempotency-safe: each call appends new observations (running stats handle
    re-runs gracefully but you should not feed the same row twice — call this
    job nightly with a fresh ``lookback_days`` window).

    Returns ``{"scanned": N, "added": K, "skipped": S}``.
    """
    factory = _factory_or_none()
    if factory is None:
        return {"scanned": 0, "added": 0, "skipped": 0}
    from core.db.models import LearningLog

    since = _now() - timedelta(days=max(1, int(lookback_days)))
    graph = CausalGraph(organization_id=organization_id)
    added = 0
    scanned = 0
    skipped = 0
    with factory() as session:
        stmt = (
            select(LearningLog)
            .where(LearningLog.created_at >= since)
            .order_by(LearningLog.created_at.desc())
            .limit(int(limit))
        )
        if organization_id is not None:
            stmt = stmt.where(LearningLog.organization_id == int(organization_id))
        rows: list[LearningLog] = list(session.execute(stmt).scalars().all())

    for row in rows:
        scanned += 1
        triple = _pair_from_log(row)
        if triple is None:
            skipped += 1
            continue
        cause, effect, strength = triple
        if graph.add_observation(
            cause,
            effect,
            strength,
            organization_id=organization_id,
            evidence={
                "learning_log_id": getattr(row, "id", None),
                "action_type": getattr(row, "action_type", None),
                "outcome": getattr(row, "outcome", None),
            },
        ):
            added += 1
        else:
            skipped += 1
    return {"scanned": scanned, "added": added, "skipped": skipped}


__all__ = [
    "CAUSE_ENERGY_HIGH",
    "CAUSE_ENERGY_LOW",
    "CAUSE_FOCUS_DEEP",
    "CAUSE_INVENTORY_DECREASED",
    "CAUSE_INVENTORY_INCREASED",
    "CAUSE_LOW_CASH",
    "CAUSE_MARKET_CALM",
    "CAUSE_MARKET_VOLATILE",
    "CAUSE_MEETING_HEAVY_DAY",
    "CausalGraph",
    "EFFECT_DECISION_QUALITY",
    "EFFECT_INVENTORY_TURNOVER",
    "EFFECT_REVENUE",
    "EFFECT_TRADING_PNL",
    "populate_from_learning_log",
]
