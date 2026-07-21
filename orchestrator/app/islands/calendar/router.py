"""Read-only calendar feed route, plus the Google Calendar OAuth connect flow.

Source precedence for GET /calendar: if Google OAuth is configured AND
connected, it wins; otherwise the private-ICS feeds; otherwise 503.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import Settings
from app.core.deps import get_config, get_pool
from app.islands.calendar import google_oauth
from app.islands.calendar.service import (
    CalendarClient,
    CalendarError,
    GoogleCalendarClient,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("")
async def upcoming_events(
    settings: Settings = Depends(get_config),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    if settings.google_oauth_configured:
        state = await google_oauth.status(pool, settings)
        if state["connected"]:
            try:
                return await GoogleCalendarClient(pool, settings).upcoming()
            except CalendarError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not settings.calendar_urls:
            raise HTTPException(
                status_code=503,
                detail="Google Calendar is configured but not connected — open /calendar/oauth/start",
            )
    if not settings.calendar_urls:
        raise HTTPException(
            status_code=503,
            detail="no calendar source configured (set CALENDAR_ICS_URLS or connect Google Calendar)",
        )
    try:
        return await CalendarClient(settings).upcoming()
    except CalendarError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/oauth/status")
async def oauth_status(
    settings: Settings = Depends(get_config),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Whether Google Calendar is configured and connected — drives a Connect
    button and its state."""
    return await google_oauth.status(pool, settings)


@router.get("/oauth/start")
async def oauth_start(
    settings: Settings = Depends(get_config),
    pool: asyncpg.Pool = Depends(get_pool),
) -> RedirectResponse:
    """Begin the consent flow: open this URL in a browser and it bounces to
    Google, which redirects back to /oauth/callback."""
    try:
        url = await google_oauth.start_authorization(pool, settings)
    except google_oauth.GoogleOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=307)


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    state: str = "",
    code: str = "",
    error: str = "",
    settings: Settings = Depends(get_config),
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    """Google redirects here after consent. Exchanges the code for tokens and
    renders a tiny close-me page."""
    if error:
        return _page(f"Google returned an error: {error}", ok=False)
    if not code:
        return _page("No authorization code in the callback.", ok=False)
    try:
        await google_oauth.complete_authorization(pool, settings, code, state)
    except google_oauth.GoogleOAuthError as exc:
        return _page(str(exc), ok=False)
    return _page("Google Calendar connected. You can close this tab.", ok=True)


def _page(message: str, *, ok: bool) -> HTMLResponse:
    color = "#1f9d55" if ok else "#c0392b"
    html = (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:system-ui;padding:3rem;text-align:center'>"
        f"<p style='font-size:1.1rem;color:{color}'>{message}</p></body>"
    )
    return HTMLResponse(html, status_code=200 if ok else 400)
