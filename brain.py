"""
THIRAMAI brain — thin facade over `core.orchestrator` (v2 modular layout).

`run_brain(message, organization_id)` is tenant-scoped. For scripts, set THIRAMAI_DEFAULT_ORG_ID
or call `run_brain(..., organization_id=...)` explicitly.
"""

import os

from core.brain_output import BrainStructuredResponse
from core.errors import QueryLengthExceeded
from core.orchestrator import run_brain as _run_brain_structured
from core.policies.loader import MAX_USER_MESSAGE_CHARS
from core.system_checks import run_full_system_check, smoke_test_invoice_pdf


def run_brain(
    user_message: str,
    organization_id: int,
    *,
    actor_role_name: str | None = None,
    user_id: int | None = None,
    vault_passphrase: str | None = None,
    correlation_id: str | None = None,
) -> BrainStructuredResponse:
    """Tenant-scoped brain; returns validated structured output (narrative + action_intent)."""
    return _run_brain_structured(
        user_message,
        organization_id,
        actor_role_name=actor_role_name,
        user_id=user_id,
        vault_passphrase=vault_passphrase,
        correlation_id=correlation_id,
    )


def run_decision_engine(
    user_message: str,
    organization_id: int,
    *,
    actor_role_name: str | None = None,
    user_id: int | None = None,
    correlation_id: str | None = None,
) -> dict:
    """
    Phase 3 — JSON-only decision pass (Groq + business context). Returns a plain dict (not Pydantic).
    See ``services.decision_brain.run_decision_engine_sync``.
    """
    from services.decision_brain import run_decision_engine_sync

    return run_decision_engine_sync(
        user_message,
        organization_id,
        actor_role_name=actor_role_name,
        user_id=user_id,
        correlation_id=correlation_id,
    )


def thiramai_think(user_message: str, organization_id: int | None = None) -> str:
    """Backward-compatible alias: returns narrative Markdown only."""
    oid = organization_id if organization_id is not None else int((os.getenv("THIRAMAI_DEFAULT_ORG_ID") or "1").strip())
    return _run_brain_structured(user_message, organization_id=oid, actor_role_name=None).narrative

if __name__ == "__main__":
    import sys

    if "--full-system-check" in sys.argv:
        raise SystemExit(run_full_system_check())

    if "--smoke-invoice" in sys.argv:
        smoke_test_invoice_pdf()
