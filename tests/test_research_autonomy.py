"""Autonomous research routing (mocked market data)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from services.research_autonomy import plan_autonomous_research
from services.research_engine_templates import (
    RESEARCH_CATEGORY_DEEP_FINANCIAL,
    RESEARCH_CATEGORY_INDUSTRIAL_ENERGY,
    RESEARCH_CATEGORY_REAL_ESTATE,
)


@patch("services.research_autonomy.fetch_quote_yfinance", return_value=(Decimal("42.5"), "INR"))
@patch(
    "services.research_autonomy.maybe_resolve_equity_for_topic",
    return_value={
        "yahoo": "SUZLON.NS",
        "base": "SUZLON",
        "name": "Suzlon Energy Limited",
        "label": "Suzlon Energy Limited (SUZLON.NS)",
        "score": 88.0,
    },
)
def test_company_typo_triggers_deep_financial(_mock_eq, _mock_q) -> None:
    plan = plan_autonomous_research("Suslan")
    assert plan.business_category == RESEARCH_CATEGORY_DEEP_FINANCIAL
    assert plan.resolved_yahoo_symbol == "SUZLON.NS"
    assert plan.price_at_save == Decimal("42.5")
    assert "LIVE MARKET SNAPSHOT" in plan.user_message


def test_solar_stays_energy() -> None:
    plan = plan_autonomous_research("Solar rooftop 5MW")
    assert plan.business_category == RESEARCH_CATEGORY_INDUSTRIAL_ENERGY
    assert plan.resolved_yahoo_symbol is None


def test_land_stays_real_estate() -> None:
    plan = plan_autonomous_research("Mandakolathur registration stamp duty")
    assert plan.business_category == RESEARCH_CATEGORY_REAL_ESTATE
