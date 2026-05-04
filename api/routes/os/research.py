"""
OS-level research API routes using DuckDuckGo search.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.dependencies import CurrentUser, require_roles
from services.research_engine_service import perform_duckduckgo_research

router = APIRouter(
    prefix="/os/research",
    tags=["OS Research"],
)


class ResearchQuery(BaseModel):
    """Web research query payload."""
    
    query: str
    max_results: int = 10


class ResearchResult(BaseModel):
    """Research result structure."""
    
    query: str
    results: list[dict[str, Any]]
    total_results: int


@router.post("/search", response_model=ResearchResult)
async def search_web(
    body: ResearchQuery,
    user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> ResearchResult:
    """
    Perform web research using DuckDuckGo.
    
    Requires research permissions.
    """
    try:
        results = perform_duckduckgo_research(
            query=body.query,
            max_results=body.max_results
        )
        return ResearchResult(
            query=body.query,
            results=results,
            total_results=len(results)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Research failed: {str(exc)}"
        )