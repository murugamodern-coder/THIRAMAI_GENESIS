"""
Multi-agent orchestrator swarm (LangGraph).

**Architect** → **Dev** → **Security** (Stage 3 ``action_policy``) → **Reviewer** → merge or retry.

Shared state is ``SwarmState`` (blackboard). Enable with ``THIRAMAI_ORCHESTRATOR_SWARM=1``.
"""

from __future__ import annotations

from core.swarm.blackboard import SwarmState
from core.swarm.pipeline import augment_shared_core_with_swarm, orchestrator_swarm_enabled

__all__ = ["SwarmState", "augment_shared_core_with_swarm", "orchestrator_swarm_enabled"]
