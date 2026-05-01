"""
Automatic discovery of callables in Python modules and lightweight usage learning.

Read-only introspection + in-memory stats; safe to call from workers/tests.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.self_evolution.meta_learner import MetaLearner

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredTool:
    """Metadata for a public callable discovered in a module."""

    tool_id: str
    name: str
    module_path: str
    parameters: dict[str, Any]
    return_type: str
    description: str
    usage_examples: list[str] = field(default_factory=list)
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    usage_count: int = 0
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ToolUsagePattern:
    """One logged call outcome (used for suggestion heuristics)."""

    tool_id: str
    context_features: dict[str, Any]
    optimal_params: dict[str, Any]
    success_probability: float


class ToolDiscovery:
    """Discover module-level callables and learn coarse success/latency stats."""

    def __init__(self) -> None:
        self.discovered_tools: dict[str, DiscoveredTool] = {}
        self.usage_patterns: list[ToolUsagePattern] = []
        self._stats_alpha: float = 0.1

    def discover_from_module(
        self,
        module_name: str,
        *,
        include_classes: bool = True,
        only_module_members: bool = True,
    ) -> list[DiscoveredTool]:
        """Import *module_name* and register public functions (and optionally classes) defined there."""
        logger.info("tool_discovery: scanning %s", module_name)
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            logger.error("tool_discovery: import failed %s: %s", module_name, exc)
            return []

        tools: list[DiscoveredTool] = []
        for name, obj in inspect.getmembers(module):
            if name.startswith("_"):
                continue
            if only_module_members and getattr(obj, "__module__", None) != module.__name__:
                continue
            if inspect.isfunction(obj):
                tool = self._analyze_callable(name, obj, module_name)
                if tool:
                    tools.append(tool)
                    self.discovered_tools[tool.tool_id] = tool
            elif include_classes and inspect.isclass(obj):
                tool = self._analyze_callable(name, obj, module_name)
                if tool:
                    tools.append(tool)
                    self.discovered_tools[tool.tool_id] = tool

        logger.info("tool_discovery: discovered %d tools from %s", len(tools), module_name)
        return tools

    def _analyze_callable(self, name: str, obj: Any, module_path: str) -> DiscoveredTool | None:
        try:
            sig = inspect.signature(obj)
        except (TypeError, ValueError) as exc:
            logger.debug("tool_discovery: no signature for %s: %s", name, exc)
            return None

        parameters: dict[str, Any] = {}
        for param_name, param in sig.parameters.items():
            parameters[param_name] = {
                "kind": str(param.kind),
                "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any",
                "default": None if param.default is inspect.Parameter.empty else param.default,
            }

        return_type = "Any"
        if sig.return_annotation != inspect.Signature.empty:
            return_type = str(sig.return_annotation)

        desc = inspect.getdoc(obj) or "No description"
        tool_id = f"{module_path}.{name}"
        return DiscoveredTool(
            tool_id=tool_id,
            name=name,
            module_path=module_path,
            parameters=parameters,
            return_type=return_type,
            description=desc[:4000],
        )

    def learn_usage_pattern(
        self,
        tool_id: str,
        context: dict[str, Any],
        params: dict[str, Any],
        success: bool,
        *,
        latency_ms: float | None = None,
    ) -> None:
        """Update running success rate / latency and append a pattern row."""
        alpha = self._stats_alpha
        if tool_id in self.discovered_tools:
            tool = self.discovered_tools[tool_id]
            tool.success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * tool.success_rate
            tool.usage_count += 1
            if latency_ms is not None and latency_ms >= 0:
                n = tool.usage_count
                tool.avg_latency_ms = ((n - 1) * tool.avg_latency_ms + float(latency_ms)) / n

        self.usage_patterns.append(
            ToolUsagePattern(
                tool_id=tool_id,
                context_features=dict(context),
                optimal_params=dict(params) if success else {},
                success_probability=1.0 if success else 0.0,
            )
        )

    def suggest_tool(
        self,
        context: dict[str, Any] | None,
        task_description: str,
        *,
        meta_learner: MetaLearner | None = None,
        min_score: float = 0.3,
    ) -> DiscoveredTool | None:
        """Rank tools by success + description keywords + meta domain alignment."""
        if not self.discovered_tools:
            return None

        ctx = context or {}
        dom = str(ctx.get("domain", "") or "").lower()
        keywords = [w for w in task_description.lower().split() if len(w) > 1]

        candidates: list[tuple[DiscoveredTool, float]] = []
        for _tid, tool in self.discovered_tools.items():
            score = 0.0
            score += 0.45 * float(_clip01(tool.success_rate))

            if keywords:
                desc_words = set(tool.description.lower().split())
                matches = len(set(keywords) & desc_words)
                score += 0.25 * min(matches / len(keywords), 1.0)

            if dom and dom in tool.module_path.lower():
                score += 0.15
            if dom and any(dom in str(v).lower() for v in (tool.name, tool.description)):
                score += 0.10

            if meta_learner and dom:
                if any(getattr(t, "domain", "").lower() == dom for t in meta_learner.tasks):
                    score += 0.05

            for pat in reversed(self.usage_patterns[-200:]):
                if pat.tool_id != tool.tool_id:
                    continue
                if pat.success_probability >= 0.5 and _context_overlap(ctx, pat.context_features) >= 0.3:
                    score += 0.10
                    break

            candidates.append((tool, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        best_tool, best_score = candidates[0]
        if best_score >= min_score:
            logger.info("tool_discovery: suggest %s (score=%.2f)", best_tool.tool_id, best_score)
            return best_tool
        return None


def _context_overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    same = sum(1 for k in keys if a.get(k) == b.get(k))
    return same / max(len(keys), 1)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


_singleton: ToolDiscovery | None = None
_lock = threading.Lock()


def discover_callable_stub(x: int = 1) -> int:
    """Tiny public helper in this module for unit tests (stable ``__module__``)."""
    return x + 1


def get_tool_discovery() -> ToolDiscovery:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = ToolDiscovery()
    return _singleton


def reset_tool_discovery() -> None:
    global _singleton
    with _lock:
        _singleton = None


__all__ = [
    "DiscoveredTool",
    "ToolDiscovery",
    "ToolUsagePattern",
    "discover_callable_stub",
    "get_tool_discovery",
    "reset_tool_discovery",
]
