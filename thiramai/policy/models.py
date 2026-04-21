from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TaskType = Literal["audit", "analysis", "coding", "research", "fix", "api", "device"]
RiskLevel = Literal["low", "medium", "high"]


class ExecutionContext(BaseModel):
    tenant_id: int | None = None
    task_type: TaskType = "analysis"
    risk_level: RiskLevel = "low"
    capabilities: list[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    allow: bool
    reason: str
    policy_id: str
