"""
Paths that must never be modified by autonomous connectors (self-improvement lock).

Reads still allowed where safe; writes blocked for core policy / executor / security code.
"""

from __future__ import annotations

from pathlib import Path

# Repo-relative POSIX-style segments (normalized with forward slashes).
PROTECTED_WRITE_PREFIXES: tuple[str, ...] = (
    "thiramai/core/executor.py",
    "thiramai/config.py",
    "core/auth.py",
    "core/security_middleware.py",
    "core/rbac.py",
    "core/production_safety.py",
    "connectors/registry.py",
    ".env",
    ".env.production",
)


def is_write_protected(rel_posix: str) -> bool:
    p = (rel_posix or "").strip().replace("\\", "/").lower().lstrip("/")
    if not p:
        return True
    for pref in PROTECTED_WRITE_PREFIXES:
        pre = pref.lower()
        if p == pre or p.startswith(pre + "/"):
            return True
    # Block writes into hidden security dirs at root
    parts = Path(p).parts
    if parts and parts[0] in {".git", ".github"}:
        return True
    return False
