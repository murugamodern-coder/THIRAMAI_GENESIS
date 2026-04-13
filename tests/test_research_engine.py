"""Part C research engine — structure and parsing (mocked external APIs)."""

from __future__ import annotations

from unittest.mock import patch

from services.research_common import parse_json_lenient
from services.research_schemes_service import _norm_state, find_schemes_sync


def test_norm_state_tn_expands():
    assert "Tamil" in _norm_state("TN")


def test_parse_json_lenient_embedded():
    raw = 'Here is JSON:\n{"a": 1, "b": [2]}'
    j = parse_json_lenient(raw)
    assert j == {"a": 1, "b": [2]}


@patch("services.research_schemes_service.groq_json_object_sync")
@patch("services.research_schemes_service.tavily_search_sync")
def test_find_schemes_structure(mock_tavily, mock_groq):
    mock_tavily.return_value = {
        "results": [
            {"title": "PM Formalisation", "url": "https://example.gov/scheme", "content": "MSME subsidy"},
        ]
    }
    mock_groq.return_value = {
        "schemes": [
            {
                "scheme_name": "Test Scheme",
                "eligibility": "MSME registered",
                "subsidy_amount": "Up to 10 lakh",
                "application_process": "Apply online",
                "deadline": "2026-12-31",
                "source_url": "https://example.gov/scheme",
            }
        ]
    }
    out = find_schemes_sync(
        "food processing",
        "TN",
        user_id=None,
        organization_id=None,
        persist=False,
        match_alerts=False,
    )
    assert out.get("ok") is True
    assert len(out.get("schemes") or []) >= 1
    s0 = out["schemes"][0]
    assert "scheme_name" in s0 or "name" in s0


@patch("services.research_market_service.groq_json_object_sync")
@patch("services.research_market_service.tavily_search_sync")
def test_research_market_structure(mock_tavily, mock_groq):
    from services.research_market_service import research_market_sync

    mock_tavily.return_value = {"results": [{"title": "Rpt", "url": "https://x.test", "content": "market growing"}]}
    mock_groq.return_value = {
        "market_size": "₹500 cr",
        "growth_rate": "8% CAGR",
        "top_players": ["A", "B"],
        "price_trends": "stable",
        "demand_forecast": "up",
        "opportunities": ["export"],
    }
    out = research_market_sync("test product", user_id=0, organization_id=None, persist=False)
    assert out.get("ok") is True
    st = out.get("structured") or {}
    assert st.get("market_size") == "₹500 cr"
    assert isinstance(st.get("top_players"), list)


@patch("services.dpr_generator_service.long_llm_sync")
def test_dpr_report_keys(mock_long):
    from services.dpr_generator_service import generate_dpr_sync

    mock_long.return_value = """{
      "executive_summary": "x",
      "market_analysis": "y",
      "technical_plan": "z",
      "cost_estimation": "c",
      "financial_projection": "f",
      "break_even": "b",
      "roi": "r"
    }"""
    out = generate_dpr_sync("unit test biz", "1 unit", "Test City", user_id=0, persist=False)
    assert out.get("ok") is True
    rep = out.get("report") or {}
    for k in (
        "executive_summary",
        "market_analysis",
        "technical_plan",
        "cost_estimation",
        "financial_projection",
        "break_even",
        "roi",
    ):
        assert k in rep
