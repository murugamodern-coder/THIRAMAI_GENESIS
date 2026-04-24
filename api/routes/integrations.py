"""Third-party integrations (Google Calendar OAuth)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from core.settings import get_settings
from services import google_calendar_integration_service as gcal
from services.integration_engine import list_integrations, list_outgoing_message_logs, test_integration, upsert_integration

router = APIRouter(tags=["Integrations"])


class IntegrationUpsertBody(BaseModel):
    type: str = Field(..., min_length=1, max_length=32)
    config_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class IntegrationTestBody(BaseModel):
    type: str = Field(..., min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/integrations", summary="Create or update channel integration")
async def upsert_channel_integration(
    body: IntegrationUpsertBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    out = upsert_integration(
        user_id=int(user.id),
        integration_type=body.type,
        config_json=body.config_json or {},
        enabled=bool(body.enabled),
    )
    if out is None:
        raise HTTPException(status_code=400, detail="Unsupported or invalid integration")
    return {"ok": True, **out}


@router.get("/integrations", summary="List integrations for current user")
async def get_channel_integrations(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"ok": True, "items": list_integrations(int(user.id))}


@router.post("/integrations/test", summary="Test a configured integration")
async def post_test_integration(
    body: IntegrationTestBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    out = test_integration(
        user_id=int(user.id),
        integration_type=body.type,
        payload=body.payload or {},
    )
    return {"ok": bool(out.get("ok")), "result": out}


@router.get("/integrations/logs", summary="List outgoing integration message logs")
async def get_integration_logs(
    limit: int = Query(100, ge=1, le=300),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"ok": True, "items": list_outgoing_message_logs(user_id=int(user.id), limit=limit)}


@router.post("/integrations/google/connect", summary="Start Google Calendar OAuth (returns authorization URL)")
async def google_connect_start(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    if not gcal.oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Google OAuth not configured (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI).",
        )
    try:
        url = gcal.build_authorization_url(user_id=int(user.id))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e) or "oauth url build failed") from e
    return {"authorization_url": url}


@router.get("/auth/google/callback", summary="Google OAuth redirect handler")
async def google_oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
) -> RedirectResponse:
    def _shell(hq: str) -> str:
        return get_settings().command_center_shell_url("personal/integrations", hash_query=hq)

    if error:
        return RedirectResponse(url=_shell(f"gcal_error={error}"), status_code=302)
    if not code or not state:
        return RedirectResponse(url=_shell("gcal_error=missing_code"), status_code=302)
    ok, msg, _uid = gcal.handle_oauth_callback(code=code, state=state)
    if not ok:
        safe = quote((msg or "failed").replace("&", " ")[:400], safe="")
        return RedirectResponse(url=_shell(f"gcal_error={safe}"), status_code=302)
    return RedirectResponse(url=_shell("gcal=connected"), status_code=302)


@router.post("/integrations/google/sync", summary="Push scheduled meetings to Google Calendar")
async def google_sync(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    if not gcal.oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    out = gcal.sync_all_meetings_for_user(user_id=int(user.id))
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "sync failed")
    return out


@router.get("/integrations/google/status", summary="Google Calendar connection status")
async def google_status(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return gcal.integration_status(user_id=int(user.id))


@router.post("/integrations/google/disconnect", summary="Disconnect Google Calendar (clear tokens)")
async def google_disconnect(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return gcal.disconnect_user(user_id=int(user.id))
