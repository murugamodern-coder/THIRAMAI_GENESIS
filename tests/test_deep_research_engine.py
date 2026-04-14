"""Deep research engine — normalization, comparison, orchestration (mocked I/O)."""

from __future__ import annotations

from unittest.mock import patch

from services.deep_research_engine import (
    build_comparison_table,
    deep_research_sync,
    normalize_results,
    query_implies_comparison,
    search_all_sources,
)


def test_normalize_results_dedupes_by_url():
    raw = [
        {"source": "web", "title": "A", "url": "https://example.com/x", "snippet": "₹ 100 per unit"},
        {"source": "news_rss", "title": "dup", "url": "https://example.com/x/", "snippet": "repeat"},
    ]
    out = normalize_results(raw)
    assert len(out) == 1
    assert "prices" in (out[0].get("categories") or [])


def test_query_implies_comparison():
    assert query_implies_comparison("Compare IndiaMART vs TradeIndia for pumps") is True
    assert query_implies_comparison("general industry overview") is False


@patch("services.deep_research_engine.groq_json_object_sync")
def test_build_comparison_table(mock_groq):
    mock_groq.return_value = {"headers": ["Vendor", "Price", "Location"], "rows": [["Acme", "₹2.1L", "Chennai"]]}
    tab = build_comparison_table(
        [{"title": "Acme supplier", "url": "https://ex.com", "snippet": "cold press ₹2.1 lakh"}],
        query="compare suppliers",
    )
    assert tab is not None
    assert tab["headers"][0] == "Vendor"
    assert len(tab["rows"]) == 1


@patch("services.deep_research_engine.groq_json_object_sync")
@patch("services.personal_command_center_service.create_research_project_sync")
@patch("services.deep_research_engine.search_google_news_rss_sync")
@patch("services.deep_research_engine.tavily_search_sync")
def test_deep_research_sync_structured_and_comparison(mock_tavily, mock_rss, mock_create, mock_groq):
    mock_tavily.return_value = {
        "ok": True,
        "results": [{"title": "Vendor A", "url": "https://a.test", "content": "Price ₹50,000 Coimbatore"}],
    }
    mock_rss.return_value = [{"source": "news_rss", "title": "N", "url": "https://news.test", "snippet": "market"}]
    mock_create.return_value = (True, "ok", 42)
    mock_groq.side_effect = [
        {
            "tables": [],
            "price_list": [{"item": "unit", "price_text": "₹50,000", "source_url": "https://a.test"}],
            "vendor_list": [{"name": "Vendor A", "url": "https://a.test", "location": "Coimbatore", "rating": ""}],
            "govt_docs": [],
            "statistics": [],
        },
        {"headers": ["Vendor", "Price", "Location"], "rows": [["Vendor A", "₹50,000", "Coimbatore"]]},
        {
            "summary": "Two-line synthesis.",
            "key_insights": ["i1"],
            "risks": ["verify price"],
            "opportunities": ["export"],
            "confidence_score": 0.72,
        },
    ]

    out = deep_research_sync(
        "compare cold press machine price Coimbatore",
        "standard",
        user_id=1,
        organization_id=1,
        persist=True,
    )
    assert out.get("ok") is True
    assert out.get("research_project_id") == 42
    assert out.get("comparison_table") is not None
    st = out.get("structured_data") or {}
    assert len(st.get("price_list") or []) >= 1
    assert float(out.get("confidence_score") or 0) > 0.5


@patch("services.deep_research_engine.tavily_search_sync")
def test_search_all_sources_quick_web_only(mock_tavily):
    mock_tavily.return_value = {"ok": True, "results": [{"title": "W", "url": "https://w", "content": "c"}]}
    bundle = search_all_sources("solar inverter MSME", "quick")
    assert bundle.get("ok") is True
    assert bundle.get("depth") == "quick"
    assert all(it.get("source") == "web" for it in bundle.get("items") or [])
