"""Logging for legacy HTTP routes that delegate to ``brain_execute``."""

from __future__ import annotations

import logging

_log = logging.getLogger("thiramai.deprecated_execution")


def warn_deprecated_execution_forwarded(route: str) -> None:
    _log.warning("Deprecated route — forwarded to brain: %s", route)
