"""Part E: build + deploy static business microsites."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, ensure_org_membership, get_current_user
from services.website_builder_service import (
    build_website_sync,
    read_site_iframe_preview_sync,
    user_can_access_org_sync,
)
from services.website_db_service import get_generated_website_sync
from services.website_deploy_service import deploy_site_sync

router = APIRouter(prefix="/website-builder", tags=["Website Builder"])


def _uid(user: CurrentUser) -> int:
    uid = int(user.id)
    if uid <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return uid


class BuildBody(BaseModel):
    organization_id: int | None = Field(None, description="Defaults to JWT active org")
    template_type: str = Field("shop", max_length=32)
    deploy: bool = Field(False, description="If true, run nginx deploy step after build")


class DeployBody(BaseModel):
    organization_id: int | None = Field(None, description="Defaults to JWT active org")


@router.post("/build", summary="Generate static site files + metadata")
async def post_build(body: BuildBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    oid = int(body.organization_id or user.organization_id)
    if oid <= 0:
        raise HTTPException(status_code=400, detail="organization_id required")
    ensure_org_membership(user, oid)
    out = build_website_sync(
        oid,
        body.template_type,
        user_id=_uid(user),
        run_deploy=bool(body.deploy),
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "build failed")
    return out


@router.post("/deploy", summary="Write nginx vhost for last built slug (optional reload)")
async def post_deploy(body: DeployBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    oid = int(body.organization_id or user.organization_id)
    if not user_can_access_org_sync(user_id=_uid(user), organization_id=oid):
        raise HTTPException(status_code=403, detail="forbidden")
    meta = get_generated_website_sync(oid)
    if not meta.get("ok"):
        raise HTTPException(status_code=400, detail="build site first")
    slug = str(meta.get("slug") or "")
    dep = deploy_site_sync(slug)
    if not dep.get("ok"):
        raise HTTPException(status_code=400, detail=dep.get("error") or "deploy failed")
    return dep


@router.get("/preview/{organization_id}", summary="Latest site HTML with inlined CSS/JS for iframe preview")
async def get_preview(organization_id: int, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    out = read_site_iframe_preview_sync(int(organization_id), user_id=_uid(user))
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error") or "not found")
    return {"ok": True, "html": out["html"], "slug": out.get("slug"), "public_url": out.get("public_url")}


@router.get("/meta/{organization_id}", summary="Stored URL + slug for UI")
async def get_meta(organization_id: int, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    oid = int(organization_id)
    if not user_can_access_org_sync(user_id=_uid(user), organization_id=oid):
        raise HTTPException(status_code=403, detail="forbidden")
    meta = get_generated_website_sync(oid)
    if not meta.get("ok"):
        return {"ok": False, "error": "not found"}
    return meta
