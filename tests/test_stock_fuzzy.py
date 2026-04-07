"""Fuzzy Indian equity resolution (no live quote calls)."""

from __future__ import annotations

from services.stock_market_service import fuzzy_resolve_indian_equity


def test_suslan_maps_to_suzlon() -> None:
    hit = fuzzy_resolve_indian_equity("Suslan", score_cutoff=68)
    assert hit is not None
    assert hit["yahoo"] == "SUZLON.NS"
    assert hit["base"] == "SUZLON"


def test_vodafone_idea_maps_to_idea() -> None:
    hit = fuzzy_resolve_indian_equity("Vodafone Idea", score_cutoff=68)
    assert hit is not None
    assert hit["yahoo"] == "IDEA.NS"


def test_ticker_dot_ns_exact() -> None:
    hit = fuzzy_resolve_indian_equity("RELIANCE.NS", score_cutoff=68)
    assert hit is not None
    assert hit["yahoo"] == "RELIANCE.NS"
