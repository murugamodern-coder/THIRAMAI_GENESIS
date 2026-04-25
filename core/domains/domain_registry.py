"""
Self-Evolution Phase 2: Domain plugin registry.

Provides :class:`Domain` and :class:`DomainRegistry`. The registry is a
process-singleton (also persisted to ``domain_definitions``) so other modules
can ask, "which features does ``equity_trading`` use?" or "which ML model
serves ``personal_health``?" without hard-coding strings.

Pre-built domains
-----------------
- ``irrigation_manufacturing``
- ``edible_oil_production``
- ``agro_trading``
- ``equity_trading``
- ``personal_health``
- ``personal_finance``

The default set is registered on first import. Users can call
:func:`register_default_domains` again to refresh DB rows after schema changes.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select

from services.ml.model_ensemble import (
    DOMAIN_PREFERRED_MODEL,
    ENSEMBLE_NAME,
)
from services.ml.outcome_predictor import MODEL_NAME as OUTCOME_PREDICTOR_NAME
from services.ml.online_learner import ONLINE_MODEL_NAME

_LOG = logging.getLogger(__name__)

_REGISTRY_LOCK = threading.Lock()


@dataclass
class Domain:
    """A domain plugin definition.

    All collections are stored as plain Python lists / dicts so the entire
    record is JSON-serialisable for the ``domain_definitions`` table.
    """

    name: str
    display_name: str = ""
    description: str = ""
    models: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    prompts: dict[str, str] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["preferred_model"] = DOMAIN_PREFERRED_MODEL.get(self.name, "random_forest")
        return d

    def feature_names(self) -> list[str]:
        return list(self.features)


class DomainRegistry:
    """In-process domain registry, optionally mirrored to the DB."""

    _by_name: dict[str, Domain] = {}

    @classmethod
    def register(cls, domain: Domain, *, persist: bool = True) -> Domain:
        """Add or replace a domain. When ``persist=True``, also upsert DB row."""
        if not isinstance(domain, Domain):
            raise TypeError("DomainRegistry.register expects a Domain instance")
        if not domain.name:
            raise ValueError("Domain.name must be a non-empty string")
        with _REGISTRY_LOCK:
            cls._by_name[domain.name] = domain
        if persist:
            try:
                _persist_domain(domain)
            except Exception as exc:
                _LOG.debug("persist domain %s failed: %s", domain.name, exc)
        return domain

    @classmethod
    def get(cls, name: str) -> Domain | None:
        with _REGISTRY_LOCK:
            return cls._by_name.get(str(name))

    @classmethod
    def list_all(cls, *, active_only: bool = False) -> list[Domain]:
        with _REGISTRY_LOCK:
            items = list(cls._by_name.values())
        if active_only:
            items = [d for d in items if d.is_active]
        return sorted(items, key=lambda d: d.name)

    @classmethod
    def get_features(cls, name: str) -> list[str]:
        d = cls.get(name)
        return d.feature_names() if d else []

    @classmethod
    def get_models(cls, name: str) -> list[str]:
        d = cls.get(name)
        return list(d.models) if d else []

    @classmethod
    def clear(cls) -> None:
        """Drop in-process state (test helper)."""
        with _REGISTRY_LOCK:
            cls._by_name.clear()


# ---------------------------------------------------------------------------
# DB persistence (best-effort)
# ---------------------------------------------------------------------------


def _persist_domain(domain: Domain) -> None:
    try:
        from core.database import get_session_factory
    except Exception as exc:
        _LOG.debug("domain_registry session factory import failed: %s", exc)
        return
    try:
        factory = get_session_factory()
    except Exception as exc:
        _LOG.debug("domain_registry session factory unavailable: %s", exc)
        return
    from core.db.models import DomainDefinition

    with factory() as session:
        try:
            existing = session.execute(
                select(DomainDefinition).where(DomainDefinition.name == domain.name)
            ).scalar_one_or_none()
        except Exception as exc:
            _LOG.debug("domain_definitions select failed (table missing?): %s", exc)
            return
        now = datetime.now(timezone.utc)
        if existing is None:
            row = DomainDefinition(
                name=domain.name,
                display_name=domain.display_name or domain.name,
                description=domain.description,
                models=list(domain.models),
                features=list(domain.features),
                tables=list(domain.tables),
                prompts=dict(domain.prompts),
                policies=dict(domain.policies),
                is_active=bool(domain.is_active),
                registered_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            existing.display_name = domain.display_name or existing.display_name
            existing.description = domain.description or existing.description
            existing.models = list(domain.models)
            existing.features = list(domain.features)
            existing.tables = list(domain.tables)
            existing.prompts = dict(domain.prompts)
            existing.policies = dict(domain.policies)
            existing.is_active = bool(domain.is_active)
            existing.updated_at = now
        try:
            session.commit()
        except Exception as exc:
            _LOG.debug("domain persist commit failed: %s", exc)
            session.rollback()


# ---------------------------------------------------------------------------
# Pre-built domains
# ---------------------------------------------------------------------------

_BUSINESS_FEATURES = [
    "revenue_7d_trend",
    "inventory_turnover_rate",
    "cash_position",
    "active_suppliers_count",
]
_TRADING_FEATURES = [
    "market_regime",
    "volatility_30d",
    "portfolio_exposure",
]
_PERSONAL_FEATURES = [
    "founder_energy_score",
    "meeting_load",
    "focus_hours_yesterday",
]

_DEFAULT_DOMAIN_BLUEPRINTS: list[Domain] = [
    Domain(
        name="irrigation_manufacturing",
        display_name="Irrigation Manufacturing",
        description=(
            "Solar pumps, HDPE/PVC pipes, drip irrigation kits — make-to-stock"
            " factory lines and field installation projects."
        ),
        models=[OUTCOME_PREDICTOR_NAME, ENSEMBLE_NAME],
        features=_BUSINESS_FEATURES,
        tables=[
            "inventory_items",
            "stock_movements",
            "production_logs",
            "purchase_orders",
            "suppliers",
            "invoices",
            "organization_liquidity",
        ],
        prompts={
            "daily_brief": (
                "You are running an irrigation manufacturing line. Use the "
                "business snapshot to flag stockouts, late POs, and revenue "
                "anomalies for {organization_name}."
            ),
            "production_recommendation": (
                "Given inventory turnover {inventory_turnover_rate} and revenue "
                "trend {revenue_7d_trend}, recommend a production batch size."
            ),
        },
        policies={
            "min_inventory_buffer_days": 5,
            "max_supplier_concentration": 0.4,
            "require_owner_approval_for_capex_above_inr": 100000,
        },
    ),
    Domain(
        name="edible_oil_production",
        display_name="Edible Oil & Jaggery Production",
        description=(
            "Cold-pressed edible oil and jaggery batches — perishable inventory"
            " with FSSAI compliance, batch traceability, and regional demand"
            " spikes around festivals."
        ),
        models=[OUTCOME_PREDICTOR_NAME, ENSEMBLE_NAME],
        features=_BUSINESS_FEATURES,
        tables=[
            "inventory_items",
            "raw_materials",
            "production_logs",
            "invoices",
            "bills",
            "compliance_cases",
        ],
        prompts={
            "shelf_life_alert": (
                "Flag SKUs with remaining shelf life under {threshold_days} days"
                " and propose a discount/clearance path."
            ),
            "festival_demand_brief": (
                "Project demand uplift for the next festival window using"
                " revenue_7d_trend={revenue_7d_trend}."
            ),
        },
        policies={
            "fssai_required": True,
            "max_batch_age_days": 90,
            "discount_for_aging_pct_min": 5,
            "discount_for_aging_pct_max": 25,
        },
    ),
    Domain(
        name="agro_trading",
        display_name="Agricultural Trading",
        description=(
            "Bulk buying and selling of agricultural commodities — daily price"
            " arbitrage between mandis, transport coordination, supplier"
            " advances and credit risk management."
        ),
        models=[OUTCOME_PREDICTOR_NAME, ENSEMBLE_NAME],
        features=_BUSINESS_FEATURES + ["market_regime", "volatility_30d"],
        tables=[
            "inventory_items",
            "purchase_orders",
            "suppliers",
            "supplier_payments",
            "invoices",
            "ledger_transactions",
        ],
        prompts={
            "mandi_arbitrage_brief": (
                "List mandis where today's spread > 3% net of transport cost"
                " for top SKUs. Include supplier credit risk."
            ),
        },
        policies={
            "max_credit_per_supplier_inr": 500000,
            "min_margin_pct": 4.0,
            "require_lab_test_for_new_supplier": True,
        },
    ),
    Domain(
        name="equity_trading",
        display_name="Equity Trading",
        description=(
            "NSE/BSE equity execution — intraday + swing strategies with strict"
            " kill-switch, daily loss caps and per-trade volatility-scaled"
            " sizing. Production trading is gated on multiple safety layers."
        ),
        models=[ENSEMBLE_NAME, ONLINE_MODEL_NAME],
        features=_TRADING_FEATURES,
        tables=[
            "equity_portfolio_positions",
            "stock_watchlist_entries",
            "stock_price_alerts",
            "ledger_transactions",
            "predictions_pending",
        ],
        prompts={
            "morning_market_brief": (
                "Give me the macro tape for today: regime={market_regime},"
                " 30d vol={volatility_30d}, exposure={portfolio_exposure}."
            ),
            "trade_idea_review": (
                "Critique this trade idea against current regime + volatility."
            ),
        },
        policies={
            "max_daily_loss_inr": 5000,
            "max_position_pct_of_capital": 0.10,
            "max_concurrent_positions": 5,
            "kill_switch_drawdown_pct": 3.0,
            "live_trading_requires_owner_flag": True,
        },
    ),
    Domain(
        name="personal_health",
        display_name="Personal Health",
        description=(
            "Founder physical/mental energy management — habits, vitals,"
            " meeting load, focus hours. Feeds the daily brief and decision"
            " quality predictors."
        ),
        models=[ONLINE_MODEL_NAME],
        features=_PERSONAL_FEATURES,
        tables=[
            "habits",
            "habit_logs",
            "personal_health_metrics",
            "personal_meetings",
            "learning_logs",
        ],
        prompts={
            "energy_brief": (
                "Energy={founder_energy_score}, meetings={meeting_load},"
                " focus_yesterday={focus_hours_yesterday}h. Recommend a"
                " realistic plan for today."
            ),
        },
        policies={
            "min_sleep_hours": 6,
            "max_meetings_per_day": 6,
            "deep_work_block_min_minutes": 90,
        },
    ),
    Domain(
        name="personal_finance",
        display_name="Personal Finance",
        description=(
            "Founder personal balance sheet — savings, debts, fixed expenses,"
            " family obligations. Distinct from business cash position."
        ),
        models=[OUTCOME_PREDICTOR_NAME],
        features=["cash_position", "founder_energy_score"],
        tables=["assets", "debts", "user_personal_crypto", "ledger_transactions"],
        prompts={
            "monthly_review": (
                "Summarise net worth change, debt-to-asset ratio and surplus"
                " cash for re-investment."
            ),
        },
        policies={
            "emergency_fund_months_min": 3,
            "max_personal_debt_to_asset_ratio": 0.5,
        },
    ),
]


def register_default_domains(*, persist: bool = True) -> int:
    """(Re)register the six built-in domains. Returns count registered."""
    count = 0
    for blueprint in _DEFAULT_DOMAIN_BLUEPRINTS:
        DomainRegistry.register(blueprint, persist=persist)
        count += 1
    return count


def iter_domain_names() -> Iterable[str]:
    return (d.name for d in DomainRegistry.list_all())


# Auto-register on import (no DB persist — boot lifecycle calls
# ``register_default_domains(persist=True)`` once the DB is ready).
register_default_domains(persist=False)


__all__ = [
    "Domain",
    "DomainRegistry",
    "iter_domain_names",
    "register_default_domains",
]
