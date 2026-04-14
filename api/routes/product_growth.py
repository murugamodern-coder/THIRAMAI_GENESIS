"""Product growth: onboarding state, demo seed, wow insights, plans, invites."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from core.database import get_session_factory
from services.invite_service import create_invite_code, peek_invite
from services.product_onboarding_service import (
    build_wow_insights_sync,
    get_bootstrap_sync,
    save_product_profile,
    seed_demo_data_sync,
)
from services.product_plans import static_plans_catalog

router = APIRouter(prefix="/product", tags=["Product & growth"])


class OnboardingPatchBody(BaseModel):
    business_done: bool | None = None
    expense_done: bool | None = None
    insights_done: bool | None = None
    wow_ack: bool | None = Field(None, description="Mark wow modal as seen")


@router.get("/bootstrap", summary="Onboarding + plan hints for SPA")
async def product_bootstrap(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        return {"ok": True, "plan": "free", "product_profile": {}, "hints": {}}
    return get_bootstrap_sync(user_id=int(user.id), organization_id=int(user.organization_id))


@router.get("/plans", summary="Public plan catalog (pricing page)")
async def product_plans() -> dict[str, Any]:
    return {"ok": True, "plans": static_plans_catalog()}


@router.post("/onboarding", summary="Update onboarding flags")
async def patch_onboarding(body: OnboardingPatchBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(400, detail="Real user required")
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(503, detail="database unavailable")
    patch: dict[str, Any] = {"onboarding": {}}
    if body.business_done is not None:
        patch["onboarding"]["business_done"] = bool(body.business_done)
    if body.expense_done is not None:
        patch["onboarding"]["expense_done"] = bool(body.expense_done)
    if body.insights_done is not None:
        patch["onboarding"]["insights_done"] = bool(body.insights_done)
    if body.wow_ack is not None:
        patch["wow_shown"] = bool(body.wow_ack)
    with factory() as session:
        with session.begin():
            save_product_profile(session, int(user.id), patch)
    return {"ok": True}


@router.post("/demo-seed", summary="Load sample personal rows for wow moment")
async def demo_seed(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(400, detail="Real user required")
    return seed_demo_data_sync(user_id=int(user.id), organization_id=int(user.organization_id))


@router.get("/wow-insights", summary="Three insights for first-login wow")
async def wow_insights(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(400, detail="Real user required")
    return build_wow_insights_sync(user_id=int(user.id), organization_id=int(user.organization_id))


class InviteCreateResponse(BaseModel):
    ok: bool
    code: str | None = None
    share_url: str | None = None


@router.post("/invite-link", summary="Create invite code for viral loop")
async def invite_link(user: CurrentUser = Depends(get_current_user)) -> InviteCreateResponse:
    if int(user.id) <= 0 or int(user.organization_id) <= 0:
        raise HTTPException(400, detail="Real user and org required")
    code = create_invite_code(inviter_user_id=int(user.id), organization_id=int(user.organization_id))
    if not code:
        return InviteCreateResponse(ok=False, code=None, share_url=None)
    base = (  # client fills host; SPA uses relative /signup
        ""
    )
    share = f"/signup?ref={code}"
    return InviteCreateResponse(ok=True, code=code, share_url=share)


@router.get("/invite/{code}", summary="Resolve invite (signup prefill)")
async def invite_resolve(code: str) -> dict[str, Any]:
    meta = peek_invite(code)
    if not meta:
        return {"ok": False, "error": "invalid_or_expired"}
    return {"ok": True, "organization_id_hint": meta.get("o"), "inviter_user_id": meta.get("u")}
