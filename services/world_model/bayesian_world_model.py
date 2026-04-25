"""World Model v2 — Bayesian belief network — Self-Evolution Phase 4 Task 2.

This is the "given current state, what is the probability of each business
outcome" engine that supersedes the regime-label model in
:mod:`services.world_model_engine`.

Design at a glance:

- **State vector** of 52 named variables across business / trading / personal /
  system / macro / risk domains. See :data:`STATE_VARIABLES`.
- **Belief distribution** keeps a per-variable posterior:
  * ``continuous`` → Welford-style running ``(mean, variance, n)``
  * ``binary``     → Beta(``alpha``, ``beta``) with conjugate updates
  * ``categorical``→ Dirichlet ``counts`` per known category
- **Transition matrix** lives in :class:`~core.db.models.WorldTransitionEdge`.
  We hash the discretised state vector to a 12-char signature and increment a
  counter on every observation. Outcome aggregates are accumulated next to it.
- **Outcome prediction** uses the conditional frequencies in the matching
  transition rows, smoothed by the belief priors (Laplace + base rates).

The engine is dependency-light (NumPy is optional) and degrades gracefully on
missing data.
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import select

from core.db.models import (
    WorldStateSnapshot,
    WorldTransitionEdge,
)

_LOG = logging.getLogger(__name__)

MODEL_VERSION = "v2"

# ---------------------------------------------------------------------------
# Variable schema (52 variables)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Variable:
    """A single belief-network variable definition."""

    name: str
    domain: str  # business | trading | personal | system | macro | risk
    kind: str    # continuous | binary | categorical
    bins: tuple[float, ...] = ()   # sorted thresholds, only for continuous
    categories: tuple[str, ...] = ()  # only for categorical
    description: str = ""


_BIZ = "business"
_TRD = "trading"
_PRS = "personal"
_SYS = "system"
_MAC = "macro"
_RSK = "risk"

_KIND_C = "continuous"
_KIND_B = "binary"
_KIND_CAT = "categorical"


STATE_VARIABLES: tuple[Variable, ...] = (
    # ---- business (10) ----
    Variable("revenue_7d_trend", _BIZ, _KIND_C, (-0.05, 0.0, 0.05), description="7d revenue trend pct"),
    Variable("revenue_mtd", _BIZ, _KIND_C, (50_000.0, 200_000.0, 1_000_000.0), description="month-to-date revenue (INR)"),
    Variable("inventory_turnover_rate", _BIZ, _KIND_C, (0.5, 1.5, 4.0), description="annualised turnover ratio"),
    Variable("cash_position", _BIZ, _KIND_C, (100_000.0, 500_000.0, 2_000_000.0), description="bank cash balance (INR)"),
    Variable("active_suppliers_count", _BIZ, _KIND_C, (1.0, 5.0, 15.0), description="active supplier count"),
    Variable("low_stock_count", _BIZ, _KIND_C, (0.0, 3.0, 10.0), description="SKUs below reorder point"),
    Variable("pending_invoices_amount", _BIZ, _KIND_C, (0.0, 100_000.0, 500_000.0), description="open AR (INR)"),
    Variable("gross_margin_estimate", _BIZ, _KIND_C, (0.10, 0.20, 0.35), description="rolling gross margin"),
    Variable("customer_count", _BIZ, _KIND_C, (5.0, 25.0, 100.0), description="distinct active customers"),
    Variable("ar_days_outstanding", _BIZ, _KIND_C, (15.0, 30.0, 60.0), description="DSO"),

    # ---- trading / market (10) ----
    Variable(
        "market_regime",
        _TRD,
        _KIND_CAT,
        categories=("bear", "sideways", "bull"),
        description="market regime label",
    ),
    Variable("volatility_30d", _TRD, _KIND_C, (0.10, 0.18, 0.28), description="annualised vol"),
    Variable("portfolio_exposure", _TRD, _KIND_C, (0.10, 0.40, 0.80), description="capital deployed pct"),
    Variable("win_rate_30d", _TRD, _KIND_C, (0.40, 0.50, 0.60), description="rolling 30d trade win rate"),
    Variable("drawdown_pct", _TRD, _KIND_C, (0.02, 0.05, 0.10), description="peak-to-trough drawdown"),
    Variable("avg_trade_pnl", _TRD, _KIND_C, (-100.0, 0.0, 100.0), description="avg pnl per trade (INR)"),
    Variable("num_open_positions", _TRD, _KIND_C, (1.0, 3.0, 8.0), description="open positions"),
    Variable("market_breadth", _TRD, _KIND_C, (0.4, 0.5, 0.6), description="advancers / total"),
    Variable("sector_concentration", _TRD, _KIND_C, (0.20, 0.40, 0.60), description="largest sector weight"),
    Variable("vix_proxy", _TRD, _KIND_C, (12.0, 18.0, 25.0), description="VIX-equivalent"),

    # ---- personal (8) ----
    Variable("founder_energy_score", _PRS, _KIND_C, (3.0, 6.0, 8.0), description="0-10 energy"),
    Variable("meeting_load", _PRS, _KIND_C, (1.0, 3.0, 6.0), description="meetings today"),
    Variable("focus_hours_yesterday", _PRS, _KIND_C, (1.0, 3.0, 5.0), description="deep focus hours"),
    Variable("sleep_quality_score", _PRS, _KIND_C, (5.0, 7.0, 8.5), description="0-10 sleep"),
    Variable("exercise_minutes_7d", _PRS, _KIND_C, (60.0, 150.0, 300.0), description="weekly exercise"),
    Variable("mood_score", _PRS, _KIND_C, (4.0, 6.0, 8.0), description="0-10 mood"),
    Variable("decision_count_today", _PRS, _KIND_C, (3.0, 8.0, 15.0), description="decisions logged today"),
    Variable("stress_index", _PRS, _KIND_C, (3.0, 5.0, 7.0), description="0-10 stress"),

    # ---- system (10) ----
    Variable("prediction_accuracy_7d", _SYS, _KIND_C, (0.55, 0.65, 0.75), description="rolling predictor acc"),
    Variable("system_trust_score", _SYS, _KIND_C, (40.0, 60.0, 80.0), description="0-100 trust"),
    Variable("autonomy_score", _SYS, _KIND_C, (0.20, 0.40, 0.60), description="0-1 autonomy ratio"),
    Variable("model_count_active", _SYS, _KIND_C, (1.0, 3.0, 6.0), description="active models in registry"),
    Variable("learning_rate_state", _SYS, _KIND_CAT, categories=("decaying", "steady", "improving"), description="learning trend"),
    Variable("error_count_24h", _SYS, _KIND_C, (1.0, 5.0, 20.0), description="errors last 24h"),
    Variable("sandbox_runs_7d", _SYS, _KIND_C, (0.0, 3.0, 10.0), description="sandbox executions"),
    Variable("evolution_score", _SYS, _KIND_C, (20.0, 40.0, 70.0), description="0-100 evolution score"),
    Variable("prediction_volume_7d", _SYS, _KIND_C, (50.0, 200.0, 1_000.0), description="predictions issued"),
    Variable("online_learner_health", _SYS, _KIND_B, description="online learner currently healthy"),

    # ---- macro / external (8) ----
    Variable("inr_usd_rate", _MAC, _KIND_C, (78.0, 83.0, 88.0), description="USD/INR fx"),
    Variable("brent_oil_price", _MAC, _KIND_C, (60.0, 80.0, 100.0), description="Brent crude USD/bbl"),
    Variable(
        "monsoon_status",
        _MAC,
        _KIND_CAT,
        categories=("deficit", "normal", "surplus"),
        description="IMD monsoon status",
    ),
    Variable(
        "kharif_outlook",
        _MAC,
        _KIND_CAT,
        categories=("weak", "neutral", "strong"),
        description="kharif crop outlook",
    ),
    Variable("cpi_inflation", _MAC, _KIND_C, (0.02, 0.045, 0.07), description="India CPI YoY"),
    Variable("repo_rate", _MAC, _KIND_C, (0.04, 0.055, 0.07), description="RBI repo"),
    Variable("gold_price_inr", _MAC, _KIND_C, (60_000.0, 75_000.0, 90_000.0), description="10g gold INR"),
    Variable("festival_proximity_days", _MAC, _KIND_C, (3.0, 14.0, 30.0), description="days to next festival"),

    # ---- risk (6) ----
    Variable("cash_runway_months", _RSK, _KIND_C, (1.0, 3.0, 6.0), description="months of runway"),
    Variable("supplier_concentration_risk", _RSK, _KIND_C, (0.30, 0.50, 0.70), description="largest supplier share"),
    Variable("single_customer_risk", _RSK, _KIND_C, (0.20, 0.40, 0.60), description="largest customer share"),
    Variable("regulatory_risk", _RSK, _KIND_B, description="open regulatory issue"),
    Variable("weather_risk", _RSK, _KIND_C, (0.20, 0.40, 0.60), description="0-1 weather risk"),
    Variable("fx_exposure", _RSK, _KIND_C, (0.10, 0.25, 0.50), description="0-1 FX exposure"),
)

VARIABLES_BY_NAME: dict[str, Variable] = {v.name: v for v in STATE_VARIABLES}

assert len(STATE_VARIABLES) >= 50, f"Expected 50+ variables, got {len(STATE_VARIABLES)}"

# ---------------------------------------------------------------------------
# Outcome catalogue
# ---------------------------------------------------------------------------

# Each entry maps the outcome name → list of (variable_name, "high"|"low"|"category", weight)
# influences. These are heuristic priors; transition-matrix evidence dominates
# once enough data accumulates.
_OUTCOME_INFLUENCES: dict[str, list[tuple[str, str, float]]] = {
    "revenue_up_next_week": [
        ("revenue_7d_trend", "high", 1.5),
        ("market_regime", "bull", 1.2),
        ("monsoon_status", "surplus", 0.8),
        ("festival_proximity_days", "low", 1.0),
        ("low_stock_count", "low", 0.6),
    ],
    "cash_crunch_30d": [
        ("cash_position", "low", 1.8),
        ("cash_runway_months", "low", 1.6),
        ("ar_days_outstanding", "high", 1.0),
        ("pending_invoices_amount", "high", 1.0),
    ],
    "inventory_stockout_7d": [
        ("low_stock_count", "high", 1.6),
        ("inventory_turnover_rate", "high", 1.2),
        ("supplier_concentration_risk", "high", 0.6),
        ("active_suppliers_count", "low", 0.6),
    ],
    "profit_margin_decline": [
        ("gross_margin_estimate", "low", 1.6),
        ("brent_oil_price", "high", 0.7),
        ("inr_usd_rate", "high", 0.7),
        ("cpi_inflation", "high", 0.6),
    ],
    "trading_drawdown_alert": [
        ("drawdown_pct", "high", 1.5),
        ("volatility_30d", "high", 1.0),
        ("vix_proxy", "high", 0.8),
        ("portfolio_exposure", "high", 0.6),
    ],
    "system_decision_quality_drop": [
        ("prediction_accuracy_7d", "low", 1.5),
        ("system_trust_score", "low", 1.2),
        ("error_count_24h", "high", 1.0),
        ("learning_rate_state", "decaying", 1.0),
    ],
    "founder_burnout_risk": [
        ("stress_index", "high", 1.4),
        ("sleep_quality_score", "low", 1.2),
        ("meeting_load", "high", 0.8),
        ("exercise_minutes_7d", "low", 0.6),
        ("mood_score", "low", 0.8),
    ],
    "regulatory_event_30d": [
        ("regulatory_risk", "high", 2.0),
        ("fx_exposure", "high", 0.5),
    ],
}


# ---------------------------------------------------------------------------
# Belief storage
# ---------------------------------------------------------------------------


@dataclass
class _Belief:
    """Per-variable posterior parameters."""

    kind: str
    # continuous: Welford state (mean, M2, n)
    mean: float = 0.0
    m2: float = 0.0
    n: int = 0
    # binary: Beta(alpha, beta)
    alpha: float = 1.0
    beta: float = 1.0
    # categorical: dirichlet counts
    counts: dict[str, float] = field(default_factory=dict)
    last_value: Any = None
    last_updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "n": int(self.n)}
        if self.kind == _KIND_C:
            var = self.m2 / self.n if self.n > 1 else 0.0
            d.update(
                {
                    "mean": round(float(self.mean), 6),
                    "variance": round(float(var), 6),
                    "stddev": round(math.sqrt(var) if var > 0 else 0.0, 6),
                }
            )
        elif self.kind == _KIND_B:
            total = self.alpha + self.beta
            d.update(
                {
                    "alpha": round(float(self.alpha), 4),
                    "beta": round(float(self.beta), 4),
                    "p": round(float(self.alpha) / float(total) if total else 0.5, 4),
                }
            )
        else:
            total = sum(self.counts.values()) or 1.0
            d.update(
                {
                    "counts": {k: round(float(v), 4) for k, v in self.counts.items()},
                    "probs": {
                        k: round(float(v) / float(total), 4) for k, v in self.counts.items()
                    },
                }
            )
        if self.last_value is not None:
            d["last_value"] = self.last_value
        if self.last_updated_at is not None:
            d["last_updated_at"] = self.last_updated_at
        return d


def _new_belief(var: Variable) -> _Belief:
    if var.kind == _KIND_CAT:
        return _Belief(kind=_KIND_CAT, counts={c: 1.0 for c in var.categories})
    return _Belief(kind=var.kind)


# ---------------------------------------------------------------------------
# Discretisation + signature
# ---------------------------------------------------------------------------


def _discretise(var: Variable, value: Any) -> str:
    """Return a short bucket label for a value of ``var``. Unknown → ``'?'``."""
    if value is None:
        return "?"
    try:
        if var.kind == _KIND_CAT:
            sval = str(value).strip().lower()
            for c in var.categories:
                if sval == c.lower():
                    return c[:6]
            return var.categories[0][:6] if var.categories else "?"
        if var.kind == _KIND_B:
            return "1" if bool(value) else "0"
        # continuous
        v = float(value)
        if not var.bins:
            return f"{v:.2f}"[:8]
        labels = ("vlo", "lo", "hi", "vhi")
        for i, threshold in enumerate(var.bins):
            if v < float(threshold):
                return labels[i] if i < len(labels) else f"b{i}"
        return labels[len(var.bins)] if len(var.bins) < len(labels) else f"b{len(var.bins)}"
    except (TypeError, ValueError):
        return "?"


def state_signature(state_vector: Mapping[str, Any]) -> str:
    """Stable 12-char hex signature for a state vector (order independent)."""
    parts: list[str] = []
    for var in STATE_VARIABLES:
        val = state_vector.get(var.name)
        parts.append(f"{var.name[:8]}:{_discretise(var, val)}")
    digest = hashlib.sha1("|".join(sorted(parts)).encode("utf-8")).hexdigest()
    return digest[:12]


# ---------------------------------------------------------------------------
# Belief updates
# ---------------------------------------------------------------------------


def _update_belief(belief: _Belief, value: Any) -> None:
    if belief.kind == _KIND_C:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        belief.n += 1
        delta = v - belief.mean
        belief.mean += delta / belief.n
        belief.m2 += delta * (v - belief.mean)
    elif belief.kind == _KIND_B:
        try:
            obs = bool(value)
        except Exception:
            return
        if obs:
            belief.alpha += 1.0
        else:
            belief.beta += 1.0
        belief.n += 1
    else:
        sval = str(value).strip().lower()
        for k in list(belief.counts.keys()):
            if k.lower() == sval:
                belief.counts[k] = belief.counts.get(k, 0.0) + 1.0
                belief.n += 1
                belief.last_value = k
                return
        # unknown bucket — register with low prior
        belief.counts[sval[:32]] = belief.counts.get(sval[:32], 1.0) + 1.0
        belief.n += 1
    belief.last_value = value
    belief.last_updated_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Outcome scoring (probability under current beliefs)
# ---------------------------------------------------------------------------


def _direction_score(var: Variable, belief: _Belief, direction: str) -> float:
    """Return a [0, 1] score for "variable currently favours ``direction``"."""
    direction = (direction or "").strip().lower()
    if belief.kind == _KIND_CAT:
        total = sum(belief.counts.values()) or 1.0
        return float(belief.counts.get(direction, 0.0) / total)
    if belief.kind == _KIND_B:
        total = belief.alpha + belief.beta
        p = float(belief.alpha) / float(total) if total else 0.5
        return p if direction in ("high", "1", "true", "yes") else 1.0 - p
    # continuous
    bins = var.bins
    if not bins:
        return 0.5
    median = float(bins[len(bins) // 2])
    spread = float(bins[-1] - bins[0]) or 1.0
    z = (belief.mean - median) / spread
    high = 1.0 / (1.0 + math.exp(-3.0 * z))
    return high if direction == "high" else (1.0 - high if direction == "low" else 0.5)


def _outcome_prior(state_vector: Mapping[str, Any], outcome: str) -> float:
    """Heuristic prior for an outcome from current state and influence weights."""
    influences = _OUTCOME_INFLUENCES.get(outcome, [])
    if not influences:
        return 0.5
    score = 0.0
    weight_sum = 0.0
    # Build temporary beliefs from raw state for prior scoring (no history).
    for var_name, direction, weight in influences:
        var = VARIABLES_BY_NAME.get(var_name)
        if var is None:
            continue
        tmp = _new_belief(var)
        if state_vector.get(var_name) is not None:
            _update_belief(tmp, state_vector[var_name])
        score += float(weight) * _direction_score(var, tmp, direction)
        weight_sum += abs(float(weight))
    if weight_sum <= 0:
        return 0.5
    return max(0.02, min(0.98, score / weight_sum))


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _factory_or_none():
    try:
        from core.database import get_session_factory

        return get_session_factory()
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_latest_snapshot(organization_id: int | None) -> WorldStateSnapshot | None:
    factory = _factory_or_none()
    if factory is None:
        return None
    try:
        with factory() as session:
            stmt = (
                select(WorldStateSnapshot)
                .where(WorldStateSnapshot.organization_id == organization_id)
                .order_by(WorldStateSnapshot.captured_at.desc(), WorldStateSnapshot.id.desc())
                .limit(1)
            )
            return session.execute(stmt).scalars().first()
    except Exception:
        return None


def _record_transition(
    organization_id: int | None,
    from_sig: str,
    to_sig: str,
    outcome_observed: Mapping[str, bool] | None,
) -> None:
    factory = _factory_or_none()
    if factory is None:
        return
    try:
        with factory() as session:
            stmt = (
                select(WorldTransitionEdge)
                .where(WorldTransitionEdge.organization_id == organization_id)
                .where(WorldTransitionEdge.from_state_signature == from_sig)
                .where(WorldTransitionEdge.to_state_signature == to_sig)
                .limit(1)
            )
            row = session.execute(stmt).scalars().first()
            if row is None:
                row = WorldTransitionEdge(
                    organization_id=organization_id,
                    from_state_signature=from_sig[:64],
                    to_state_signature=to_sig[:64],
                    transition_count=0,
                    outcome_aggregates={},
                )
                session.add(row)
            row.transition_count = int(row.transition_count or 0) + 1
            row.last_seen_at = datetime.now(timezone.utc)
            if outcome_observed:
                agg = dict(row.outcome_aggregates or {})
                for outcome, observed in outcome_observed.items():
                    bucket = agg.setdefault(outcome, {"obs": 0, "n": 0})
                    bucket["n"] = int(bucket.get("n") or 0) + 1
                    if bool(observed):
                        bucket["obs"] = int(bucket.get("obs") or 0) + 1
                row.outcome_aggregates = agg
            session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("world_model.record_transition failed: %s", exc)


def _outcome_evidence_from_transitions(
    organization_id: int | None,
    from_sig: str,
    outcome: str,
) -> tuple[float, int]:
    """Return ``(weighted_p, evidence_n)`` from transitions starting at ``from_sig``.

    Falls back to ``(0.5, 0)`` if no evidence is on disk.
    """
    factory = _factory_or_none()
    if factory is None:
        return 0.5, 0
    try:
        with factory() as session:
            stmt = (
                select(WorldTransitionEdge)
                .where(WorldTransitionEdge.organization_id == organization_id)
                .where(WorldTransitionEdge.from_state_signature == from_sig)
                .limit(64)
            )
            rows = session.execute(stmt).scalars().all()
    except Exception:
        return 0.5, 0
    obs = 0
    n = 0
    for r in rows:
        agg = (r.outcome_aggregates or {}).get(outcome) or {}
        n += int(agg.get("n") or 0)
        obs += int(agg.get("obs") or 0)
    if n <= 0:
        return 0.5, 0
    return float(obs) / float(n), int(n)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class WorldModelOutput:
    state_vector: dict[str, Any]
    state_signature: str
    belief_distribution: dict[str, dict[str, Any]]
    outcome_predictions: dict[str, dict[str, Any]]
    evidence_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "model_version": MODEL_VERSION,
            "state_signature": self.state_signature,
            "state_vector": self.state_vector,
            "belief_distribution": self.belief_distribution,
            "outcome_predictions": self.outcome_predictions,
            "evidence_count": int(self.evidence_count),
            "updated_at": _now_iso(),
        }


def _gather_state_from_feature_store(
    *, organization_id: int | None, user_id: int | None
) -> dict[str, Any]:
    """Pull whatever is available from the existing feature store + helpers."""
    state: dict[str, Any] = {v.name: None for v in STATE_VARIABLES}
    try:
        from services.ml import feature_store  # type: ignore[import-not-found]

        biz = feature_store.compute_features(
            feature_store.SCOPE_BUSINESS, organization_id=organization_id
        )
        trd = feature_store.compute_features(
            feature_store.SCOPE_TRADING, organization_id=organization_id
        )
        prs = feature_store.compute_features(feature_store.SCOPE_PERSONAL, user_id=user_id)
        for source in (biz, trd, prs):
            for k, v in (source or {}).items():
                if k in state:
                    state[k] = v
    except Exception as exc:
        _LOG.debug("world_model feature store unavailable: %s", exc)
    return state


def _enrich_with_predictive_signals(
    state: dict[str, Any], *, user_id: int | None
) -> dict[str, Any]:
    """Layer in signals from existing engines without re-implementing them."""
    if user_id is None:
        return state
    try:
        from services.feedback_engine import calculate_prediction_accuracy
        from services.predictive_engine import prediction_summary

        pred = prediction_summary(int(user_id))
        fb = calculate_prediction_accuracy(int(user_id), limit=200)
        regime_label = "bull" if (pred.get("profit_trend") or {}).get("trend") == "up" else (
            "bear" if (pred.get("predicted_risk") or {}).get("risk_level") == "high" else "sideways"
        )
        state.setdefault("market_regime", None)
        if state.get("market_regime") is None:
            state["market_regime"] = regime_label
        if state.get("system_trust_score") is None:
            state["system_trust_score"] = fb.get("system_trust_score")
        if state.get("prediction_accuracy_7d") is None:
            acc = (fb.get("accuracy_pct") or fb.get("system_trust_score") or 60.0)
            state["prediction_accuracy_7d"] = max(0.0, min(1.0, float(acc) / 100.0))
        if state.get("learning_rate_state") is None:
            trend = str(fb.get("trend") or "steady").lower()
            state["learning_rate_state"] = (
                "improving" if "improv" in trend else ("decaying" if "down" in trend or "decline" in trend else "steady")
            )
    except Exception as exc:
        _LOG.debug("world_model predictive enrichment skipped: %s", exc)
    return state


def gather_observations(
    *, organization_id: int | None = None, user_id: int | None = None
) -> dict[str, Any]:
    """Collect a best-effort observation for every variable in the schema.

    Missing variables are returned as ``None``; the engine treats those as
    "no evidence this tick" and skips them in the belief update.
    """
    state = _gather_state_from_feature_store(organization_id=organization_id, user_id=user_id)
    state = _enrich_with_predictive_signals(state, user_id=user_id)
    return state


# ---------------------------------------------------------------------------
# Public engine class
# ---------------------------------------------------------------------------


class BayesianWorldModel:
    """Belief-network engine for Phase 4.

    Beliefs are loaded from the most recent :class:`WorldStateSnapshot` for the
    organisation; updates are folded back in and re-snapshotted on demand. The
    object is cheap to instantiate per request (constant-time per call to
    :meth:`update_from_observation`).
    """

    def __init__(self, *, organization_id: int | None = None, user_id: int | None = None) -> None:
        self.organization_id = organization_id
        self.user_id = user_id
        self.beliefs: dict[str, _Belief] = {v.name: _new_belief(v) for v in STATE_VARIABLES}
        self.last_signature: str | None = None
        self.evidence_count: int = 0
        self._hydrate_from_snapshot()

    # -- hydration --------------------------------------------------------

    def _hydrate_from_snapshot(self) -> None:
        snap = _load_latest_snapshot(self.organization_id)
        if snap is None:
            return
        self.last_signature = (snap.state_signature or None) or None
        self.evidence_count = int(snap.evidence_count or 0)
        for name, payload in (snap.belief_distribution or {}).items():
            var = VARIABLES_BY_NAME.get(name)
            if var is None or not isinstance(payload, dict):
                continue
            kind = payload.get("kind") or var.kind
            belief = _new_belief(var)
            if kind == _KIND_C:
                belief.mean = float(payload.get("mean") or 0.0)
                var_v = float(payload.get("variance") or 0.0)
                belief.n = int(payload.get("n") or 0)
                belief.m2 = max(0.0, var_v * belief.n)
            elif kind == _KIND_B:
                belief.alpha = float(payload.get("alpha") or 1.0)
                belief.beta = float(payload.get("beta") or 1.0)
                belief.n = int(payload.get("n") or int(belief.alpha + belief.beta - 2))
            else:
                counts = payload.get("counts") or {}
                if isinstance(counts, dict):
                    belief.counts = {str(k): float(v) for k, v in counts.items() if v is not None}
                belief.n = int(payload.get("n") or int(sum(belief.counts.values())))
            belief.last_value = payload.get("last_value")
            belief.last_updated_at = payload.get("last_updated_at")
            self.beliefs[name] = belief

    # -- updates ----------------------------------------------------------

    def update_from_observation(
        self,
        observations: Mapping[str, Any],
        *,
        outcomes_observed: Mapping[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Fold an observation into the belief distribution.

        ``outcomes_observed`` is an optional mapping of
        ``{outcome_name: bool}`` describing whether each known outcome did
        actually happen in this tick (used to enrich the transition matrix).
        Returns the post-update :class:`WorldModelOutput` payload.
        """
        updated_keys: list[str] = []
        for name, val in (observations or {}).items():
            belief = self.beliefs.get(name)
            if belief is None or val is None:
                continue
            _update_belief(belief, val)
            updated_keys.append(name)
        if updated_keys:
            self.evidence_count += 1

        snapshot_state = self._current_state()
        new_sig = state_signature(snapshot_state)
        if self.last_signature is not None:
            _record_transition(
                self.organization_id,
                self.last_signature,
                new_sig,
                outcomes_observed,
            )
        self.last_signature = new_sig
        out = self._build_output(snapshot_state)
        return out.as_dict()

    # -- queries ----------------------------------------------------------

    def get_state_vector(self) -> dict[str, Any]:
        return self._current_state()

    def get_belief_distribution(self) -> dict[str, dict[str, Any]]:
        return {name: belief.as_dict() for name, belief in self.beliefs.items()}

    def predict_outcome(self, outcome: str, *, conditions: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return ``{p, evidence_n, sources, drivers}`` for ``outcome``.

        If ``conditions`` is given those values override the current state for
        scoring (cheap counterfactual: "what if cash position drops 20%?").
        """
        state = self._current_state()
        if conditions:
            for k, v in conditions.items():
                if k in state:
                    state[k] = v
        prior_p = _outcome_prior(state, outcome)
        sig = state_signature(state)
        evidence_p, evidence_n = _outcome_evidence_from_transitions(
            self.organization_id, sig, outcome
        )
        # Combine: more evidence → trust evidence more (Beta posterior style).
        weight_e = min(1.0, evidence_n / 30.0)
        p = (1.0 - weight_e) * prior_p + weight_e * evidence_p
        drivers = self._top_drivers(outcome, state, limit=5)
        return {
            "outcome": outcome,
            "p": round(max(0.01, min(0.99, p)), 4),
            "p_prior": round(prior_p, 4),
            "p_evidence": round(evidence_p, 4),
            "evidence_n": int(evidence_n),
            "state_signature": sig,
            "drivers": drivers,
        }

    def predict_all_business_outcomes(
        self, *, conditions: Mapping[str, Any] | None = None
    ) -> dict[str, dict[str, Any]]:
        return {name: self.predict_outcome(name, conditions=conditions) for name in _OUTCOME_INFLUENCES}

    # -- persistence ------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Persist the current belief network as a :class:`WorldStateSnapshot`."""
        state = self._current_state()
        out = self._build_output(state)
        factory = _factory_or_none()
        if factory is None:
            return out.as_dict()
        try:
            with factory() as session:
                row = WorldStateSnapshot(
                    organization_id=self.organization_id,
                    user_id=self.user_id,
                    state_signature=out.state_signature[:64],
                    state_vector=state,
                    belief_distribution=out.belief_distribution,
                    outcome_predictions=out.outcome_predictions,
                    evidence_count=int(out.evidence_count),
                    model_version=MODEL_VERSION,
                )
                session.add(row)
                session.commit()
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("world_model.snapshot persist failed: %s", exc)
        return out.as_dict()

    # -- internals --------------------------------------------------------

    def _current_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        for var in STATE_VARIABLES:
            belief = self.beliefs.get(var.name)
            if belief is None or belief.n == 0:
                state[var.name] = None
                continue
            if belief.kind == _KIND_C:
                state[var.name] = round(float(belief.mean), 6)
            elif belief.kind == _KIND_B:
                total = belief.alpha + belief.beta
                state[var.name] = round(float(belief.alpha) / float(total) if total else 0.5, 4)
            else:
                if not belief.counts:
                    state[var.name] = None
                else:
                    state[var.name] = max(belief.counts.items(), key=lambda kv: kv[1])[0]
        return state

    def _build_output(self, state: dict[str, Any]) -> WorldModelOutput:
        sig = state_signature(state)
        belief_dist = self.get_belief_distribution()
        outcomes: dict[str, dict[str, Any]] = {}
        for name in _OUTCOME_INFLUENCES:
            p_prior = _outcome_prior(state, name)
            evidence_p, evidence_n = _outcome_evidence_from_transitions(
                self.organization_id, sig, name
            )
            weight_e = min(1.0, evidence_n / 30.0)
            p = (1.0 - weight_e) * p_prior + weight_e * evidence_p
            outcomes[name] = {
                "p": round(max(0.01, min(0.99, p)), 4),
                "p_prior": round(p_prior, 4),
                "p_evidence": round(evidence_p, 4),
                "evidence_n": int(evidence_n),
            }
        return WorldModelOutput(
            state_vector=state,
            state_signature=sig,
            belief_distribution=belief_dist,
            outcome_predictions=outcomes,
            evidence_count=self.evidence_count,
        )

    def _top_drivers(
        self, outcome: str, state: Mapping[str, Any], *, limit: int
    ) -> list[dict[str, Any]]:
        influences = _OUTCOME_INFLUENCES.get(outcome, [])
        out: list[dict[str, Any]] = []
        for var_name, direction, weight in influences[:limit]:
            var = VARIABLES_BY_NAME.get(var_name)
            if var is None:
                continue
            tmp = _new_belief(var)
            if state.get(var_name) is not None:
                _update_belief(tmp, state[var_name])
            score = _direction_score(var, tmp, direction)
            out.append(
                {
                    "variable": var_name,
                    "direction": direction,
                    "weight": float(weight),
                    "current_value": state.get(var_name),
                    "contribution": round(float(weight) * score, 4),
                }
            )
        out.sort(key=lambda d: d["contribution"], reverse=True)
        return out


# ---------------------------------------------------------------------------
# Module-level convenience entry points
# ---------------------------------------------------------------------------


def update_world_model(
    *,
    organization_id: int | None,
    user_id: int | None = None,
    extra_observations: Mapping[str, Any] | None = None,
    outcomes_observed: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """One-shot tick: gather → update → return current beliefs.

    Used by the scheduler. Always returns a dict (no exceptions propagate).
    """
    try:
        engine = BayesianWorldModel(organization_id=organization_id, user_id=user_id)
        observations = gather_observations(organization_id=organization_id, user_id=user_id)
        if extra_observations:
            for k, v in extra_observations.items():
                if v is not None:
                    observations[k] = v
        return engine.update_from_observation(observations, outcomes_observed=outcomes_observed)
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("world_model.update failed: %s", exc)
        return {"ok": False, "error": str(exc), "model_version": MODEL_VERSION}


def snapshot_world_state(
    *, organization_id: int | None, user_id: int | None = None
) -> dict[str, Any]:
    """Persist a fresh snapshot. Calls :func:`update_world_model` first."""
    try:
        engine = BayesianWorldModel(organization_id=organization_id, user_id=user_id)
        observations = gather_observations(organization_id=organization_id, user_id=user_id)
        engine.update_from_observation(observations)
        return engine.snapshot()
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("world_model.snapshot_world_state failed: %s", exc)
        return {"ok": False, "error": str(exc), "model_version": MODEL_VERSION}


def predict(
    *,
    organization_id: int | None,
    outcome: str | None = None,
    conditions: Mapping[str, Any] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Return outcome predictions. If ``outcome`` is None, returns all."""
    try:
        engine = BayesianWorldModel(organization_id=organization_id, user_id=user_id)
        if outcome is None:
            return {
                "ok": True,
                "predictions": engine.predict_all_business_outcomes(conditions=conditions),
                "state_signature": state_signature(engine.get_state_vector()),
                "model_version": MODEL_VERSION,
            }
        return {
            "ok": True,
            "prediction": engine.predict_outcome(outcome, conditions=conditions),
            "model_version": MODEL_VERSION,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": str(exc), "model_version": MODEL_VERSION}


def get_status() -> dict[str, Any]:
    """Capability snapshot for ``GET /personal/os/brain-health``."""
    factory = _factory_or_none()
    snapshot_count = 0
    edge_count = 0
    last_at: str | None = None
    if factory is not None:
        try:
            with factory() as session:
                from sqlalchemy import func as _func

                snapshot_count = int(
                    session.execute(select(_func.count(WorldStateSnapshot.id))).scalars().first()
                    or 0
                )
                edge_count = int(
                    session.execute(select(_func.count(WorldTransitionEdge.id))).scalars().first()
                    or 0
                )
                last = (
                    session.execute(
                        select(WorldStateSnapshot.captured_at)
                        .order_by(WorldStateSnapshot.captured_at.desc())
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                if last is not None:
                    last_at = last.isoformat()
        except Exception:
            pass
    return {
        "model_version": MODEL_VERSION,
        "variable_count": len(STATE_VARIABLES),
        "outcome_count": len(_OUTCOME_INFLUENCES),
        "snapshot_count": snapshot_count,
        "transition_edges": edge_count,
        "last_snapshot_at": last_at,
    }


__all__ = [
    "BayesianWorldModel",
    "MODEL_VERSION",
    "STATE_VARIABLES",
    "VARIABLES_BY_NAME",
    "Variable",
    "WorldModelOutput",
    "gather_observations",
    "get_status",
    "predict",
    "snapshot_world_state",
    "state_signature",
    "update_world_model",
]


def _outcome_unused_export(_x: Iterable[str] = ()) -> None:  # pragma: no cover
    """Kept to silence import-warnings for runtime tooling."""
    _ = list(_x)
