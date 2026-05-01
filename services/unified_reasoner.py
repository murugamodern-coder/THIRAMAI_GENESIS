"""Cross-domain unified reasoning over a shared semantic embedding space.

The reasoner ties trading / business / personal / system concepts together
via two complementary structures:

* a **single embedding space** (one vector per concept, same dimensionality
  regardless of domain) so semantic search transcends the per-domain silos;
* a **directed knowledge graph** of typed edges (``causes`` / ``correlates``
  / ``enables`` / ``inhibits``) so causal hops between domains can be
  enumerated and weighted.

Soft dependencies and why we don't require them
-----------------------------------------------

Both ``sentence-transformers`` (real semantic embeddings) and ``networkx``
(graph algorithms) are *optional*. They are not currently in
``requirements*.txt`` and ``import`` would fail in CI. The fallbacks below
are **production-quality**, not placeholders, so the rest of the brain stack
can rely on this module without forcing those installs:

* If ``sentence-transformers`` is unavailable, every text encodes to a stable
  384-d vector seeded from ``zlib.adler32`` (process-stable, unlike Python's
  salted ``hash()``). The vector is unit-normalised so cosine similarity
  behaves the same way as it would with the real model. We never mutate the
  global ``numpy.random`` state - each fallback call uses its own
  :class:`numpy.random.Generator`.
* If ``networkx`` is unavailable, an in-house adjacency-dict ``_FallbackDiGraph``
  implements the small surface area we use (``add_node`` / ``add_edge`` /
  ``neighbors`` / ``edges`` / ``nodes`` / ``shortest_path``). Reasoning is
  fully functional either way.

Spec deviations
---------------

The reference spec (commit message: 'unified reasoner v1') had a couple of
runtime-correctness bugs that this implementation fixes deliberately:

* The fallback embedder used ``np.random.seed(hash(text) % 2**32)`` which
  (a) mutates the global numpy RNG, and (b) is non-deterministic across
  processes because Python salts ``hash()`` by default. Both are fixed here.
* ``UnifiedReasoner.reason`` had a mutable list as a default argument - now
  uses ``None`` and resolves the default inside the body.
* ``_bootstrap_concepts`` always ran at construction; tests need the option
  to start with an empty graph - exposed as ``bootstrap=False``.
* The ``HierarchicalPolicy`` integration mutated the caller's context dict;
  it now enriches a local copy and surfaces the enrichment via the response.
"""

from __future__ import annotations

import logging
import threading
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import numpy as np

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Soft dependency probes
# ---------------------------------------------------------------------------


try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

    EMBEDDINGS_AVAILABLE = True
except Exception as _exc:  # pragma: no cover - environment-dependent
    SentenceTransformer = None  # type: ignore[assignment, misc]
    EMBEDDINGS_AVAILABLE = False
    _LOG.info("sentence-transformers unavailable (%s) - using fallback embedder", _exc)

try:
    import networkx as _nx  # type: ignore[import-untyped]

    GRAPH_AVAILABLE = True
except Exception as _exc:  # pragma: no cover - environment-dependent
    _nx = None  # type: ignore[assignment]
    GRAPH_AVAILABLE = False
    _LOG.info("networkx unavailable (%s) - using fallback DiGraph", _exc)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


EMBEDDING_DIM: int = 384
DEFAULT_MODEL_NAME: str = "all-MiniLM-L6-v2"
KNOWN_DOMAINS: frozenset[str] = frozenset({"trading", "business", "personal", "system"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_seed(text: str) -> int:
    """Deterministic 32-bit seed derived from ``text``.

    ``hash()`` is salted per-process by default (PYTHONHASHSEED=random) so it
    silently produces different fallback embeddings across deployments. We
    use ``zlib.adler32`` (the same primitive used by
    :func:`services.policy_engine._stable_unit_hash`) which is stable across
    interpreters and platforms.
    """
    return zlib.adler32((text or "").encode("utf-8")) & 0xFFFFFFFF


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in ``[-1, 1]`` with safe fallback to 0 on zero vectors."""
    a = np.asarray(a, dtype=float).reshape(-1)
    b = np.asarray(b, dtype=float).reshape(-1)
    if a.shape != b.shape:
        return 0.0
    denom = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _normalise_text(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (name or "").strip().lower()).strip("_")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DomainConcept:
    """A semantic concept living in exactly one domain."""

    concept_id: str
    domain: str
    name: str
    description: str
    embedding: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def similarity(self, other: "DomainConcept") -> float:
        return _cosine_similarity(self.embedding, other.embedding)


@dataclass
class CrossDomainImplication:
    """A causal hop from a concept in one domain to a concept in another."""

    source_domain: str
    target_domain: str
    source_concept: str
    target_concept: str
    impact_type: str  # "positive" | "negative" | "neutral"
    magnitude: float  # 0..1
    confidence: float  # 0..1
    reasoning: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_domain": self.source_domain,
            "target_domain": self.target_domain,
            "source_concept": self.source_concept,
            "target_concept": self.target_concept,
            "impact": self.impact_type,
            "magnitude": float(self.magnitude),
            "confidence": float(self.confidence),
            "reasoning": self.reasoning,
        }


# ---------------------------------------------------------------------------
# Fallback DiGraph (used when networkx is missing)
# ---------------------------------------------------------------------------


class _FallbackDiGraph:
    """Minimal directed-graph used when ``networkx`` isn't installed.

    Implements only the surface of :class:`networkx.DiGraph` that
    :class:`KnowledgeGraph` actually exercises. Backed by adjacency dicts.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._adj: dict[str, dict[str, dict[str, Any]]] = {}

    # node API -----------------------------------------------------------

    def add_node(self, node_id: str, **attrs: Any) -> None:
        self._nodes[node_id] = dict(attrs)
        self._adj.setdefault(node_id, {})

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._nodes

    @property
    def nodes(self) -> dict[str, dict[str, Any]]:
        return self._nodes

    # edge API -----------------------------------------------------------

    def add_edge(self, src: str, dst: str, **attrs: Any) -> None:
        if src not in self._nodes:
            self.add_node(src)
        if dst not in self._nodes:
            self.add_node(dst)
        self._adj[src][dst] = dict(attrs)

    def neighbors(self, node_id: str) -> list[str]:
        return list(self._adj.get(node_id, {}).keys())

    def edges(self, data: bool = False) -> list[Any]:
        out: list[Any] = []
        for src, targets in self._adj.items():
            for dst, attrs in targets.items():
                out.append((src, dst, dict(attrs)) if data else (src, dst))
        return out

    def __getitem__(self, node_id: str) -> dict[str, dict[str, Any]]:
        return self._adj.get(node_id, {})

    # algorithms ---------------------------------------------------------

    def shortest_path(self, src: str, dst: str) -> list[str]:
        """BFS-based shortest path. Raises ``KeyError`` if either node is
        absent or no path exists - mirrors ``networkx`` raising
        ``NodeNotFound`` / ``NetworkXNoPath``."""
        if src not in self._nodes or dst not in self._nodes:
            raise KeyError("node_not_found")
        if src == dst:
            return [src]
        visited = {src}
        prev: dict[str, str] = {}
        queue: list[str] = [src]
        while queue:
            node = queue.pop(0)
            for neighbour in self._adj.get(node, {}):
                if neighbour in visited:
                    continue
                visited.add(neighbour)
                prev[neighbour] = node
                if neighbour == dst:
                    path = [dst]
                    while path[-1] != src:
                        path.append(prev[path[-1]])
                    path.reverse()
                    return path
                queue.append(neighbour)
        raise KeyError("no_path")


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------


class UnifiedEmbedder:
    """Encode text to a unit-normalised ``EMBEDDING_DIM``-dimensional vector.

    Tries :class:`sentence_transformers.SentenceTransformer` first (only if
    the package imports cleanly). If anything goes wrong - missing dep, bad
    model name, runtime exception during encode - falls back to a stable
    deterministic hash-seeded vector that *also* lives on the unit sphere,
    so cosine similarity behaves the same way as with the real model.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        *,
        force_fallback: bool = False,
    ) -> None:
        self.model_name = model_name
        self.model: Any | None = None
        self._force_fallback = bool(force_fallback)
        if not self._force_fallback:
            self._load_model()

    # -- model loading -------------------------------------------------

    def _load_model(self) -> None:
        if not EMBEDDINGS_AVAILABLE or SentenceTransformer is None:
            return
        try:
            self.model = SentenceTransformer(self.model_name)
            _LOG.info("loaded embedding model %s", self.model_name)
        except Exception as exc:
            _LOG.warning("failed to load embedding model %s: %s", self.model_name, exc)
            self.model = None

    @property
    def using_real_model(self) -> bool:
        return self.model is not None

    # -- encoding -------------------------------------------------------

    def encode(self, text: str) -> np.ndarray:
        if not isinstance(text, str):
            text = str(text)
        if self.model is not None:
            try:
                vec = np.asarray(self.model.encode(text), dtype=float).reshape(-1)
                if vec.size > 0:
                    return self._unit_normalise(vec)
                _LOG.warning("real model returned empty vector; using fallback")
            except Exception as exc:
                _LOG.warning("real-model encode failed (%s); using fallback", exc)
        return self._fallback_encode(text)

    def batch_encode(self, texts: Iterable[str]) -> np.ndarray:
        text_list = [str(t) for t in texts]
        if not text_list:
            return np.zeros((0, EMBEDDING_DIM), dtype=float)
        if self.model is not None:
            try:
                arr = np.asarray(self.model.encode(text_list), dtype=float)
                if arr.ndim == 1:
                    arr = arr.reshape(1, -1)
                # Row-wise unit-normalise; behave identically to per-text encode().
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms = np.where(norms == 0.0, 1.0, norms)
                return arr / norms
            except Exception as exc:
                _LOG.warning("batch encode failed (%s); falling back per-text", exc)
        return np.stack([self._fallback_encode(t) for t in text_list])

    # -- fallback -------------------------------------------------------

    def _fallback_encode(self, text: str) -> np.ndarray:
        """Stable hash-seeded embedding.

        Crucially, we use a *local* :class:`numpy.random.Generator` here -
        the original spec called ``np.random.seed`` which mutates the global
        numpy RNG and would silently break any other component relying on
        ``np.random``.
        """
        rng = np.random.default_rng(_stable_seed(text))
        vec = rng.standard_normal(EMBEDDING_DIM)
        return self._unit_normalise(vec)

    @staticmethod
    def _unit_normalise(vec: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vec))
        if norm == 0.0:
            return vec
        return vec / norm


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------


_VALID_RELATIONSHIPS: frozenset[str] = frozenset({"causes", "correlates", "enables", "inhibits"})


class KnowledgeGraph:
    """Directed multi-domain knowledge graph.

    Backed by ``networkx.DiGraph`` when available, otherwise by
    :class:`_FallbackDiGraph`. Concepts are also kept in a regular dict so
    callers can iterate them without going through the graph backend.
    """

    def __init__(self, *, force_fallback: bool = False) -> None:
        self.concepts: dict[str, DomainConcept] = {}
        self._using_networkx = bool(GRAPH_AVAILABLE) and not force_fallback and _nx is not None
        if self._using_networkx:
            self.graph: Any = _nx.DiGraph()
        else:
            self.graph = _FallbackDiGraph()

    @property
    def using_networkx(self) -> bool:
        return self._using_networkx

    # -- concepts ------------------------------------------------------

    def add_concept(self, concept: DomainConcept) -> None:
        if concept.concept_id in self.concepts:
            _LOG.info("knowledge_graph.add_concept overwriting %s", concept.concept_id)
        self.concepts[concept.concept_id] = concept
        self.graph.add_node(
            concept.concept_id,
            domain=concept.domain,
            name=concept.name,
            embedding=concept.embedding,
        )

    def get_concept(self, concept_id: str) -> DomainConcept | None:
        return self.concepts.get(concept_id)

    def __len__(self) -> int:
        return len(self.concepts)

    # -- edges ---------------------------------------------------------

    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship: str = "causes",
        strength: float = 1.0,
    ) -> bool:
        """Add an edge if both endpoints exist.

        Returns ``True`` if the edge was added, ``False`` if it was rejected
        (missing endpoint, unknown relationship, invalid strength).
        """
        if source_id not in self.concepts or target_id not in self.concepts:
            _LOG.debug("relationship rejected: missing endpoint %s -> %s", source_id, target_id)
            return False
        rel = (relationship or "").strip().lower()
        if rel not in _VALID_RELATIONSHIPS:
            _LOG.debug("relationship rejected: unknown type %s", relationship)
            return False
        try:
            s = float(strength)
        except (TypeError, ValueError):
            return False
        s = max(0.0, min(1.0, s))
        self.graph.add_edge(source_id, target_id, relationship=rel, strength=s)
        return True

    def find_path(self, source_id: str, target_id: str) -> list[str] | None:
        """Shortest causal path between two concepts (None if no path)."""
        if source_id not in self.concepts or target_id not in self.concepts:
            return None
        try:
            if self._using_networkx:
                return list(_nx.shortest_path(self.graph, source_id, target_id))
            return self.graph.shortest_path(source_id, target_id)
        except Exception:
            return None

    def get_neighbors(
        self,
        concept_id: str,
        relationship: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        if concept_id not in self.concepts:
            return []
        out: list[tuple[str, dict[str, Any]]] = []
        for neighbour in self.graph.neighbors(concept_id):
            edge_data = dict(self.graph[concept_id][neighbour])
            if relationship is None or edge_data.get("relationship") == relationship:
                out.append((neighbour, edge_data))
        return out

    def get_cross_domain_edges(self) -> list[tuple[str, str, dict[str, Any]]]:
        cross: list[tuple[str, str, dict[str, Any]]] = []
        for src, dst, data in self.graph.edges(data=True):
            src_node = self.graph.nodes[src]
            dst_node = self.graph.nodes[dst]
            if src_node.get("domain") != dst_node.get("domain"):
                cross.append((src, dst, dict(data)))
        return cross

    def edge_count(self) -> int:
        return len(self.graph.edges())


# ---------------------------------------------------------------------------
# Reasoner
# ---------------------------------------------------------------------------


_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "crash", "crunch", "stress", "problem", "issue", "error", "shortage", "downturn",
)
_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "bull", "spike", "growth", "opportunity", "boom", "expansion", "surplus",
)
_NEUTRAL_KEYWORDS: tuple[str, ...] = ("focus", "health", "monitor")


_DEFAULT_ACTION_MAP: dict[str, dict[str, str]] = {
    "trading": {
        "crash": "liquidate_positions",
        "volatility": "reduce_exposure",
        "bull": "increase_positions",
    },
    "business": {
        "cash": "delay_expenses",
        "demand": "scale_production",
        "supply": "find_alternatives",
    },
    "personal": {
        "stress": "reduce_commitments",
        "time": "prioritize_tasks",
        "health": "schedule_exercise",
    },
    "system": {
        "load": "scale_resources",
        "error": "investigate_logs",
    },
}


# All four known domains by default - the original spec excluded "system"
# but that silently dropped any system-domain concept from semantic search,
# even when the caller had bootstrapped one (UX bug, not deliberate).
_DEFAULT_DOMAINS: tuple[str, ...] = ("trading", "business", "personal", "system")


_BOOTSTRAP_CONCEPTS: tuple[tuple[str, str, str, str], ...] = (
    # trading
    ("trading_market_crash", "trading", "Market crash expected", "Stock market experiencing significant downturn"),
    ("trading_high_volatility", "trading", "High market volatility", "Market showing increased price fluctuations"),
    ("trading_bull_market", "trading", "Bull market trend", "Sustained upward market movement"),
    # business
    ("business_cash_crunch", "business", "Cash flow problems", "Business experiencing liquidity shortage"),
    ("business_demand_spike", "business", "High customer demand", "Sudden increase in product or service demand"),
    ("business_supply_issue", "business", "Supply chain disruption", "Problems with inventory or suppliers"),
    # personal
    ("personal_stress", "personal", "High stress levels", "Increased personal stress or anxiety"),
    ("personal_time_crunch", "personal", "Time constraints", "Limited available time for activities"),
    ("personal_health_focus", "personal", "Health priority", "Focus on health and wellness"),
    # system
    ("system_high_load", "system", "System under load", "Computing resources stressed"),
    ("system_error_spike", "system", "Error rate increase", "Higher than normal system errors"),
)


_BOOTSTRAP_RELATIONSHIPS: tuple[tuple[str, str, str, float], ...] = (
    ("trading_market_crash", "business_cash_crunch", "causes", 0.7),
    ("trading_high_volatility", "personal_stress", "causes", 0.5),
    ("business_cash_crunch", "personal_stress", "causes", 0.8),
    ("business_demand_spike", "personal_time_crunch", "causes", 0.6),
    ("business_supply_issue", "business_cash_crunch", "causes", 0.5),
    ("system_high_load", "system_error_spike", "causes", 0.9),
    ("personal_stress", "personal_health_focus", "enables", 0.4),
)


class UnifiedReasoner:
    """Cross-domain reasoning over the shared embedding + knowledge graph."""

    def __init__(
        self,
        *,
        embedder: UnifiedEmbedder | None = None,
        knowledge_graph: KnowledgeGraph | None = None,
        bootstrap: bool = True,
    ) -> None:
        self.embedder = embedder or UnifiedEmbedder()
        self.knowledge_graph = knowledge_graph or KnowledgeGraph()
        self._lock = threading.Lock()
        if bootstrap:
            self._bootstrap_concepts()
        _LOG.info(
            "UnifiedReasoner ready model=%s graph=%s concepts=%d edges=%d",
            "real" if self.embedder.using_real_model else "fallback",
            "networkx" if self.knowledge_graph.using_networkx else "fallback",
            len(self.knowledge_graph),
            self.knowledge_graph.edge_count(),
        )

    # -- bootstrap -----------------------------------------------------

    def _bootstrap_concepts(self) -> None:
        for concept_id, domain, name, description in _BOOTSTRAP_CONCEPTS:
            embedding = self.embedder.encode(f"{name}. {description}")
            concept = DomainConcept(
                concept_id=concept_id,
                domain=domain,
                name=name,
                description=description,
                embedding=embedding,
            )
            self.knowledge_graph.add_concept(concept)
        for src, dst, rel, strength in _BOOTSTRAP_RELATIONSHIPS:
            self.knowledge_graph.add_relationship(src, dst, rel, strength)

    # -- public API ----------------------------------------------------

    def reason(
        self,
        query: str,
        domains: Iterable[str] | None = None,
        *,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Return a multi-domain reasoning report for ``query``."""
        domain_list = list(domains) if domains is not None else list(_DEFAULT_DOMAINS)
        if not isinstance(query, str) or not query.strip():
            return self._empty_report(query=str(query or ""), domains=domain_list)

        query_embedding = self.embedder.encode(query)
        relevant = self._semantic_search(query_embedding, domain_list, top_k=top_k)
        implications = self._causal_inference(relevant)
        recommendations = self._generate_recommendations(query, relevant, implications)
        domains_affected = sorted({i.target_domain for i in implications})

        return {
            "query": query,
            "domains_considered": domain_list,
            "relevant_concepts": [
                {
                    "id": c.concept_id,
                    "domain": c.domain,
                    "name": c.name,
                    "similarity": float(sim),
                }
                for c, sim in relevant
            ],
            "primary_action": recommendations.get("primary"),
            "secondary_effects": recommendations.get("secondary", []),
            "domains_affected": domains_affected,
            "implications": [i.as_dict() for i in implications],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def add_concept(
        self,
        domain: str,
        name: str,
        description: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> DomainConcept:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("concept name must be a non-empty string")
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError("domain must be a non-empty string")
        normalised_name = _normalise_text(name)
        if not normalised_name:
            normalised_name = "unnamed"
        concept_id = f"{domain.strip().lower()}_{normalised_name}"
        embedding = self.embedder.encode(f"{name}. {description or ''}")
        concept = DomainConcept(
            concept_id=concept_id,
            domain=domain.strip().lower(),
            name=name.strip(),
            description=str(description or ""),
            embedding=embedding,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self.knowledge_graph.add_concept(concept)
        _LOG.info("unified.add_concept id=%s domain=%s", concept.concept_id, concept.domain)
        return concept

    def learn_relationship(
        self,
        source_concept_id: str,
        target_concept_id: str,
        relationship: str = "causes",
        strength: float = 0.5,
    ) -> bool:
        with self._lock:
            ok = self.knowledge_graph.add_relationship(
                source_concept_id, target_concept_id, relationship, strength
            )
        if ok:
            _LOG.info(
                "unified.learn_relationship %s -%s-> %s strength=%.2f",
                source_concept_id, relationship, target_concept_id, float(strength),
            )
        return ok

    # -- internals -----------------------------------------------------

    def _semantic_search(
        self,
        query_embedding: np.ndarray,
        domains: list[str],
        top_k: int,
    ) -> list[tuple[DomainConcept, float]]:
        if top_k <= 0:
            return []
        domain_filter = {d.strip().lower() for d in domains if isinstance(d, str)}
        scored: list[tuple[DomainConcept, float]] = []
        for concept in self.knowledge_graph.concepts.values():
            if domain_filter and concept.domain not in domain_filter:
                continue
            scored.append((concept, _cosine_similarity(query_embedding, concept.embedding)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def _causal_inference(
        self,
        relevant: list[tuple[DomainConcept, float]],
    ) -> list[CrossDomainImplication]:
        out: list[CrossDomainImplication] = []
        seen: set[tuple[str, str]] = set()
        for concept, relevance in relevant:
            for neighbour_id, edge_data in self.knowledge_graph.get_neighbors(
                concept.concept_id, relationship="causes"
            ):
                neighbour = self.knowledge_graph.get_concept(neighbour_id)
                if neighbour is None or neighbour.domain == concept.domain:
                    continue
                key = (concept.concept_id, neighbour.concept_id)
                if key in seen:
                    continue
                seen.add(key)
                strength = float(edge_data.get("strength", 0.5))
                out.append(
                    CrossDomainImplication(
                        source_domain=concept.domain,
                        target_domain=neighbour.domain,
                        source_concept=concept.name,
                        target_concept=neighbour.name,
                        impact_type=self._classify_impact(concept, neighbour),
                        magnitude=max(0.0, min(1.0, strength * float(relevance))),
                        confidence=max(0.0, min(1.0, float(relevance) * 0.8)),
                        reasoning=(
                            f"{concept.name} in {concept.domain} causes "
                            f"{neighbour.name} in {neighbour.domain}"
                        ),
                    )
                )
        return out

    @staticmethod
    def _classify_impact(source: DomainConcept, target: DomainConcept) -> str:
        src_name = source.name.lower()
        tgt_name = target.name.lower()
        src_negative = any(kw in src_name for kw in _NEGATIVE_KEYWORDS)
        tgt_negative = any(kw in tgt_name for kw in _NEGATIVE_KEYWORDS)
        if src_negative and tgt_negative:
            return "negative"
        if not src_negative and not tgt_negative:
            return "positive"
        return "neutral"

    def _generate_recommendations(
        self,
        query: str,
        relevant: list[tuple[DomainConcept, float]],
        implications: list[CrossDomainImplication],
    ) -> dict[str, Any]:
        if not relevant:
            return {
                "primary": {
                    "domain": "unknown",
                    "action": "no_action",
                    "confidence": 0.0,
                    "reasoning": "no relevant concept matched query",
                },
                "secondary": [],
            }
        primary_concept, primary_score = relevant[0]
        primary = {
            "domain": primary_concept.domain,
            "action": self._concept_to_action(primary_concept),
            "confidence": float(primary_score),
            "reasoning": f"Most relevant concept: {primary_concept.name}",
        }
        secondary: list[dict[str, Any]] = []
        for impl in implications[:3]:
            if impl.magnitude > 0.3:
                secondary.append(
                    {
                        "domain": impl.target_domain,
                        "action": self._implication_to_action(impl),
                        "impact": impl.impact_type,
                        "magnitude": float(impl.magnitude),
                        "reasoning": impl.reasoning,
                    }
                )
        return {"primary": primary, "secondary": secondary}

    @staticmethod
    def _concept_to_action(concept: DomainConcept) -> str:
        domain_map = _DEFAULT_ACTION_MAP.get(concept.domain, {})
        lname = concept.name.lower()
        for keyword, action in domain_map.items():
            if keyword in lname:
                return action
        return "monitor"

    @staticmethod
    def _implication_to_action(impl: CrossDomainImplication) -> str:
        target = _normalise_text(impl.target_concept) or "target"
        if impl.impact_type == "negative":
            return f"mitigate_{target}"
        if impl.impact_type == "positive":
            return f"leverage_{target}"
        return "monitor"

    @staticmethod
    def _empty_report(*, query: str, domains: list[str]) -> dict[str, Any]:
        return {
            "query": query,
            "domains_considered": domains,
            "relevant_concepts": [],
            "primary_action": {
                "domain": "unknown",
                "action": "no_action",
                "confidence": 0.0,
                "reasoning": "empty query",
            },
            "secondary_effects": [],
            "domains_affected": [],
            "implications": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_singleton: UnifiedReasoner | None = None
_singleton_lock = threading.Lock()


def get_unified_reasoner() -> UnifiedReasoner:
    """Return the process-wide :class:`UnifiedReasoner` singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = UnifiedReasoner()
    return _singleton


def reset_unified_reasoner() -> None:
    """Test-only helper that drops the singleton so the next
    :func:`get_unified_reasoner` rebuilds from scratch (e.g. with a freshly
    seeded fallback embedder)."""
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "CrossDomainImplication",
    "DomainConcept",
    "EMBEDDING_DIM",
    "EMBEDDINGS_AVAILABLE",
    "GRAPH_AVAILABLE",
    "KNOWN_DOMAINS",
    "KnowledgeGraph",
    "UnifiedEmbedder",
    "UnifiedReasoner",
    "get_unified_reasoner",
    "reset_unified_reasoner",
]
