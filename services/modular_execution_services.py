"""Modular domain execution services for Thiramai."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
from typing import Any

from services.business_snapshot_service import build_business_snapshot
from services.personal_quick_intent_sync import parse_quick_phrase
from services.research_engine_service import run_supplier_research_sync
from services.stock_signal_service import generate_intraday_signal
from services.website_builder_service import build_website_sync
from services.website_template_service import TEMPLATE_TYPES


@dataclass(frozen=True)
class ServiceExecutionContext:
    user_id: int
    organization_id: int
    role_name: str


def _extract_symbol(command: str) -> str | None:
    tokens = [t.strip(" ,.!?;:").upper() for t in (command or "").split()]
    for t in tokens:
        if t.isalpha() and 2 <= len(t) <= 12:
            return t
    return None


def _extract_org_id(command: str) -> int | None:
    m = re.search(r"\b(?:org|organization|business)\s*#?\s*(\d+)\b", command or "", re.I)
    if not m:
        return None
    try:
        out = int(m.group(1))
    except Exception:
        return None
    return out if out > 0 else None


def _extract_template_type(command: str) -> str:
    t = (command or "").lower()
    for template in sorted(TEMPLATE_TYPES):
        if template in t:
            return template
    if "catalog" in t:
        return "catalog"
    if "landing" in t:
        return "landing"
    return "shop"


class BaseExecutionService(ABC):
    intent: str

    @abstractmethod
    def execute(self, command: str, ctx: ServiceExecutionContext) -> dict[str, Any]:
        raise NotImplementedError


class PersonalService(BaseExecutionService):
    intent = "personal"

    def execute(self, command: str, ctx: ServiceExecutionContext) -> dict[str, Any]:
        parsed = parse_quick_phrase(command)
        return {
            "intent": self.intent,
            "steps": [
                "Detected personal intent",
                "Routed to personal_quick_intent_sync.parse_quick_phrase",
                "Parsed quick personal action",
            ],
            "result": {
                "command": command,
                "parsed": parsed,
                "user_id": ctx.user_id,
            },
            "status": "success" if parsed.get("ok") else "error",
        }


class BusinessService(BaseExecutionService):
    intent = "business"

    def execute(self, command: str, ctx: ServiceExecutionContext) -> dict[str, Any]:
        snapshot = build_business_snapshot(ctx.organization_id)
        return {
            "intent": self.intent,
            "steps": [
                "Detected business intent",
                "Routed to business_snapshot_service.build_business_snapshot",
                "Generated business snapshot",
            ],
            "result": {
                "command": command,
                "snapshot": snapshot,
            },
            "status": "success" if snapshot.get("ok") else "error",
        }


class ResearchService(BaseExecutionService):
    intent = "research"

    def execute(self, command: str, ctx: ServiceExecutionContext) -> dict[str, Any]:
        out = run_supplier_research_sync(command)
        return {
            "intent": self.intent,
            "steps": [
                "Detected research intent",
                "Routed to research_engine_service.run_supplier_research_sync",
                "Executed supplier/pricing/contact extraction",
            ],
            "result": out,
            "status": "success" if out.get("ok") else "error",
        }


class MoneyService(BaseExecutionService):
    intent = "money"

    def execute(self, command: str, ctx: ServiceExecutionContext) -> dict[str, Any]:
        symbol = _extract_symbol(command) or "TCS"
        out = generate_intraday_signal(symbol, user_id=ctx.user_id)
        return {
            "intent": self.intent,
            "steps": [
                "Detected money intent",
                "Routed to stock_signal_service.generate_intraday_signal",
                "Generated trading signal",
            ],
            "result": out,
            "status": "success" if out.get("ok") else "error",
        }


class BuildService(BaseExecutionService):
    intent = "build"

    def execute(self, command: str, ctx: ServiceExecutionContext) -> dict[str, Any]:
        org_id = _extract_org_id(command) or int(ctx.organization_id)
        template = _extract_template_type(command)
        run_deploy = "deploy" in (command or "").lower()
        out = build_website_sync(
            org_id,
            template,
            user_id=int(ctx.user_id),
            run_deploy=run_deploy,
        )
        return {
            "intent": self.intent,
            "steps": [
                "Detected build intent",
                f"Resolved build target organization_id={org_id}, template={template}, deploy={run_deploy}",
                "Routed to website_builder_service.build_website_sync",
                "Generated business website artifacts and metadata",
            ],
            "result": out,
            "status": "success" if out.get("ok") else "error",
        }

