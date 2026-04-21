"""Safe write-path policy for LLM-triggered filesystem operations."""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger("thiramai.security.sandbox_policy")
_ROOT = Path(__file__).resolve().parents[2]

# Relative to repo root; only these directories are writable for LLM-driven operations.
SAFE_WRITE_PATHS: tuple[str, ...] = (
    "sandbox",
    "generated_apps",
    "logs",
    "var/sandbox_patches",
    "var/thiramai-sites",
    "var/kernel",
)

_BLOCKED_EXACT: frozenset[str] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "api/routes/auth.py",
    }
)


def _norm_rel(path: Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def validate_llm_write_path(path_like: str | Path) -> tuple[bool, str]:
    """Return (allowed, reason) for an LLM-initiated write target."""
    p = Path(path_like)
    target = p if p.is_absolute() else (_ROOT / p)
    target = target.resolve()
    try:
        rel = _norm_rel(target.relative_to(_ROOT))
    except ValueError:
        return False, "outside_repo_root"
    if rel in _BLOCKED_EXACT:
        return False, f"blocked_path:{rel}"
    if rel.endswith("/auth.py") or rel == "api/routes/auth.py":
        return False, f"blocked_path:{rel}"
    if rel.startswith(".env"):
        return False, f"blocked_path:{rel}"
    for allowed in SAFE_WRITE_PATHS:
        prefix = _norm_rel(Path(allowed))
        if rel == prefix or rel.startswith(prefix + "/"):
            return True, "ok"
    return False, f"path_not_allowlisted:{rel}"


def enforce_llm_write_path(path_like: str | Path, *, operation: str = "write") -> Path:
    """Validate and return resolved path, raising PermissionError if blocked."""
    p = Path(path_like)
    target = p if p.is_absolute() else (_ROOT / p)
    target = target.resolve()
    ok, reason = validate_llm_write_path(target)
    if not ok:
        _log.warning("SECURITY_EVENT llm_write_blocked op=%s path=%s reason=%s", operation, str(target), reason)
        raise PermissionError(f"Blocked by sandbox policy: {reason}")
    return target
