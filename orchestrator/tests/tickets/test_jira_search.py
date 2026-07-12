"""JQL search pagination + normalization, with httpx mocked (no live Jira)."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.islands.tickets.services.jira import JiraClient


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
    from app.islands.tickets.services.jira import JiraError

    with pytest.raises(JiraError):
        await client.search_issues("nonsense")


def _rich_settings():
    return Settings(
        jira_base_url="https://example.atlassian.net",
        jira_email="me@example.com",
        jira_api_token="token",
        jira_acceptance_criteria_field="customfield_100",
    )


def test_rich_jira_extracts_llm_useful_fields():
    client = JiraClient(_rich_settings())
    raw = {
        "key": "PROJ-7",
        "fields": {
            "summary": "Do the thing",
            "issuetype": {"name": "Bug"},
            "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
            "priority": {"name": "High"},
            "labels": ["backend", "oauth"],
            "components": [{"name": "auth"}],
            "assignee": {"displayName": "June Dev"},
            "reporter": {"displayName": "PM Person"},
            "description": [{"type": "paragraph", "content": [{"type": "text", "text": "desc"}]}],
            "customfield_100": [{"type": "paragraph", "content": [{"type": "text", "text": "must work"}]}],
            "parent": {"key": "PROJ-1", "fields": {"summary": "Epic"}},
            "subtasks": [{"key": "PROJ-8", "fields": {"summary": "sub", "status": {"name": "To Do"}}}],
            "issuelinks": [
                {
                    "type": {"name": "Blocks", "outward": "blocks"},
                    "outwardIssue": {"key": "PROJ-9", "fields": {"summary": "other", "status": {"name": "Done"}}},
                }
            ],
            "comment": {"comments": [
                {"author": {"displayName": "June Dev"}, "created": "2026-01-01", "body": [{"type": "paragraph", "content": [{"type": "text", "text": "a comment"}]}]}
            ]},
            "attachment": [{"filename": "log.txt", "content": "http://x/log.txt", "size": 12, "mimeType": "text/plain"}],
        },
    }
    j = client._rich_jira(raw, "PROJ-7")
    assert j["priority"] == "High"
    assert j["labels"] == ["backend", "oauth"]
    assert j["assignee"] == "June Dev"
    assert j["acceptance_criteria"] == "must work"
    assert j["parent"]["key"] == "PROJ-1"
    assert j["subtasks"][0]["key"] == "PROJ-8"
    assert j["links"][0]["key"] == "PROJ-9" and j["links"][0]["direction"] == "outward"
    assert j["comments"][0]["author"] == "June Dev"
    assert j["comments"][0]["body"] == "a comment"
    assert j["attachments"][0]["mime"] == "text/plain"


def test_normalize_issue_carries_jira_and_columns():
    client = JiraClient(_rich_settings())
    raw = {"key": "PROJ-1", "fields": {"summary": "S", "project": {"key": "PROJ"}}}
    n = client._normalize_issue(raw)
    assert n["jira_key"] == "PROJ-1"
    assert n["project_key"] == "PROJ"
    assert n["title"] == "S"
    assert n["jira"]["key"] == "PROJ-1"
    assert "raw_jira" in n


def test_adf_preserves_link_href_as_markdown():
    from app.islands.tickets.services.jira import _adf_to_text
    adf = {"type": "paragraph", "content": [
        {"type": "text", "text": "see "},
        {"type": "text", "text": "the doc", "marks": [{"type": "link", "attrs": {"href": "https://ex.com/d"}}]},
    ]}
    out = _adf_to_text(adf)
    assert "[the doc](https://ex.com/d)" in out


def test_adf_marks_inline_media():
    from app.islands.tickets.services.jira import _adf_to_text
    adf = {"type": "mediaSingle", "content": [
        {"type": "media", "attrs": {"id": "abc", "alt": "screenshot.png", "type": "file"}},
    ]}
    out = _adf_to_text(adf)
    assert "[image: screenshot.png]" in out


async def test_fetch_attachment_rejects_foreign_host(monkeypatch):
    from app.islands.tickets.services.jira import JiraError
    client = JiraClient(_settings())
    with pytest.raises(JiraError):
        await client.fetch_attachment("https://evil.example.com/x.png")


async def test_fetch_attachment_returns_bytes(monkeypatch):
    async def fake_get(self, url, auth=None):
        return httpx.Response(200, content=b"PNGDATA", headers={"content-type": "image/png"})
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = JiraClient(_settings())
    data, ctype = await client.fetch_attachment("https://example.atlassian.net/rest/api/3/attachment/content/1")
    assert data == b"PNGDATA"
    assert ctype == "image/png"
