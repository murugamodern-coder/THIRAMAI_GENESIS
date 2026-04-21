"""Cap auto-fix attempts per issue (infinite repair loop guard)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from core.stability.logging_tags import log_auto_fix_blocked, log_stability


@dataclass
class AutoFixGuard:
    """
    Per-issue attempt counts. Prevents infinite repair loops.

    Cooldown between attempts is enforced by the caller (e.g. ``run_system`` sleep between rounds),
    not inside this class, so the second fix attempt is not blocked incorrectly.
    Issue keys are stable strings (e.g. ``bundle_integrity``, ``api_health``).
    """

    max_per_issue: int = field(default_factory=lambda: int(os.environ.get("THIRAMAI_AUTO_FIX_MAX_PER_ISSUE", "3") or "3"))
    _attempts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.max_per_issue = max(1, self.max_per_issue)

    def can_attempt(self, issue_keys: set[str]) -> bool:
        """True if any failed issue is still under the per-issue cap."""
        if not issue_keys:
            return False
        for key in issue_keys:
            if self._attempts.get(key, 0) < self.max_per_issue:
                return True
        log_auto_fix_blocked(
            f"issues={sorted(issue_keys)} max_per_issue={self.max_per_issue} (all at cap)"
        )
        return False

    def record_attempt(self, issue_keys: set[str]) -> None:
        for key in issue_keys:
            self._attempts[key] = self._attempts.get(key, 0) + 1
        log_stability(f"auto-fix attempt recorded for {sorted(issue_keys)}")
