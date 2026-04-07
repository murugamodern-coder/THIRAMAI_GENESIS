"""Kernel capabilities and boundary description (micro-kernel contract)."""

from __future__ import annotations

from typing import Any


def kernel_capabilities() -> dict[str, Any]:
    """Declared capabilities of the runtime kernel (orchestrator + API shell)."""
    return {
        "name": "thiramai-genesis-kernel",
        "version": "1.0",
        "subsystems": [
            "orchestrator",
            "auth_rbac",
            "tenant_data_plane",
            "sandbox_execution",
            "self_coder_patches",
        ],
        "sandbox": {
            "engine": "docker",
            "isolation": "headless_container",
            "network_default": "none",
        },
    }


def describe_kernel() -> str:
    """Short human-readable boundary summary for prompts and ops."""
    caps = kernel_capabilities()
    subs = ", ".join(caps["subsystems"])
    return (
        f"THIRAMAI kernel ({caps['name']} v{caps['version']}): "
        f"nucleus subsystems [{subs}]. "
        "AI-generated code runs only inside Docker sandbox; patches require pytest green "
        "before hot-reload signal."
    )
