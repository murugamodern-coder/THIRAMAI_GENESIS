"""Classify autonomous job failures and attach operator-facing hints."""

from __future__ import annotations

from typing import Any


_NON_RETRY_HINT = (
    "This class of error typically requires a code/config change or human approval rather than blind retry."
)


def classify_error(message: str) -> tuple[str, str]:
    """Return (error_type, short_cause_hint)."""
    m = (message or "").lower()
    if "approval" in m or "denied" in m:
        return "approval_blocked", "High-risk task blocked pending approval or was rejected."
    if "rate limit" in m or "429" in m:
        return "rate_limit", "Upstream rate limit or quota exceeded; backoff and retry later."
    if "timeout" in m or "timed out" in m:
        return "timeout", "Operation exceeded its time budget (network, shell, or sandbox)."
    if "connection" in m or "econnrefused" in m or "unreachable" in m:
        return "network", "Network connectivity or DNS failure reaching a dependency."
    if "permission" in m or "access denied" in m or "forbidden" in m or "401" in m or "403" in m:
        return "authorization", "Credentials or permissions insufficient for the requested action."
    if "json" in m or "parse" in m or "syntax" in m:
        return "validation", "Output or payload did not match expected structure."
    if "openai" in m or "llm" in m or "model" in m:
        return "llm_provider", "LLM provider returned an error or empty response."
    if "circuit" in m or "breaker" in m:
        return "circuit_open", "Stability circuit breaker prevented the call."
    if "memory" in m or "oom" in m:
        return "resource_exhaustion", "Process memory pressure or resource cap hit."
    return "unknown", "Inspect attached traceback and latest_results for the failing step."


def analyze_job_failure(
    exc: BaseException | None,
    *,
    message: str | None = None,
    job_id: str | None = None,
    failing_step: str | None = None,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce a structured record stored on the job row (``failure_analysis``)."""
    raw = message or (str(exc) if exc is not None else "unknown_error")
    err_type, cause = classify_error(raw)
    retry_hint = True
    if err_type in ("approval_blocked", "authorization", "validation"):
        retry_hint = False

    out: dict[str, Any] = {
        "error_type": err_type,
        "suggested_cause": cause,
        "retryable_hint": retry_hint,
        "failing_step": failing_step,
        "message_excerpt": raw[:2000],
        "job_id": job_id,
        "notes": _NON_RETRY_HINT if not retry_hint else "Retry may succeed if the root condition is transient.",
    }
    if extra_context:
        out["context"] = extra_context
    return out
