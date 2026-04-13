"""Third-party integrations (Google Calendar OAuth)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from api.dependencies import CurrentUser, get_current_user
from services import google_calendar_integration_service as gcal

router = APIRouter(tags=["Integrations"])


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
    base = "/static/command_center/index.html#/personal/integrations"
    if error:
        return RedirectResponse(url=f"{base}?gcal_error={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(url=f"{base}?gcal_error=missing_code", status_code=302)
    ok, msg, _uid = gcal.handle_oauth_callback(code=code, state=state)
    if not ok:
        safe = quote((msg or "failed").replace("&", " ")[:400], safe="")
        return RedirectResponse(url=f"{base}?gcal_error={safe}", status_code=302)
    return RedirectResponse(url=f"{base}?gcal=connected", status_code=302)


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
