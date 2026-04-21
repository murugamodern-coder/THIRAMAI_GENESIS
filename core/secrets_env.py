"""
Secret retrieval for production: values come only from the process environment.

Do not read ``.env`` files here — ``python-dotenv`` loading happens in ``app`` / ``thiramai.config``
for development convenience; production should inject secrets via the orchestrator (Kubernetes secrets,
AWS Secrets Manager sidecar, etc.) which surface as normal environment variables.

Never log returned secret material; callers should log key *names* only.
"""

from __future__ import annotations

import os
from typing import Any


def get_secret(name: str, default: str | None = None, *, prefix: str = "") -> str | None:
    """
    Read a secret from the environment.

    Optional ``prefix`` (e.g. ``THIRAMAI_SECRET_``) is prepended when the bare name is unset,
    enabling a secret-manager naming convention without changing call sites.
    """
    raw = os.getenv(name)
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    if prefix:
        alt = os.getenv(f"{prefix.rstrip('_')}_{name}" if "_" not in name else f"{prefix}{name}")
        if alt is not None and str(alt).strip():
            return str(alt).strip()
    return default


def require_secret(name: str, *, prefix: str = "") -> str:
    v = get_secret(name, None, prefix=prefix)
    if not v:
        raise RuntimeError(f"Required secret {name} is not set in environment")
    return v


def redact_secret_log_value(_value: Any) -> str:
    """Use in logs instead of printing credential-like strings."""
    return "[redacted]"
