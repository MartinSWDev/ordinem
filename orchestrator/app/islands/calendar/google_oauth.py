"""Google Calendar OAuth 2.0 (read-only) — the authorization-code flow and
token lifecycle for the calendar island.

No Google client library: the three endpoints (authorize, token, refresh) are
plain HTTP, matching the ICS source's dependency-light style. The single token
set lives in the `google_oauth` table (single-user tool); `valid_access_token`
transparently refreshes the short-lived access token from the refresh token.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import asyncpg
import httpx

from app.core.config import Settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/calendar.readonly"

_ROW_ID = "default"


class GoogleOAuthError(RuntimeError):
    pass


def build_auth_url(settings: Settings, state: str) -> str:
    """The URL to send the user to for consent. access_type=offline +
    prompt=consent guarantees a refresh token every time."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


async def _row(conn: asyncpg.Connection) -> asyncpg.Record | None:
    return await conn.fetchrow("select * from google_oauth where id = $1", _ROW_ID)


async def start_authorization(pool: asyncpg.Pool, settings: Settings) -> str:
    """Persist a fresh CSRF state and return the consent URL."""
    if not settings.google_oauth_configured:
        raise GoogleOAuthError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set")
    state = secrets.token_urlsafe(24)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into google_oauth (id, pending_state, updated_at)
            values ($1, $2, now())
            on conflict (id) do update set pending_state = $2, updated_at = now()
            """,
            _ROW_ID,
            state,
        )
    return build_auth_url(settings, state)


async def _token_request(data: dict) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(TOKEN_ENDPOINT, data=data)
    if resp.status_code >= 400:
        # Google returns {"error": ..., "error_description": ...}
        detail = resp.text
        try:
            body = resp.json()
            detail = body.get("error_description") or body.get("error") or detail
        except ValueError:
            pass
        raise GoogleOAuthError(f"token request failed: {detail}")
    return resp.json()


async def complete_authorization(
    pool: asyncpg.Pool, settings: Settings, code: str, state: str
) -> None:
    """Validate the CSRF state, exchange the code, and store the tokens."""
    async with pool.acquire() as conn:
        row = await _row(conn)
    if row is None or not row["pending_state"] or state != row["pending_state"]:
        raise GoogleOAuthError("state mismatch — restart the connect flow")

    tokens = await _token_request(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "grant_type": "authorization_code",
        }
    )
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise GoogleOAuthError(
            "Google returned no refresh token — revoke the app's access in your "
            "Google account and reconnect (consent must be re-granted)"
        )
    expiry = datetime.now(timezone.utc) + timedelta(
        seconds=int(tokens.get("expires_in", 3600))
    )
    async with pool.acquire() as conn:
        await conn.execute(
            """
            update google_oauth
            set refresh_token = $2, access_token = $3, token_expiry = $4,
                scopes = $5, pending_state = null, connected_at = now(),
                updated_at = now()
            where id = $1
            """,
            _ROW_ID,
            refresh_token,
            tokens.get("access_token"),
            expiry,
            tokens.get("scope", SCOPES),
        )


async def valid_access_token(pool: asyncpg.Pool, settings: Settings) -> str:
    """A usable access token, refreshing from the refresh token if the current
    one is missing or within 60s of expiry."""
    async with pool.acquire() as conn:
        row = await _row(conn)
    if row is None or not row["refresh_token"]:
        raise GoogleOAuthError("not connected to Google Calendar")

    fresh_enough = (
        row["access_token"]
        and row["token_expiry"]
        and row["token_expiry"] > datetime.now(timezone.utc) + timedelta(seconds=60)
    )
    if fresh_enough:
        return row["access_token"]

    tokens = await _token_request(
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": row["refresh_token"],
            "grant_type": "refresh_token",
        }
    )
    access_token = tokens.get("access_token")
    expiry = datetime.now(timezone.utc) + timedelta(
        seconds=int(tokens.get("expires_in", 3600))
    )
    async with pool.acquire() as conn:
        await conn.execute(
            "update google_oauth set access_token = $2, token_expiry = $3, "
            "updated_at = now() where id = $1",
            _ROW_ID,
            access_token,
            expiry,
        )
    return access_token


async def status(pool: asyncpg.Pool, settings: Settings) -> dict:
    async with pool.acquire() as conn:
        row = await _row(conn)
    connected = bool(row and row["refresh_token"])
    return {
        "configured": settings.google_oauth_configured,
        "connected": connected,
        "scopes": (row["scopes"] if row else None),
        "connected_at": (row["connected_at"].isoformat() if row and row["connected_at"] else None),
        "calendars": settings.google_calendar_id_list,
    }
