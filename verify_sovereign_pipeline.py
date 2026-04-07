"""
Dry-run structural checks for THIRAMAI Tech Empire (no API keys required).
Run: python verify_sovereign_pipeline.py
"""

from __future__ import annotations

from core.policies.loader import TAVILY_API_QUERY_LIMIT, get_prompt
from core.router import route_is_industrial_business
from core.search_pipeline import (
    _ascii_debug,
    clip_for_tavily_api,
    fallback_search_seed,
    topic_search_queries,
)


def dry_run_1_agri_handoff() -> None:
    """Simple ag query -> council path (router only); R1->R2->R3 is enforced in _run_strategic_council source."""
    q = "Paddy yield in Thanjavur"
    assert not route_is_industrial_business(q), "Expected Tech Empire council, not industrial DPR"
    agri = get_prompt("PROMPT_AGRI_SCIENTIST")
    econ = get_prompt("PROMPT_ECONOMIC_ARCHITECT")
    tech = get_prompt("PROMPT_TECH_STRATEGIST")
    assert "Field Intelligence" in agri or "Agri-Scientist" in agri
    assert "Financial Engine" in econ or "Economic Architect" in econ
    assert "Tech Integration" in tech or "Tech Strategist" in tech
    print("[OK] Dry run 1: ag query routes to council; three agent prompts present.")


def dry_run_2_industrial_router() -> None:
    q = "Drip Irrigation Pipe Factory ROI"
    assert route_is_industrial_business(q), "Industrial keywords should select DPR pipeline"
    print("[OK] Dry run 2: industrial query triggers Industrial Business DPR router.")


def dry_run_3_long_query_tavily_cap() -> None:
    """Simulate ~1000-word brief: fallback seed must stay within Tavily limit."""
    long_q = ("word " * 1000).strip()
    assert len(long_q) > 3000
    seed = fallback_search_seed(long_q)
    assert len(seed) <= TAVILY_API_QUERY_LIMIT, f"seed len {len(seed)} > {TAVILY_API_QUERY_LIMIT}"
    for q in topic_search_queries(seed):
        clipped = clip_for_tavily_api(q)
        assert len(clipped) <= TAVILY_API_QUERY_LIMIT, f"Tavily query len {len(clipped)}"
    mega = "a" * 10_000
    assert len(clip_for_tavily_api(mega)) == TAVILY_API_QUERY_LIMIT
    # ASCII debug must be pure ASCII
    ad = _ascii_debug("\u2192 Tamil \u0b9e")
    assert ad.encode("ascii")
    print("[OK] Dry run 3: summarizer/fallback + topic queries respect 200-char Tavily cap; debug ASCII safe.")


def main() -> None:
    dry_run_1_agri_handoff()
    dry_run_2_industrial_router()
    dry_run_3_long_query_tavily_cap()
    print("\nAll sovereign pipeline structural checks passed.")


if __name__ == "__main__":
    main()
