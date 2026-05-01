"""LLM-backed improvement hypotheses from detected performance regressions.

Uses the Anthropic API when ``ANTHROPIC_API_KEY`` is set and
``anthropic`` is installed; otherwise falls back to deterministic
rule-based hypotheses suitable for CI and air-gapped installs.

All deployment actions remain **off by default** — hypotheses carry a
``test_strategy`` field for downstream A/B or shadow routing; nothing
here mutates production routing automatically.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from services.self_evolution.performance_monitor import PerformanceDegradation

logger = logging.getLogger(__name__)

try:
    import anthropic  # type: ignore[import-not-found]

    _ANTHROPIC_IMPORT_OK = True
except Exception:  # pragma: no cover - optional
    anthropic = None  # type: ignore[assignment]
    _ANTHROPIC_IMPORT_OK = False


DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")


@dataclass
class ImprovementHypothesis:
    hypothesis_id: str
    issue: PerformanceDegradation
    fix_type: str
    description: str
    code_changes: str | None
    test_strategy: str
    success_criteria: dict[str, float]
    confidence: float
    estimated_impact: float
    risk_level: str
    generated_at: datetime
    raw_llm_response: str | None = None


class ImprovementGenerator:
    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model or DEFAULT_MODEL
        self._client = client
        self._api_key = api_key if api_key is not None else (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        self._owns_client = False

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not _ANTHROPIC_IMPORT_OK or not self._api_key:
            return None
        try:
            self._client = anthropic.Anthropic(api_key=self._api_key)
            self._owns_client = True
            return self._client
        except Exception as exc:
            logger.warning("improvement_generator: Anthropic client init failed: %s", exc)
            return None

    def anthropic_ready(self) -> bool:
        return self._ensure_client() is not None

    def generate_fixes(
        self,
        degradations: list[PerformanceDegradation],
    ) -> list[ImprovementHypothesis]:
        if not degradations:
            return []
        client = self._ensure_client()
        out: list[ImprovementHypothesis] = []
        for degradation in degradations:
            if client is not None:
                hypothesis = self._generate_with_claude(client, degradation)
            else:
                hypothesis = self._generate_fallback(degradation)
            out.append(hypothesis)
            logger.info(
                "improvement_generator: %s -> %s",
                degradation.issue_type,
                hypothesis.fix_type,
            )
        return out

    def _generate_with_claude(self, client: Any, degradation: PerformanceDegradation) -> ImprovementHypothesis:
        prompt = self._build_prompt(degradation)
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            content = ""
            if response.content:
                first = response.content[0]
                content = getattr(first, "text", str(first))
            hyp = self._parse_claude_response(content, degradation)
            hyp.raw_llm_response = content
            return hyp
        except Exception as exc:
            logger.error("improvement_generator: Claude API failed: %s", exc)
            return self._generate_fallback(degradation)

    def _build_prompt(self, degradation: PerformanceDegradation) -> str:
        return f"""
You are a machine learning engineer debugging a production AI system.

PERFORMANCE ISSUE DETECTED:
- Type: {degradation.issue_type}
- Severity: {degradation.severity:.2f}
- Domain: {degradation.affected_domain}
- Component: {degradation.affected_component}
- Current value: {degradation.current_value:.3f}
- Baseline value: {degradation.baseline_value:.3f}
- Description: {degradation.description}

Generate ONE concrete fix hypothesis. Respond with a single JSON object only:

{{
  "fix_type": "parameter_tuning" | "model_retrain" | "code_change" | "feature_engineering",
  "description": "Clear description of the fix",
  "code_changes": "Python snippet or null",
  "test_strategy": "a_b_test" | "shadow" | "canary",
  "success_criteria": {{"metric_name": 0.05}},
  "confidence": 0.0,
  "estimated_impact": 0.0,
  "risk_level": "low" | "medium" | "high"
}}

Rules: incremental changes only; must be measurable; no destructive ops.
"""

    def _parse_claude_response(self, response: str, degradation: PerformanceDegradation) -> ImprovementHypothesis:
        try:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                raise ValueError("no JSON object in model response")
            data = json.loads(json_match.group())
            hypothesis_id = str(uuid.uuid4())
            sc = data.get("success_criteria") or {"accuracy_gain": 0.05}
            if not isinstance(sc, dict):
                sc = {"accuracy_gain": 0.05}
            sc = {str(k): float(v) for k, v in sc.items() if isinstance(v, (int, float))}
            return ImprovementHypothesis(
                hypothesis_id=hypothesis_id,
                issue=degradation,
                fix_type=str(data.get("fix_type", "parameter_tuning")),
                description=str(data.get("description", "")),
                code_changes=data.get("code_changes"),
                test_strategy=str(data.get("test_strategy", "a_b_test")),
                success_criteria=sc or {"accuracy_gain": 0.05},
                confidence=float(data.get("confidence", 0.5)),
                estimated_impact=float(data.get("estimated_impact", 0.3)),
                risk_level=str(data.get("risk_level", "medium")),
                generated_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.error("improvement_generator: parse failed: %s", exc)
            return self._generate_fallback(degradation)

    def _generate_fallback(self, degradation: PerformanceDegradation) -> ImprovementHypothesis:
        hid = str(uuid.uuid4())
        if degradation.issue_type == "accuracy_drop":
            return ImprovementHypothesis(
                hypothesis_id=hid,
                issue=degradation,
                fix_type="model_retrain",
                description="Trigger online learner partial_fit with last-N-day resolved outcomes; tighten exploration.",
                code_changes=None,
                test_strategy="a_b_test",
                success_criteria={"decision_accuracy_delta": 0.05},
                confidence=0.7,
                estimated_impact=0.4,
                risk_level="low",
                generated_at=datetime.now(timezone.utc),
            )
        if degradation.issue_type == "drift":
            return ImprovementHypothesis(
                hypothesis_id=hid,
                issue=degradation,
                fix_type="feature_engineering",
                description="Refresh normalization stats; increase `online_cluster_features` batch size for drift labels.",
                code_changes=None,
                test_strategy="shadow",
                success_criteria={"feature_drift_score_delta": -0.1},
                confidence=0.6,
                estimated_impact=0.3,
                risk_level="low",
                generated_at=datetime.now(timezone.utc),
            )
        if degradation.issue_type == "performance_drop":
            return ImprovementHypothesis(
                hypothesis_id=hid,
                issue=degradation,
                fix_type="parameter_tuning",
                description="Reduce strategy aggressiveness in policy router; enable conservative variant for trading domain.",
                code_changes=None,
                test_strategy="canary",
                success_criteria={"trading_sharpe_delta": 0.2},
                confidence=0.55,
                estimated_impact=0.35,
                risk_level="medium",
                generated_at=datetime.now(timezone.utc),
            )
        return ImprovementHypothesis(
            hypothesis_id=hid,
            issue=degradation,
            fix_type="parameter_tuning",
            description="Lower auto-execution temperature; add human-in-the-loop for low-confidence actions.",
            code_changes=None,
            test_strategy="a_b_test",
            success_criteria={"error_rate_delta": -0.02},
            confidence=0.5,
            estimated_impact=0.2,
            risk_level="low",
            generated_at=datetime.now(timezone.utc),
        )


_singleton: ImprovementGenerator | None = None
_singleton_lock = threading.Lock()


def get_improvement_generator() -> ImprovementGenerator:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ImprovementGenerator()
    return _singleton


def reset_improvement_generator() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "ImprovementGenerator",
    "ImprovementHypothesis",
    "get_improvement_generator",
    "reset_improvement_generator",
]
