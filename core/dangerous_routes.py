"""High-risk HTTP surface — disabled or blocked when ``ENV`` / ``THIRAMAI_ENV`` is ``production``."""

from __future__ import annotations

import os

from core.settings import get_settings

# Mirrors Day 2 spec (documentation / tooling); routing uses ``dangerous_route_prefixes_production``.
ENV = os.getenv("ENV", "development")

DANGEROUS_ROUTES = [
    "agent_tools",
    "code_agent",
    "kernel_microkernel",
    "website_builder",
    "tool_builder",
    "jarvis_bridge",
]


def production_blocks_dangerous_routes() -> bool:
    return get_settings().is_production()


def dangerous_route_prefixes_production() -> tuple[str, ...]:
    """URL prefixes that must not be served by real handlers in production (403 via middleware if probed)."""
    return (
        "/api/tools",
        "/api/agent",
        "/api/websites",
        "/website-builder",
        "/tools/builder",
        "/kernel",
        "/logs",
    )


def is_dangerous_public_path(path: str) -> bool:
    """True when *path* should be blocked in production (prefix match)."""
    p = path or ""
    if not p.startswith("/"):
        p = "/" + p
    for prefix in dangerous_route_prefixes_production():
        if p == prefix or p.startswith(prefix + "/"):
            return True
    return False
