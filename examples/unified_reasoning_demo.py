"""Demo: cross-domain unified reasoning end-to-end.

Run with::

    python examples/unified_reasoning_demo.py

The demo uses the deterministic fallback embedder and the in-house fallback
DiGraph by default - no extra dependencies required. If
``sentence-transformers`` and / or ``networkx`` are installed they'll be
picked up automatically.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow ``python examples/unified_reasoning_demo.py`` to import top-level
# packages without installing the project; mirrors policy_engine_usage.py.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.unified_reasoner import (  # noqa: E402
    EMBEDDINGS_AVAILABLE,
    GRAPH_AVAILABLE,
    get_unified_reasoner,
)


def _print_section(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}\n{title}\n{bar}")


def _print_result(result: dict) -> None:
    primary = result.get("primary_action") or {}
    print("\nPrimary action:")
    print(f"  domain     : {primary.get('domain')}")
    print(f"  action     : {primary.get('action')}")
    print(f"  confidence : {float(primary.get('confidence', 0.0)):.2f}")
    print(f"  reasoning  : {primary.get('reasoning')}")

    secondary = result.get("secondary_effects") or []
    print(f"\nSecondary effects ({len(secondary)}):")
    for effect in secondary:
        print(f"  - {effect.get('domain'):8s} {effect.get('action')}")
        print(f"      impact={effect.get('impact')} magnitude={float(effect.get('magnitude', 0.0)):.2f}")
        print(f"      {effect.get('reasoning')}")

    affected = result.get("domains_affected") or []
    print(f"\nDomains affected: {', '.join(affected) if affected else '(none)'}")

    relevant = result.get("relevant_concepts") or []
    print(f"\nRelevant concepts ({len(relevant)}):")
    for c in relevant:
        print(f"  - [{c.get('domain'):8s}] {c.get('name')}  sim={float(c.get('similarity', 0.0)):.3f}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s :: %(message)s")
    print(
        "Backends: "
        f"sentence-transformers={'available' if EMBEDDINGS_AVAILABLE else 'fallback'}, "
        f"networkx={'available' if GRAPH_AVAILABLE else 'fallback'}"
    )

    reasoner = get_unified_reasoner()

    _print_section("Query 1: market crash implications")
    _print_result(reasoner.reason("Market crash expected tomorrow"))

    _print_section("Query 2: business demand spike")
    _print_result(reasoner.reason("Customer demand spiking unexpectedly"))

    _print_section("Query 3: personal stress")
    _print_result(reasoner.reason("Feeling overwhelmed and stressed"))

    _print_section("Learning a new concept + relationship")
    new_concept = reasoner.add_concept(
        domain="business",
        name="Product launch",
        description="Launching a new product into the market",
    )
    print(f"Added concept   : {new_concept.concept_id}")
    print(f"Embedding shape : {new_concept.embedding.shape}")

    ok = reasoner.learn_relationship(
        new_concept.concept_id,
        "personal_time_crunch",
        relationship="causes",
        strength=0.8,
    )
    print(f"Learned edge    : product launch -causes-> personal_time_crunch  ok={ok}")

    _print_section("Query 4: re-run after learning")
    _print_result(reasoner.reason("planning a product launch"))


if __name__ == "__main__":
    main()
