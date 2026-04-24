"""Negotiation intelligence: price bands, supplier matrix, tactics, templates."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.negotiation_intelligence_engine import (
    build_negotiation_suggestions,
    compare_suppliers,
    enrich_with_market_research,
    estimate_price_model,
    full_negotiation_pack,
    generate_message_templates,
    generate_negotiation_script,
)

router = APIRouter(tags=["Negotiation Intelligence"])


class PriceEstimateBody(BaseModel):
    reference_unit_price: float = Field(..., gt=0)
    currency: str = "INR"
    market_volatility: Literal["low", "medium", "high"] = "medium"
    product_note: str = ""


class SupplierRow(BaseModel):
    name: str
    unit_price: float = Field(..., gt=0)
    reliability_0_100: float = Field(default=65.0, ge=0, le=100)
    delivery_days: float = 21.0
    moq: int | str | None = None
    notes: str = ""


class CompareBody(BaseModel):
    suppliers: list[SupplierRow] = Field(..., min_length=1, max_length=20)
    role: Literal["buyer", "seller"] = "buyer"


class NegotiationPlanBody(BaseModel):
    price_model: dict[str, Any] = Field(..., description="Output from /negotiation/price/estimate or compatible")
    role: Literal["buyer", "seller"] = "buyer"
    target_margin_buffer_pct: float = Field(5.0, ge=0, le=20)


class TemplateBody(BaseModel):
    product_line: str = Field(..., min_length=2, max_length=2000)
    supplier_name: str = "Supplier"
    your_company: str = "our organization"
    role: Literal["buyer", "seller"] = "buyer"
    language: str = "en"


class ScriptBody(BaseModel):
    product_line: str = Field(..., min_length=2, max_length=2000)
    role: Literal["buyer", "seller"] = "buyer"
    your_company: str = "us"


class FullPackBody(BaseModel):
    product_line: str = Field(..., min_length=2, max_length=2000)
    reference_unit_price: float = Field(..., gt=0)
    currency: str = "INR"
    market_volatility: Literal["low", "medium", "high"] = "medium"
    suppliers: list[SupplierRow] | None = None
    role: Literal["buyer", "seller"] = "buyer"
    your_company: str = "our team"


@router.post("/negotiation/price/estimate")
async def post_negotiation_price_estimate(
    body: PriceEstimateBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "view_personal", "run_research")),
) -> dict[str, Any]:
    return estimate_price_model(
        reference_unit_price=body.reference_unit_price,
        currency=body.currency,
        market_volatility=body.market_volatility,
        product_note=body.product_note,
    )


@router.post("/negotiation/suppliers/compare")
async def post_negotiation_suppliers_compare(
    body: CompareBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "view_personal", "run_research")),
) -> dict[str, Any]:
    rows = [r.model_dump() for r in body.suppliers]
    return compare_suppliers(rows, role=body.role)


@router.post("/negotiation/plan")
async def post_negotiation_plan(
    body: NegotiationPlanBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "view_personal", "run_research")),
) -> dict[str, Any]:
    return build_negotiation_suggestions(
        price_model=body.price_model,
        role=body.role,
        target_margin_buffer_pct=body.target_margin_buffer_pct,
    )


@router.post("/negotiation/templates")
async def post_negotiation_templates(
    body: TemplateBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "view_personal", "run_research")),
) -> dict[str, Any]:
    return generate_message_templates(
        product_line=body.product_line,
        supplier_name=body.supplier_name,
        your_company=body.your_company,
        role=body.role,
        language=body.language,
    )


@router.post("/negotiation/script")
async def post_negotiation_script(
    body: ScriptBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "view_personal", "run_research")),
) -> dict[str, Any]:
    return generate_negotiation_script(
        product_line=body.product_line, role=body.role, your_company=body.your_company
    )


@router.post("/negotiation/pack")
async def post_negotiation_pack(
    body: FullPackBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "view_personal", "run_research")),
) -> dict[str, Any]:
    sup = [r.model_dump() for r in (body.suppliers or [])] if body.suppliers else None
    return full_negotiation_pack(
        product_line=body.product_line,
        reference_unit_price=body.reference_unit_price,
        currency=body.currency,
        market_volatility=body.market_volatility,
        suppliers=sup,
        role=body.role,
        your_company=body.your_company,
    )


@router.get("/negotiation/research/hints")
async def get_negotiation_research_hints(
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "view_personal", "run_research")),
    product_line: str = Query(..., min_length=2, max_length=500),
    max_results: int = Query(10, ge=3, le=25),
) -> dict[str, Any]:
    return enrich_with_market_research(product_line, max_results=max_results)
