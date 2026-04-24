"""Scientific validation: cross-source checks, credibility, contradictions, uncertainty."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.scientific_validation_engine import (
    multi_source_validate,
    score_source_credibility,
    validate_existing_research,
)

router = APIRouter(tags=["Scientific validation"])


class MultiSourceBody(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    cross_query: str | None = Field(None, max_length=2000)
    use_llm: bool = True


@router.get("/scientific-validation/source-credibility")
async def get_source_credibility(
    url: str = Query(..., min_length=4, max_length=4000),
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    _ = user
    return score_source_credibility(url)


@router.post("/scientific-validation/cross-check")
async def post_cross_check(
    body: MultiSourceBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    _ = user
    return multi_source_validate(
        str(body.query).strip(),
        cross_query=body.cross_query,
        use_llm=body.use_llm,
    )


class ExistingBody(BaseModel):
    research: dict[str, Any] = Field(default_factory=dict)
    cross_text: str | None = None
    extra_urls: list[str] = Field(default_factory=list)
    use_llm: bool = True


@router.post("/scientific-validation/validate-corpus")
async def post_validate_corpus(
    body: ExistingBody,
    user: CurrentUser = Depends(require_permission("run_research", "manage_business", "trade_stock")),
) -> dict[str, Any]:
    _ = user
    return validate_existing_research(
        body.research,
        cross_text=body.cross_text,
        extra_urls=body.extra_urls,
        use_llm=body.use_llm,
    )
