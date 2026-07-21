"""Google Calendar OAuth source: auth-URL construction and event normalization
(the pieces that don't need Google or a DB)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.core.config import Settings
from app.islands.calendar.google_oauth import SCOPES, build_auth_url
from app.islands.calendar.service import normalize_google_events


def _settings(**over) -> Settings:
    base = dict(
        _env_file=None,
        google_client_id="cid.apps.googleusercontent.com",
        google_client_secret="secret",
    )
    base.update(over)
    return Settings(**base)


def test_build_auth_url_carries_offline_consent_and_state():
    url = build_auth_url(_settings(), "the-state")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid.apps.googleusercontent.com"]
    assert q["scope"] == [SCOPES]
    assert q["access_type"] == ["offline"]  # required to get a refresh token
    assert q["prompt"] == ["consent"]
    assert q["response_type"] == ["code"]
    assert q["state"] == ["the-state"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8787/calendar/oauth/callback"]


def test_normalize_timed_and_all_day_events():
    payload = {
        "summary": "Work",
        "items": [
            {
                "id": "a",
                "summary": "Standup",
                "location": "Meet",
                "start": {"dateTime": "2026-07-13T09:30:00+00:00"},
                "end": {"dateTime": "2026-07-13T10:00:00+00:00"},
            },
            {
                "id": "b",
                "summary": "Away",
                "start": {"date": "2026-07-14"},
                "end": {"date": "2026-07-15"},
            },
        ],
    }
    events = normalize_google_events(payload)
    assert [e["title"] for e in events] == ["Standup", "Away"]
    assert events[0]["all_day"] is False
    assert events[0]["calendar_name"] == "Work"
    assert events[0]["location"] == "Meet"
    assert events[1]["all_day"] is True
    # start/end are ISO strings, matching the ICS source's shape
    assert events[0]["start"].startswith("2026-07-13T09:30")
    assert events[1]["location"] is None


def test_normalize_skips_cancelled_and_untitled_default():
    payload = {
        "summary": "Cal",
        "items": [
            {"id": "x", "status": "cancelled", "start": {"date": "2026-07-14"}, "end": {"date": "2026-07-15"}},
            {"id": "y", "start": {"dateTime": "2026-07-13T09:00:00Z"}, "end": {"dateTime": "2026-07-13T10:00:00Z"}},
        ],
    }
    events = normalize_google_events(payload)
    assert len(events) == 1
    assert events[0]["title"] == "Untitled event"


# --- token lifecycle (fake pool, mocked token endpoint) ------------------------

from datetime import datetime, timedelta, timezone

import pytest

from app.islands.calendar import google_oauth


class _FakeConn:
    def __init__(self, store):
        self._store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetchrow(self, query, *args):
        return self._store.get("row")

    async def execute(self, query, *args):
        self._store.setdefault("executed", []).append((query, args))


class _FakePool:
    def __init__(self, store):
        self._store = store

    def acquire(self):
        return _FakeConn(self._store)


async def test_valid_access_token_returns_cached_when_fresh(monkeypatch):
    store = {
        "row": {
            "refresh_token": "r",
            "access_token": "cached",
            "token_expiry": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
    }

    async def boom(_):
        raise AssertionError("should not refresh a fresh token")

    monkeypatch.setattr(google_oauth, "_token_request", boom)
    token = await google_oauth.valid_access_token(_FakePool(store), _settings())
    assert token == "cached"


async def test_valid_access_token_refreshes_when_expired(monkeypatch):
    store = {
        "row": {
            "refresh_token": "r",
            "access_token": "stale",
            "token_expiry": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
    }

    async def fake_refresh(data):
        assert data["grant_type"] == "refresh_token"
        return {"access_token": "brand-new", "expires_in": 3600}

    monkeypatch.setattr(google_oauth, "_token_request", fake_refresh)
    token = await google_oauth.valid_access_token(_FakePool(store), _settings())
    assert token == "brand-new"


async def test_valid_access_token_errors_when_not_connected():
    store = {"row": None}
    with pytest.raises(google_oauth.GoogleOAuthError, match="not connected"):
        await google_oauth.valid_access_token(_FakePool(store), _settings())


async def test_complete_authorization_requires_refresh_token(monkeypatch):
    store = {"row": {"pending_state": "s"}}

    async def no_refresh(data):
        return {"access_token": "a", "expires_in": 3600}  # no refresh_token

    monkeypatch.setattr(google_oauth, "_token_request", no_refresh)
    with pytest.raises(google_oauth.GoogleOAuthError, match="no refresh token"):
        await google_oauth.complete_authorization(_FakePool(store), _settings(), "code", "s")


async def test_complete_authorization_rejects_state_mismatch():
    store = {"row": {"pending_state": "expected"}}
    with pytest.raises(google_oauth.GoogleOAuthError, match="state mismatch"):
        await google_oauth.complete_authorization(_FakePool(store), _settings(), "code", "wrong")
