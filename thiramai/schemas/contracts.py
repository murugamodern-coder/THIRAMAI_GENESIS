from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StepModel(BaseModel):
    id: int
    task_type: Literal["audit", "analysis", "coding", "research", "fix", "api", "device"]
    command: str = ""
    description: str
    depends_on: list[int] = Field(default_factory=list)


class PlanModel(BaseModel):
    goal: str
    steps: list[StepModel]
    total_steps: int


class ReviewModel(BaseModel):
    status: Literal["pass", "fail"]
    confidence: float
    reason: str
    suggested_fix: str = ""
