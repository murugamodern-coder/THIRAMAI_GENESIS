"""
Micro-kernel boundary for THIRAMAI Genesis.

The **monolith** remains the deployable unit; this package defines the *kernel contract*:
orchestrator + HTTP façade as the nucleus, with **optional** sandboxed code generation
(``services/sandbox_service``) and **Self-Coder** patches applied only after isolated pytest.

Hot-reload is **signalled** via ``core.kernel.hot_reload`` and ``core.kernel.reload_hook``;
applying patches to live Gunicorn workers still requires a supervised process restart.
"""

from __future__ import annotations

from core.kernel.bridge import describe_kernel, kernel_capabilities

__all__ = ["describe_kernel", "kernel_capabilities"]
