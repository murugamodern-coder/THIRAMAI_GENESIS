"""Business-category detection for the Research Hub."""

from __future__ import annotations

from services.research_engine_templates import (
    RESEARCH_CATEGORY_DEEP_FINANCIAL,
    RESEARCH_CATEGORY_FINANCIAL_STOCKS,
    RESEARCH_CATEGORY_INDUSTRIAL_ENERGY,
    RESEARCH_CATEGORY_REAL_ESTATE,
    VALID_RESEARCH_CATEGORIES,
    category_label,
    detect_research_business_category,
    structural_template_topic,
)


def test_vodafone_idea_is_financial() -> None:
    assert detect_research_business_category("Vodafone Idea outlook") == RESEARCH_CATEGORY_FINANCIAL_STOCKS
    assert detect_research_business_category("vodafone idea share price") == RESEARCH_CATEGORY_FINANCIAL_STOCKS


def test_solar_is_energy() -> None:
    assert detect_research_business_category("Solar") == RESEARCH_CATEGORY_INDUSTRIAL_ENERGY
    assert detect_research_business_category("solar park 50mw tamil nadu") == RESEARCH_CATEGORY_INDUSTRIAL_ENERGY


def test_mandakolathur_real_estate() -> None:
    assert detect_research_business_category("Mandakolathur land registration costs") == RESEARCH_CATEGORY_REAL_ESTATE


def test_guideline_value_real_estate() -> None:
    assert detect_research_business_category("Guideline value vs market rate Chennai plot") == RESEARCH_CATEGORY_REAL_ESTATE


def test_category_labels() -> None:
    for c in VALID_RESEARCH_CATEGORIES:
        assert category_label(c)
    assert "Deep" in category_label(RESEARCH_CATEGORY_DEEP_FINANCIAL)


def test_structural_energy_and_re() -> None:
    assert structural_template_topic("200 MW solar park") == RESEARCH_CATEGORY_INDUSTRIAL_ENERGY
    assert structural_template_topic("Mandakolathur guideline value") == RESEARCH_CATEGORY_REAL_ESTATE
    assert structural_template_topic("Vodafone Idea") is None


def test_default_legacy_energy() -> None:
    """Ambiguous industrial-style topics keep the legacy DPR-style default."""
    assert detect_research_business_category("competitor pricing in Chennai") == RESEARCH_CATEGORY_INDUSTRIAL_ENERGY
