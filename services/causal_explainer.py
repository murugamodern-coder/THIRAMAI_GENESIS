"""Causal explanation for individual decisions.

Given a decision dict (the same shape returned by :class:`PolicyEngine` /
:class:`HierarchicalPolicy`) this module builds:

* a small DAG of causal steps - context / world state -> features ->
  bandit weights -> action;
* per-feature attribution scores using a simple magnitude-normalised
  attribution (the spec called this "SHAP-style" but it's not real SHAP -
  see the class docstring);
* a short natural-language explanation;
* one or two counterfactual statements about which features were most
  influential.

Spec deviations (deliberate fixes for issues in the original prompt)
--------------------------------------------------------------------

* The spec aliased our local fallback ``_FallbackDiGraph`` to ``nx`` and
  then called ``nx.DiGraph()`` - which would raise ``AttributeError``
  because the alias points to a *class*, not the networkx module. We use
  a ``_DIGRAPH_FACTORY`` callable so both code paths build a graph the
  same way.
* The spec used ``hash(domain) % 100 / 100.0`` for fallback feature
  encoding - Python's ``hash()`` is salted per-process so the encoding
  silently changed across deployments. We use ``zlib.adler32``.
* The implementation is honest about not being SHAP - the class is named
  :class:`MagnitudeAttributor` to reflect what it actually does.
* The router-side ``_graph_to_dict`` referenced in the spec didn't exist;
  :meth:`CausalGraphBuilder.to_dict` is the canonical converter.
"""

from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

import numpy as np

from services.unified_reasoner import _FallbackDiGraph

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Soft import - networkx is optional, fallback uses the in-house DiGraph
# ---------------------------------------------------------------------------


try:
    import networkx as _nx  # type: ignore[import-untyped]

    GRAPH_AVAILABLE = True
    _DIGRAPH_FACTORY: Callable[[], Any] = _nx.DiGraph
except Exception as _exc:  # pragma: no cover - environment-dependent
    _nx = None  # type: ignore[assignment]
    GRAPH_AVAILABLE = False
    _DIGRAPH_FACTORY = _FallbackDiGraph


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FeatureImportance:
    """Per-feature attribution score."""

    feature_name: str
    importance: float  # >=0, importances across one explanation sum to ~1
    contribution: float  # signed - the raw feature value
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "importance": float(self.importance),
            "contribution": float(self.contribution),
            "description": self.description,
        }


@dataclass
class CausalExplanation:
    """Full explanation bundle for a single decision."""

    decision_id: int | None
    action: str
    confidence: float
    causal_graph: Any  # nx.DiGraph or _FallbackDiGraph
    feature_importance: list[FeatureImportance] = field(default_factory=list)
    text_explanation: str = ""
    counterfactuals: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self, *, graph_to_dict: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "action": self.action,
            "confidence": float(self.confidence),
            "causal_graph": graph_to_dict(self.causal_graph),
            "feature_importance": [f.as_dict() for f in self.feature_importance],
            "text_explanation": self.text_explanation,
            "counterfactuals": list(self.counterfactuals),
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Causal graph builder
# ---------------------------------------------------------------------------


class CausalGraphBuilder:
    """Build the small causal DAG and convert it to a JSON-friendly dict."""

    def build(
        self,
        context: dict[str, Any],
        world_state: dict[str, Any],
        features: np.ndarray,
        action: str,
        confidence: float,
    ) -> Any:
        graph = _DIGRAPH_FACTORY()
        graph.add_node("Context", layer=0, kind="input")
        graph.add_node("WorldState", layer=0, kind="input")
        graph.add_node("Features", layer=1, kind="derived", size=int(np.size(features)))
        graph.add_node("BanditWeights", layer=2, kind="model")
        graph.add_node("Action", layer=3, kind="output", value=str(action))
        graph.add_edge("Context", "Features", weight=0.4, label="extract")
        graph.add_edge("WorldState", "Features", weight=0.6, label="predict")
        graph.add_edge("Features", "BanditWeights", weight=0.8, label="combine")
        graph.add_edge("BanditWeights", "Action", weight=float(confidence), label="select")
        return graph

    @staticmethod
    def to_dict(graph: Any) -> dict[str, Any]:
        nodes_attr = getattr(graph, "nodes", None)
        if nodes_attr is None:
            return {"nodes": [], "edges": []}
        nodes_payload: list[dict[str, Any]] = []
        for node_id in graph.nodes:
            attrs = dict(graph.nodes[node_id])
            nodes_payload.append({"id": str(node_id), **attrs})
        edges_payload: list[dict[str, Any]] = []
        for edge in graph.edges(data=True) if hasattr(graph, "edges") else []:
            if len(edge) == 3:
                src, dst, data = edge
            else:
                src, dst = edge
                data = {}
            edges_payload.append({"source": str(src), "target": str(dst), **dict(data)})
        return {"nodes": nodes_payload, "edges": edges_payload}


# ---------------------------------------------------------------------------
# Feature attribution
# ---------------------------------------------------------------------------


class MagnitudeAttributor:
    """Magnitude-based feature attribution.

    .. note::
       Not real SHAP - SHAP requires retraining the model on feature subsets
       and is expensive. This computes ``|x_i| / sum_j |x_j|`` which is a
       cheap, interpretable approximation that highlights which features are
       *active* but does **not** account for feature interaction or model
       coefficients. The spec called this "SHAP-style" - we keep that
       framing in user-facing text but the class name reflects the truth."""

    def attribute(
        self,
        features: np.ndarray,
        feature_names: Sequence[str],
    ) -> list[FeatureImportance]:
        features = np.asarray(features, dtype=float).reshape(-1)
        names = list(feature_names)
        if len(names) < features.size:
            names.extend(f"feature_{i}" for i in range(len(names), features.size))
        else:
            names = names[: features.size]

        if features.size == 0:
            return []

        magnitudes = np.abs(features)
        total = float(np.sum(magnitudes))
        if total > 0:
            normalised = magnitudes / total
        else:
            normalised = np.ones_like(magnitudes) / float(features.size)

        out = [
            FeatureImportance(
                feature_name=names[i],
                importance=float(normalised[i]),
                contribution=float(features[i]),
                description=self._describe(names[i], float(features[i]), float(normalised[i])),
            )
            for i in range(features.size)
        ]
        out.sort(key=lambda fi: fi.importance, reverse=True)
        return out

    @staticmethod
    def _describe(name: str, value: float, importance: float) -> str:
        if value > 0.5:
            direction = "high"
        elif value < -0.5:
            direction = "very low"
        elif value < 0:
            direction = "negative"
        else:
            direction = "low"
        if importance > 0.15:
            strength = "strong"
        elif importance > 0.05:
            strength = "moderate"
        else:
            strength = "weak"
        return f"{name}: {direction} value ({strength} influence)"


# ---------------------------------------------------------------------------
# NL explanation
# ---------------------------------------------------------------------------


class NaturalLanguageGenerator:
    """Produce a multi-sentence plain-English explanation of a decision."""

    def generate(
        self,
        action: str,
        confidence: float,
        feature_importance: Sequence[FeatureImportance],
        world_state: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        sentences: list[str] = []
        sentences.append(
            f"Selected action '{action}' with {float(confidence):.0%} confidence."
        )

        top = list(feature_importance)[:3]
        if top:
            factors = ", ".join(f"{f.feature_name} ({f.importance:.0%})" for f in top)
            sentences.append(f"Primary influencing factors: {factors}.")

        if isinstance(world_state, dict):
            prediction = world_state.get("prediction") or world_state.get("p")
            if isinstance(prediction, dict):
                world_conf = float(prediction.get("confidence", 0.0) or 0.0)
                if world_conf >= 0.7:
                    sentences.append(
                        f"World model shows high confidence ({world_conf:.0%}) in this outcome."
                    )

        domain = str(context.get("domain", "business") if isinstance(context, dict) else "business")
        risk_tolerance = float(context.get("risk_tolerance", 0.5) if isinstance(context, dict) else 0.5)
        if risk_tolerance > 0.7:
            risk_desc = "high risk tolerance"
        elif risk_tolerance < 0.3:
            risk_desc = "low risk tolerance"
        else:
            risk_desc = "moderate risk tolerance"
        sentences.append(f"Decision made in {domain} domain with {risk_desc}.")

        return " ".join(sentences)


# ---------------------------------------------------------------------------
# Helpers - feature extraction fallback
# ---------------------------------------------------------------------------


def _stable_unit(value: Any) -> float:
    """Map any string-like value to a stable float in ``[0, 1)``.

    Used as a fallback feature encoding when no real feature vector is
    available. ``hash()`` is process-salted, ``zlib.adler32`` is not."""
    text = "" if value is None else str(value)
    return (zlib.adler32(text.encode("utf-8")) & 0xFFFFFFFF) / float(2**32)


def _features_from_context(context: dict[str, Any]) -> np.ndarray:
    if not isinstance(context, dict):
        context = {}
    constraints = context.get("constraints", {})
    constraint_count = len(constraints) if hasattr(constraints, "__len__") else 0
    base = [
        1.0,
        _stable_unit(context.get("domain", "")),
        float(context.get("risk_tolerance", 0.5) or 0.5),
        _stable_unit(context.get("time_horizon", "")),
        float(min(10, constraint_count)) / 10.0,
    ]
    base.extend([0.0] * (20 - len(base)))
    return np.asarray(base, dtype=float)


_DEFAULT_FEATURE_NAMES: tuple[str, ...] = (
    "bias",
    "domain_encoding",
    "risk_tolerance",
    "time_horizon",
    "constraint_count",
    "feature_5", "feature_6", "feature_7", "feature_8", "feature_9",
    "feature_10", "feature_11", "feature_12", "feature_13", "feature_14",
    "feature_15", "feature_16", "feature_17", "feature_18", "feature_19",
)


# ---------------------------------------------------------------------------
# Causal explainer
# ---------------------------------------------------------------------------


class CausalExplainer:
    """Top-level entry point. Combines the builder + attributor + NLG."""

    def __init__(
        self,
        *,
        graph_builder: CausalGraphBuilder | None = None,
        attributor: MagnitudeAttributor | None = None,
        nl_generator: NaturalLanguageGenerator | None = None,
    ) -> None:
        self.graph_builder = graph_builder or CausalGraphBuilder()
        self.attributor = attributor or MagnitudeAttributor()
        self.nl_generator = nl_generator or NaturalLanguageGenerator()

    # -- public --------------------------------------------------------

    def explain(
        self,
        decision: dict[str, Any] | None,
        decision_id: int | None = None,
    ) -> CausalExplanation:
        decision = dict(decision or {})
        action = str(decision.get("action") or "unknown")
        confidence = float(decision.get("confidence", 0.5) or 0.5)
        context = dict(decision.get("context_used") or decision.get("context") or {})
        world_state = dict(decision.get("world_state") or {})

        features = self._extract_features(decision, context)
        names = self._get_feature_names(decision, features.size)

        graph = self.graph_builder.build(context, world_state, features, action, confidence)
        importance = self.attributor.attribute(features, names)
        text = self.nl_generator.generate(action, confidence, importance, world_state, context)
        counterfactuals = self._generate_counterfactuals(action, importance)

        explanation = CausalExplanation(
            decision_id=decision_id,
            action=action,
            confidence=confidence,
            causal_graph=graph,
            feature_importance=importance,
            text_explanation=text,
            counterfactuals=counterfactuals,
        )
        logger.info("causal_explainer: explained action=%s confidence=%.2f", action, confidence)
        return explanation

    # -- internals -----------------------------------------------------

    @staticmethod
    def _extract_features(decision: dict[str, Any], context: dict[str, Any]) -> np.ndarray:
        # 1. Direct PolicyEngine output - DecisionOutput.features is a list[float].
        for key in ("features",):
            if key in decision and decision[key] is not None:
                try:
                    return np.asarray(decision[key], dtype=float).reshape(-1)
                except (TypeError, ValueError):
                    pass
        metadata = decision.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("features") is not None:
            try:
                return np.asarray(metadata["features"], dtype=float).reshape(-1)
            except (TypeError, ValueError):
                pass
        return _features_from_context(context)

    @staticmethod
    def _get_feature_names(decision: dict[str, Any], size: int) -> list[str]:
        metadata = decision.get("metadata") or {}
        if isinstance(metadata, dict) and isinstance(metadata.get("feature_names"), list):
            names = [str(n) for n in metadata["feature_names"]]
            if len(names) >= size:
                return names[:size]
            names.extend(f"feature_{i}" for i in range(len(names), size))
            return names
        if size <= len(_DEFAULT_FEATURE_NAMES):
            return list(_DEFAULT_FEATURE_NAMES[:size])
        out = list(_DEFAULT_FEATURE_NAMES)
        out.extend(f"feature_{i}" for i in range(len(_DEFAULT_FEATURE_NAMES), size))
        return out

    @staticmethod
    def _generate_counterfactuals(
        action: str, importance: Sequence[FeatureImportance]
    ) -> list[str]:
        out: list[str] = []
        for feat in list(importance)[:2]:
            if feat.contribution >= 0.5:
                out.append(
                    f"if {feat.feature_name} were lower, a different action than "
                    f"'{action}' might have been selected"
                )
            elif feat.contribution <= -0.5:
                out.append(
                    f"if {feat.feature_name} were higher, '{action}' would be "
                    "even more strongly preferred"
                )
            else:
                out.append(
                    f"{feat.feature_name} was near its midpoint - small changes "
                    f"there are unlikely to flip the decision away from '{action}'"
                )
        return out


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_singleton: CausalExplainer | None = None
import threading as _threading

_singleton_lock = _threading.Lock()


def get_causal_explainer() -> CausalExplainer:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = CausalExplainer()
    return _singleton


def reset_causal_explainer() -> None:
    """Test-only helper that drops the singleton."""
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "CausalExplainer",
    "CausalExplanation",
    "CausalGraphBuilder",
    "FeatureImportance",
    "GRAPH_AVAILABLE",
    "MagnitudeAttributor",
    "NaturalLanguageGenerator",
    "get_causal_explainer",
    "reset_causal_explainer",
]
