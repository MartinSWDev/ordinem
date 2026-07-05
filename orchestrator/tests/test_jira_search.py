"""JQL search pagination + normalization, with httpx mocked (no live Jira)."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.services.jira import JiraClient


def _settings() -> Settings:
    return Settings(
        jira_base_url="https://example.atlassian.net",
        jira_email="me@example.com",
        jira_api_token="token",
    )


def _issue(key: str, summary: str, project: str = "PROJ") -> dict:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "project": {"key": project},
            "description": None,
        },
    }


async def test_search_paginates_via_next_page_token(monkeypatch):
    # Two pages: first returns a token, second has no token -> stop.
    pages = [
        {"issues": [_issue("PROJ-1", "one"), _issue("PROJ-2", "two")], "nextPageToken": "tok"},
        {"issues": [_issue("PROJ-3", "three")]},
    ]
    calls: list[dict] = []

    async def fake_post(self, url, json=None, auth=None):
        calls.append(json)
        idx = len(calls) - 1
        return httpx.Response(200, json=pages[idx])

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = JiraClient(_settings())
    issues = await client.search_issues("project = PROJ")

    assert [i["jira_key"] for i in issues] == ["PROJ-1", "PROJ-2", "PROJ-3"]
    assert [i["title"] for i in issues] == ["one", "two", "three"]
    # second call must carry the token from page one
    assert calls[0].get("nextPageToken") is None
    assert calls[1].get("nextPageToken") == "tok"


async def test_search_stops_on_is_last(monkeypatch):
    async def fake_post(self, url, json=None, auth=None):
        return httpx.Response(
            200, json={"issues": [_issue("PROJ-9", "last")], "nextPageToken": "x", "isLast": True}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = JiraClient(_settings())
    issues = await client.search_issues("project = PROJ")
    assert len(issues) == 1  # did not loop despite a token, because isLast


async def test_search_raises_on_http_error(monkeypatch):
    async def fake_post(self, url, json=None, auth=None):
        return httpx.Response(400, text="bad jql")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = JiraClient(_settings())
    from app.services.jira import JiraError

    with pytest.raises(JiraError):
        await client.search_issues("nonsense")
