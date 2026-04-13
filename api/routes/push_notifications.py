"""Web Push (VAPID) — public key, subscribe, unsubscribe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from services import web_push_service as wps

router = APIRouter(prefix="/push", tags=["Web Push"])


class PushKeysBody(BaseModel):
    p256dh: str = Field(..., min_length=1, max_length=512)
    auth: str = Field(..., min_length=1, max_length=256)


class PushSubscribeBody(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=4096)
    keys: PushKeysBody


class PushUnsubscribeBody(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=4096)


@router.get("/vapid-public-key", summary="VAPID public key for PushManager.subscribe")
async def vapid_public_key() -> dict[str, Any]:
    key = wps.vapid_public_key_b64u()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Web Push not configured (set THIRAMAI_VAPID_PUBLIC_KEY, THIRAMAI_VAPID_PRIVATE_KEY, THIRAMAI_VAPID_SUBJECT).",
        )
    return {"public_key": key}


@router.post("/subscribe", summary="Register browser push subscription")
async def push_subscribe(
    body: PushSubscribeBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    if not wps.vapid_configured():
        raise HTTPException(status_code=503, detail="Web Push not configured on server")
    ok, msg = wps.save_subscription_sync(
        user_id=int(user.id),
        endpoint=body.endpoint.strip(),
        keys={"p256dh": body.keys.p256dh.strip(), "auth": body.keys.auth.strip()},
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "status": msg}


@router.delete("/unsubscribe", summary="Remove push subscription for this endpoint")
@router.post("/unsubscribe", summary="Remove push subscription (POST alias for clients without DELETE body)")
async def push_unsubscribe(
    body: PushUnsubscribeBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    ok, msg = wps.delete_subscription_sync(user_id=int(user.id), endpoint=body.endpoint.strip())
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "status": msg}
