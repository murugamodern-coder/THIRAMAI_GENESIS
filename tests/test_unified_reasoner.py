"""Tests for :mod:`services.unified_reasoner`.

Design notes
------------

* The suite never touches ``sentence-transformers``. Every embedder is built
  with ``force_fallback=True`` so the deterministic 384-d fallback is what we
  exercise. This is also exactly the path production runs today (the dep
  isn't in ``requirements*.txt``).
* The fallback ``KnowledgeGraph`` (used when ``networkx`` is missing) is
  exercised via ``KnowledgeGraph(force_fallback=True)``. We additionally
  parametrise the integration tests so they cover *both* backends when
  ``networkx`` is available, but degrade gracefully when it isn't.
* HierarchicalPolicy integration tests inject a stub reasoner so they don't
  depend on the bootstrap concept set or any backend choice.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pytest

from services.hierarchical_policy import (
    HierarchicalPolicy,
    StrategicPlanner,
    TacticalPlanner,
    reset_hierarchical_policy,
)
from services.policy_engine import PolicyEngine, reset_policy_engine
from services.unified_reasoner import (
    EMBEDDING_DIM,
    GRAPH_AVAILABLE,
    CrossDomainImplication,
    DomainConcept,
    KnowledgeGraph,
    UnifiedEmbedder,
    UnifiedReasoner,
    _cosine_similarity,
    _stable_seed,
    get_unified_reasoner,
    reset_unified_reasoner,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    reset_unified_reasoner()
    reset_policy_engine()
    reset_hierarchical_policy()
    yield
    reset_unified_reasoner()
    reset_policy_engine()
    reset_hierarchical_policy()


@pytest.fixture()
def fallback_embedder() -> UnifiedEmbedder:
    return UnifiedEmbedder(force_fallback=True)


@pytest.fixture()
def fallback_graph() -> KnowledgeGraph:
    return KnowledgeGraph(force_fallback=True)


@pytest.fixture()
def reasoner(fallback_embedder: UnifiedEmbedder) -> UnifiedReasoner:
    """Bootstrapped reasoner using the fallback backends end-to-end."""
    return UnifiedReasoner(
        embedder=fallback_embedder,
        knowledge_graph=KnowledgeGraph(force_fallback=True),
        bootstrap=True,
    )


@pytest.fixture()
def empty_reasoner(fallback_embedder: UnifiedEmbedder) -> UnifiedReasoner:
    return UnifiedReasoner(
        embedder=fallback_embedder,
        knowledge_graph=KnowledgeGraph(force_fallback=True),
        bootstrap=False,
    )


# ===========================================================================
# Stable seed + cosine helpers
# ===========================================================================


def test_stable_seed_is_deterministic_across_calls():
    assert _stable_seed("hello") == _stable_seed("hello")
    assert _stable_seed("a") != _stable_seed("b")


def test_stable_seed_does_not_depend_on_pythonhashseed(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "12345")
    seed1 = _stable_seed("market crash")
    monkeypatch.setenv("PYTHONHASHSEED", "67890")
    seed2 = _stable_seed("market crash")
    assert seed1 == seed2


def test_cosine_similarity_identical_vectors_is_one():
    v = np.asarray([1.0, 2.0, 3.0])
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    a = np.asarray([1.0, 0.0])
    b = np.asarray([0.0, 1.0])
    assert _cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_handles_zero_vector():
    a = np.zeros(4)
    b = np.asarray([1.0, 0.0, 0.0, 0.0])
    assert _cosine_similarity(a, b) == 0.0


def test_cosine_similarity_handles_shape_mismatch():
    assert _cosine_similarity(np.zeros(3), np.zeros(5)) == 0.0


# ===========================================================================
# UnifiedEmbedder fallback
# ===========================================================================


def test_embedder_fallback_returns_correct_dimension(fallback_embedder: UnifiedEmbedder):
    vec = fallback_embedder.encode("market crash expected")
    assert vec.shape == (EMBEDDING_DIM,)
    assert vec.dtype == float


def test_embedder_fallback_is_unit_normalised(fallback_embedder: UnifiedEmbedder):
    vec = fallback_embedder.encode("foo")
    assert float(np.linalg.norm(vec)) == pytest.approx(1.0)


def test_embedder_fallback_is_deterministic(fallback_embedder: UnifiedEmbedder):
    a = fallback_embedder.encode("x" * 50)
    b = fallback_embedder.encode("x" * 50)
    np.testing.assert_array_equal(a, b)


def test_embedder_fallback_varies_by_input(fallback_embedder: UnifiedEmbedder):
    a = fallback_embedder.encode("apples")
    b = fallback_embedder.encode("oranges")
    # Different inputs produce different vectors
    assert not np.array_equal(a, b)


def test_embedder_fallback_does_not_mutate_global_numpy_state(fallback_embedder: UnifiedEmbedder):
    """The original spec used np.random.seed which would mutate the global
    numpy RNG. Verify by drawing from numpy after encoding - the result must
    not be a fixed function of the encoded text."""
    np.random.seed(42)
    expected = np.random.standard_normal(5)

    np.random.seed(42)
    fallback_embedder.encode("polluting input")
    actual = np.random.standard_normal(5)

    np.testing.assert_array_equal(expected, actual)


def test_embedder_batch_encode_shape(fallback_embedder: UnifiedEmbedder):
    arr = fallback_embedder.batch_encode(["a", "b", "c"])
    assert arr.shape == (3, EMBEDDING_DIM)


def test_embedder_batch_encode_empty_returns_empty_array(fallback_embedder: UnifiedEmbedder):
    arr = fallback_embedder.batch_encode([])
    assert arr.shape == (0, EMBEDDING_DIM)


def test_embedder_batch_encode_matches_single_encode(fallback_embedder: UnifiedEmbedder):
    single = fallback_embedder.encode("hello world")
    batched = fallback_embedder.batch_encode(["hello world"])
    np.testing.assert_array_equal(single, batched[0])


def test_embedder_force_fallback_reports_no_real_model(fallback_embedder: UnifiedEmbedder):
    assert fallback_embedder.using_real_model is False


def test_embedder_handles_non_string_input(fallback_embedder: UnifiedEmbedder):
    vec = fallback_embedder.encode(12345)  # type: ignore[arg-type]
    assert vec.shape == (EMBEDDING_DIM,)


# ===========================================================================
# DomainConcept
# ===========================================================================


def test_domain_concept_similarity_with_self_is_one(fallback_embedder: UnifiedEmbedder):
    emb = fallback_embedder.encode("trading market crash")
    c = DomainConcept("c1", "trading", "Market crash", "...", emb)
    assert c.similarity(c) == pytest.approx(1.0)


def test_domain_concept_similarity_between_different_concepts_is_finite(fallback_embedder):
    a = DomainConcept("a", "trading", "Bull market", "", fallback_embedder.encode("bull market"))
    b = DomainConcept("b", "personal", "Health focus", "", fallback_embedder.encode("health focus"))
    sim = a.similarity(b)
    assert -1.0 <= sim <= 1.0


# ===========================================================================
# KnowledgeGraph (fallback path)
# ===========================================================================


def test_graph_add_concept_records_in_concepts_dict(fallback_embedder, fallback_graph):
    c = DomainConcept("c1", "trading", "n", "d", fallback_embedder.encode("x"))
    fallback_graph.add_concept(c)
    assert "c1" in fallback_graph.concepts
    assert len(fallback_graph) == 1


def test_graph_add_concept_overwrites_with_warning(fallback_embedder, fallback_graph, caplog):
    c1 = DomainConcept("dup", "trading", "first", "d", fallback_embedder.encode("a"))
    c2 = DomainConcept("dup", "trading", "second", "d", fallback_embedder.encode("b"))
    fallback_graph.add_concept(c1)
    with caplog.at_level("INFO"):
        fallback_graph.add_concept(c2)
    assert fallback_graph.concepts["dup"].name == "second"


def test_graph_relationship_requires_existing_endpoints(fallback_embedder, fallback_graph):
    c = DomainConcept("a", "trading", "n", "d", fallback_embedder.encode("a"))
    fallback_graph.add_concept(c)
    assert fallback_graph.add_relationship("a", "missing", "causes", 0.5) is False
    assert fallback_graph.add_relationship("missing", "a", "causes", 0.5) is False


def test_graph_relationship_rejects_unknown_type(fallback_embedder, fallback_graph):
    for cid in ("a", "b"):
        fallback_graph.add_concept(
            DomainConcept(cid, "trading", cid, "", fallback_embedder.encode(cid))
        )
    assert fallback_graph.add_relationship("a", "b", "telepathy", 0.5) is False


def test_graph_relationship_clamps_strength(fallback_embedder, fallback_graph):
    for cid in ("a", "b"):
        fallback_graph.add_concept(
            DomainConcept(cid, "trading", cid, "", fallback_embedder.encode(cid))
        )
    fallback_graph.add_relationship("a", "b", "causes", 5.0)
    edge = dict(fallback_graph.graph["a"]["b"])
    assert edge["strength"] == pytest.approx(1.0)
    fallback_graph.add_relationship("a", "b", "causes", -1.0)
    edge = dict(fallback_graph.graph["a"]["b"])
    assert edge["strength"] == pytest.approx(0.0)


def test_graph_find_path_returns_full_chain(fallback_embedder, fallback_graph):
    for cid in ("a", "b", "c"):
        fallback_graph.add_concept(
            DomainConcept(cid, "trading", cid, "", fallback_embedder.encode(cid))
        )
    fallback_graph.add_relationship("a", "b", "causes", 0.5)
    fallback_graph.add_relationship("b", "c", "causes", 0.5)
    assert fallback_graph.find_path("a", "c") == ["a", "b", "c"]


def test_graph_find_path_returns_none_when_disconnected(fallback_embedder, fallback_graph):
    fallback_graph.add_concept(DomainConcept("a", "t", "a", "", fallback_embedder.encode("a")))
    fallback_graph.add_concept(DomainConcept("b", "t", "b", "", fallback_embedder.encode("b")))
    assert fallback_graph.find_path("a", "b") is None


def test_graph_find_path_returns_none_for_missing_node(fallback_embedder, fallback_graph):
    assert fallback_graph.find_path("ghost", "phantom") is None


def test_graph_get_neighbors_filters_by_relationship(fallback_embedder, fallback_graph):
    for cid in ("a", "b", "c"):
        fallback_graph.add_concept(
            DomainConcept(cid, "trading", cid, "", fallback_embedder.encode(cid))
        )
    fallback_graph.add_relationship("a", "b", "causes", 0.5)
    fallback_graph.add_relationship("a", "c", "correlates", 0.4)
    causes_only = fallback_graph.get_neighbors("a", relationship="causes")
    assert [n for n, _ in causes_only] == ["b"]
    all_n = fallback_graph.get_neighbors("a")
    assert sorted(n for n, _ in all_n) == ["b", "c"]


def test_graph_get_neighbors_unknown_concept_returns_empty(fallback_graph):
    assert fallback_graph.get_neighbors("ghost") == []


def test_graph_cross_domain_edges_only_includes_inter_domain(fallback_embedder, fallback_graph):
    fallback_graph.add_concept(DomainConcept("ta", "trading", "ta", "", fallback_embedder.encode("ta")))
    fallback_graph.add_concept(DomainConcept("tb", "trading", "tb", "", fallback_embedder.encode("tb")))
    fallback_graph.add_concept(DomainConcept("ba", "business", "ba", "", fallback_embedder.encode("ba")))
    fallback_graph.add_relationship("ta", "tb", "causes", 0.5)  # intra-domain
    fallback_graph.add_relationship("ta", "ba", "causes", 0.6)  # cross-domain
    cross = fallback_graph.get_cross_domain_edges()
    assert len(cross) == 1
    assert cross[0][0] == "ta" and cross[0][1] == "ba"


def test_fallback_graph_is_used_when_force_fallback(fallback_graph):
    assert fallback_graph.using_networkx is False


@pytest.mark.skipif(not GRAPH_AVAILABLE, reason="networkx not installed")
def test_networkx_graph_used_when_available():
    g = KnowledgeGraph(force_fallback=False)
    assert g.using_networkx is True


# ===========================================================================
# UnifiedReasoner - bootstrap + structure
# ===========================================================================


def test_reasoner_bootstrap_loads_default_concepts(reasoner: UnifiedReasoner):
    assert len(reasoner.knowledge_graph) == 11  # 3 trading + 3 business + 3 personal + 2 system
    assert reasoner.knowledge_graph.edge_count() >= 7


def test_reasoner_can_skip_bootstrap(empty_reasoner: UnifiedReasoner):
    assert len(empty_reasoner.knowledge_graph) == 0
    assert empty_reasoner.knowledge_graph.edge_count() == 0


def test_reasoner_bootstrap_includes_all_known_domains(reasoner: UnifiedReasoner):
    domains_present = {c.domain for c in reasoner.knowledge_graph.concepts.values()}
    assert {"trading", "business", "personal", "system"} <= domains_present


# ===========================================================================
# UnifiedReasoner - semantic search
# ===========================================================================


def test_reasoner_semantic_search_returns_top_k_sorted(reasoner: UnifiedReasoner):
    out = reasoner.reason("market crash incoming")
    sims = [c["similarity"] for c in out["relevant_concepts"]]
    assert sims == sorted(sims, reverse=True)
    assert len(sims) <= 5


def test_reasoner_semantic_search_filters_by_domain(reasoner: UnifiedReasoner):
    out = reasoner.reason("market crash incoming", domains=["trading"])
    assert {c["domain"] for c in out["relevant_concepts"]} == {"trading"}


def test_reasoner_semantic_search_top_k_zero_returns_empty(empty_reasoner: UnifiedReasoner):
    empty_reasoner.add_concept("trading", "Test", "Test concept")
    out = empty_reasoner.reason("query", top_k=0)
    assert out["relevant_concepts"] == []


def test_reasoner_empty_query_returns_empty_report(reasoner: UnifiedReasoner):
    out = reasoner.reason("")
    assert out["relevant_concepts"] == []
    assert out["primary_action"]["action"] == "no_action"
    assert out["implications"] == []


def test_reasoner_whitespace_query_treated_as_empty(reasoner: UnifiedReasoner):
    out = reasoner.reason("   \n\t  ")
    assert out["relevant_concepts"] == []


def test_reasoner_reason_does_not_mutate_default_domains(reasoner: UnifiedReasoner):
    """Regression for the spec's mutable-default bug: calling reason() twice
    with different domain sets must not have the second call affect the
    first's domain list."""
    out_a = reasoner.reason("query a", domains=["trading"])
    out_b = reasoner.reason("query b", domains=["business"])
    assert out_a["domains_considered"] == ["trading"]
    assert out_b["domains_considered"] == ["business"]


# ===========================================================================
# UnifiedReasoner - causal inference + impact classification
# ===========================================================================


def test_reasoner_causal_inference_finds_cross_domain_implications(empty_reasoner: UnifiedReasoner):
    """The fallback embedder is semantically meaningless, so we can't rely on
    'market crash' returning the trading concept top-ranked. We instead use
    a controlled empty reasoner with two concepts whose ``f"{name}. {desc}"``
    is queried verbatim - giving cosine=1.0 deterministically."""
    empty_reasoner.add_concept("trading", "Market crash", "downturn")
    empty_reasoner.add_concept("business", "Cash crunch", "liquidity problem")
    empty_reasoner.learn_relationship(
        "trading_market_crash", "business_cash_crunch", "causes", 0.7
    )
    out = empty_reasoner.reason("Market crash. downturn")
    targets = {(impl["source_domain"], impl["target_domain"]) for impl in out["implications"]}
    assert ("trading", "business") in targets


def test_reasoner_causal_inference_skips_intra_domain_neighbours(empty_reasoner: UnifiedReasoner):
    empty_reasoner.add_concept("trading", "Storm", "trading storm")
    empty_reasoner.add_concept("trading", "Calm", "trading calm")
    empty_reasoner.learn_relationship("trading_storm", "trading_calm", "causes", 0.9)
    out = empty_reasoner.reason("storm")
    assert out["implications"] == []  # same-domain edges do NOT generate implications


def test_reasoner_implications_dedupe(empty_reasoner: UnifiedReasoner):
    empty_reasoner.add_concept("trading", "Crash", "market crash")
    empty_reasoner.add_concept("business", "Crunch", "cash crunch problem")
    empty_reasoner.learn_relationship("trading_crash", "business_crunch", "causes", 0.9)
    out = empty_reasoner.reason("crash")
    assert len(out["implications"]) == 1


def test_reasoner_impact_classifier_negative_to_negative_is_negative(reasoner: UnifiedReasoner):
    src = reasoner.knowledge_graph.get_concept("trading_market_crash")
    dst = reasoner.knowledge_graph.get_concept("business_cash_crunch")
    assert src is not None and dst is not None
    assert UnifiedReasoner._classify_impact(src, dst) == "negative"


def test_reasoner_impact_classifier_neutral_when_only_one_side_negative(empty_reasoner):
    empty_reasoner.add_concept("trading", "Bull rally", "market boom")
    empty_reasoner.add_concept("business", "Cash crunch", "liquidity problem")
    bull = empty_reasoner.knowledge_graph.get_concept("trading_bull_rally")
    crunch = empty_reasoner.knowledge_graph.get_concept("business_cash_crunch")
    assert bull is not None and crunch is not None
    assert UnifiedReasoner._classify_impact(bull, crunch) == "neutral"


# ===========================================================================
# UnifiedReasoner - recommendations
# ===========================================================================


def test_reasoner_primary_action_uses_concept_to_action_map(empty_reasoner: UnifiedReasoner):
    """Verbatim concept text guarantees cosine=1.0 with the fallback embedder
    so the trading concept is the deterministic top-1 ranked result."""
    empty_reasoner.add_concept("trading", "Market crash imminent", "huge downturn")
    out = empty_reasoner.reason("Market crash imminent. huge downturn")
    primary = out["primary_action"]
    assert primary["action"] == "liquidate_positions"  # 'crash' keyword in name
    assert primary["domain"] == "trading"


def test_reasoner_primary_action_falls_back_to_monitor(empty_reasoner: UnifiedReasoner):
    empty_reasoner.add_concept("system", "Generic event", "an event with no keyword match")
    # Verbatim text + explicit domains so the system concept is matched even
    # if the default domain set ever changes again.
    out = empty_reasoner.reason(
        "Generic event. an event with no keyword match", domains=["system"]
    )
    assert out["primary_action"]["action"] == "monitor"


def test_reasoner_secondary_effects_filtered_by_magnitude(empty_reasoner):
    empty_reasoner.add_concept("trading", "Trigger", "downturn risk")
    empty_reasoner.add_concept("business", "Cash crunch", "liquidity problem")
    # Strength 0.1 * any-relevance < 0.3 threshold => no secondary effect
    empty_reasoner.learn_relationship("trading_trigger", "business_cash_crunch", "causes", 0.1)
    out = empty_reasoner.reason("trigger")
    assert out["secondary_effects"] == []


def test_reasoner_secondary_effects_include_strong_impacts(empty_reasoner):
    """Verbatim text query gives the trading source concept cosine=1.0 so
    magnitude = 1.0 * 0.95 = 0.95, well above the 0.3 secondary-effect floor."""
    empty_reasoner.add_concept("trading", "Crash trigger", "downturn ahead")
    empty_reasoner.add_concept("business", "Cash crunch", "liquidity problem")
    empty_reasoner.learn_relationship(
        "trading_crash_trigger", "business_cash_crunch", "causes", 0.95
    )
    out = empty_reasoner.reason("Crash trigger. downturn ahead")
    actions = [s["action"] for s in out["secondary_effects"]]
    assert any(a.startswith("mitigate_") for a in actions)


def test_reasoner_no_relevant_returns_no_action(empty_reasoner: UnifiedReasoner):
    out = empty_reasoner.reason("anything")
    assert out["primary_action"]["domain"] == "unknown"
    assert out["primary_action"]["action"] == "no_action"


# ===========================================================================
# UnifiedReasoner - learning new concepts and relationships
# ===========================================================================


def test_reasoner_add_concept_creates_id(empty_reasoner: UnifiedReasoner):
    c = empty_reasoner.add_concept("business", "New Product Launch", "Bringing product to market")
    assert c.concept_id == "business_new_product_launch"
    assert c.domain == "business"
    assert c.embedding.shape == (EMBEDDING_DIM,)
    assert empty_reasoner.knowledge_graph.get_concept(c.concept_id) is c


def test_reasoner_add_concept_normalises_special_chars(empty_reasoner: UnifiedReasoner):
    c = empty_reasoner.add_concept("trading", "BTC/USD spike!", "crypto pair surge")
    assert "/" not in c.concept_id
    assert "!" not in c.concept_id
    assert c.concept_id.startswith("trading_")


def test_reasoner_add_concept_rejects_empty_name(empty_reasoner: UnifiedReasoner):
    with pytest.raises(ValueError):
        empty_reasoner.add_concept("trading", "", "desc")
    with pytest.raises(ValueError):
        empty_reasoner.add_concept("trading", "   ", "desc")


def test_reasoner_add_concept_rejects_empty_domain(empty_reasoner: UnifiedReasoner):
    with pytest.raises(ValueError):
        empty_reasoner.add_concept("", "Name", "desc")


def test_reasoner_learn_relationship_returns_true_on_success(empty_reasoner):
    empty_reasoner.add_concept("trading", "A", "")
    empty_reasoner.add_concept("business", "B", "")
    assert empty_reasoner.learn_relationship("trading_a", "business_b", "causes", 0.5) is True


def test_reasoner_learn_relationship_returns_false_when_endpoint_missing(empty_reasoner):
    empty_reasoner.add_concept("trading", "A", "")
    assert empty_reasoner.learn_relationship("trading_a", "ghost", "causes", 0.5) is False


# ===========================================================================
# Singleton
# ===========================================================================


def test_singleton_returns_same_instance(monkeypatch):
    # Avoid loading sentence-transformers in the singleton's default ctor.
    monkeypatch.setattr("services.unified_reasoner.EMBEDDINGS_AVAILABLE", False)
    a = get_unified_reasoner()
    b = get_unified_reasoner()
    assert a is b


def test_reset_singleton_returns_new_instance(monkeypatch):
    monkeypatch.setattr("services.unified_reasoner.EMBEDDINGS_AVAILABLE", False)
    a = get_unified_reasoner()
    reset_unified_reasoner()
    b = get_unified_reasoner()
    assert a is not b


# ===========================================================================
# CrossDomainImplication
# ===========================================================================


def test_cross_domain_implication_as_dict_round_trips():
    impl = CrossDomainImplication(
        source_domain="trading", target_domain="business",
        source_concept="Crash", target_concept="Cash crunch",
        impact_type="negative", magnitude=0.6, confidence=0.5, reasoning="r",
    )
    d = impl.as_dict()
    assert d["source_domain"] == "trading"
    assert d["target_domain"] == "business"
    assert d["impact"] == "negative"
    assert d["magnitude"] == pytest.approx(0.6)


# ===========================================================================
# HierarchicalPolicy integration
# ===========================================================================


class _StubReasoner:
    """Records calls and returns a fixed report. Lets us assert wiring without
    booting the real UnifiedReasoner singleton."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def reason(self, query: str, domains: Any = None, **_: Any) -> dict[str, Any]:
        self.calls.append((query, domains))
        return {
            "implications": [{"impact": "negative", "magnitude": 0.7}],
            "domains_affected": ["business", "personal"],
            "relevant_concepts": [{"id": "x", "domain": "trading"}],
            "primary_action": {"domain": "trading", "action": "liquidate_positions", "confidence": 0.9},
            "secondary_effects": [{"domain": "business", "action": "mitigate_cash_crunch"}],
        }


@pytest.fixture()
def fresh_engine() -> PolicyEngine:
    return PolicyEngine(n_features=20, alpha=1.0)


def test_hierarchical_decide_does_not_call_reasoner_when_flag_off(fresh_engine):
    stub = _StubReasoner()
    h = HierarchicalPolicy(
        operational=fresh_engine,
        cross_domain_reasoner=stub,
        goals_provider=lambda _ctx: [],
    )
    out = h.decide({"intent": "x", "domain": "trading"}, horizon="immediate")
    assert "cross_domain" not in out
    assert stub.calls == []


def test_hierarchical_decide_invokes_reasoner_when_flag_on(fresh_engine):
    stub = _StubReasoner()
    h = HierarchicalPolicy(
        operational=fresh_engine,
        cross_domain_reasoner=stub,
        goals_provider=lambda _ctx: [],
    )
    out = h.decide(
        {"intent": "market crash incoming", "domain": "trading", "check_cross_domain": True},
        horizon="immediate",
    )
    assert stub.calls == [("market crash incoming", None)]
    assert "cross_domain" in out
    assert out["cross_domain"]["domains_affected"] == ["business", "personal"]


def test_hierarchical_decide_does_not_mutate_caller_context(fresh_engine):
    """Even with cross-domain enrichment on, the caller's input dict must not
    grow new keys (we enrich a local copy)."""
    stub = _StubReasoner()
    h = HierarchicalPolicy(
        operational=fresh_engine,
        cross_domain_reasoner=stub,
        goals_provider=lambda _ctx: [],
    )
    user_ctx = {"intent": "crash", "check_cross_domain": True}
    h.decide(user_ctx, horizon="immediate")
    assert "cross_domain_implications" not in user_ctx
    assert "affected_domains" not in user_ctx


def test_hierarchical_decide_passes_explicit_domains_to_reasoner(fresh_engine):
    stub = _StubReasoner()
    h = HierarchicalPolicy(
        operational=fresh_engine,
        cross_domain_reasoner=stub,
        goals_provider=lambda _ctx: [],
    )
    h.decide(
        {
            "intent": "scenario",
            "check_cross_domain": True,
            "cross_domain_domains": ["trading", "business"],
        },
        horizon="immediate",
    )
    assert stub.calls[0][1] == ["trading", "business"]


def test_hierarchical_strategic_decision_includes_cross_domain_when_enabled(fresh_engine, small_goals):
    stub = _StubReasoner()
    h = HierarchicalPolicy(
        operational=fresh_engine,
        strategic=StrategicPlanner(simulation_budget=8),
        tactical=TacticalPlanner(),
        cross_domain_reasoner=stub,
        goals_provider=lambda _ctx: list(small_goals),
    )
    out = h.decide(
        {"intent": "expand market share", "check_cross_domain": True, "organization_id": 1},
        horizon="strategic",
    )
    assert out["layer"] == "strategic"
    assert "cross_domain" in out
    assert stub.calls[0][0] == "expand market share"


def test_hierarchical_decide_skips_enrichment_when_query_empty(fresh_engine):
    stub = _StubReasoner()
    h = HierarchicalPolicy(
        operational=fresh_engine,
        cross_domain_reasoner=stub,
        goals_provider=lambda _ctx: [],
    )
    out = h.decide({"check_cross_domain": True}, horizon="immediate")
    assert "cross_domain" not in out
    assert stub.calls == []


@pytest.fixture()
def small_goals():
    """Reuse the same goal shape as the hierarchical tests."""
    from datetime import datetime, timedelta, timezone

    from services.hierarchical_policy import StrategicGoal

    now = datetime.now(timezone.utc)
    return [
        StrategicGoal(goal_id="g1", description="Grow", domain="trading",
                      target_value=1.0, current_value=0.0,
                      deadline=now + timedelta(days=30), priority=0.8),
        StrategicGoal(goal_id="g2", description="Expand", domain="business",
                      target_value=1.0, current_value=0.0,
                      deadline=now + timedelta(days=60), priority=0.6),
    ]


# ===========================================================================
# Full pipeline sanity
# ===========================================================================


def test_full_pipeline_market_crash_query(reasoner: UnifiedReasoner):
    """Use verbatim bootstrap text so the trading_market_crash concept is
    deterministically the cosine=1.0 top-1 even with the fallback embedder."""
    out = reasoner.reason(
        "Market crash expected. Stock market experiencing significant downturn"
    )
    assert out["primary_action"]["domain"] == "trading"
    # Bootstrap edge market_crash -> business_cash_crunch fires.
    assert "business" in out["domains_affected"]
    assert out["timestamp"]


def test_full_pipeline_demand_spike_query(reasoner: UnifiedReasoner):
    """Same approach: verbatim bootstrap text => deterministic top-1."""
    out = reasoner.reason(
        "High customer demand. Sudden increase in product or service demand"
    )
    assert out["primary_action"]["domain"] == "business"
    assert out["primary_action"]["action"] == "scale_production"
    # Bootstrap edge demand_spike -> personal_time_crunch fires.
    assert "personal" in out["domains_affected"]


def test_full_pipeline_with_constrained_domains_no_cross_implications(reasoner):
    out = reasoner.reason("market crash expected", domains=["trading"])
    # Implications target other domains, but they're filtered out of relevant
    # concepts. Implications can still be empty because the only relevant
    # concept is trading and its causal neighbour (business_cash_crunch) was
    # not in the relevant set.
    assert all(impl["target_domain"] != "trading" for impl in out["implications"])
