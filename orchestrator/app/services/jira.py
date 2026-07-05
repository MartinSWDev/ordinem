"""Jira ingestion (section 6). Real client over the Jira Cloud REST API v3.

Lights up as soon as JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN are set in
.env. Until then, callers get a clear JiraNotConfigured error rather than a
silent failure.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings


class JiraNotConfigured(RuntimeError):
    pass


class JiraError(RuntimeError):
    pass


def _adf_to_text(node: Any) -> str:
    """Flatten Atlassian Document Format (description/fields come as ADF JSON)
    into plain text. Good enough for the structured pane; the iframe (section 6)
    is there for anything this doesn't render cleanly."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        if node.get("type") in ("hardBreak", "paragraph"):
            return _adf_to_text(node.get("content")) + "\n"
        return _adf_to_text(node.get("content"))
    return ""


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.jira_configured:
            raise JiraNotConfigured(
                "Set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN in .env"
            )
        self._base = settings.jira_base_url.rstrip("/")
        self._auth = (settings.jira_email, settings.jira_api_token)
        self._ac_field = settings.jira_acceptance_criteria_field or None

    async def fetch_issue(self, jira_key: str) -> dict[str, Any]:
        """Pull key, summary, description, acceptance criteria, comments and the
        attachments list. Returns a normalized dict plus the raw payload."""
        url = f"{self._base}/rest/api/3/issue/{jira_key}"
        params = {"fields": "*all", "expand": "renderedFields"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, auth=self._auth)
        if resp.status_code == 404:
            raise JiraError(f"Jira issue {jira_key} not found")
        if resp.status_code >= 400:
            raise JiraError(f"Jira API error {resp.status_code} for {jira_key}")

        raw = resp.json()
        fields = raw.get("fields", {})

        acceptance = None
        if self._ac_field:
            acceptance = _adf_to_text(fields.get(self._ac_field)).strip() or None

        comments = [
            {
                "author": (c.get("author") or {}).get("displayName"),
                "body": _adf_to_text(c.get("body")).strip(),
                "created": c.get("created"),
            }
            for c in (fields.get("comment", {}) or {}).get("comments", [])
        ]
        attachments = [
            {"filename": a.get("filename"), "url": a.get("content"), "size": a.get("size")}
            for a in (fields.get("attachment") or [])
        ]

        project_key = (fields.get("project") or {}).get("key") or jira_key.split("-")[0]

        return {
            "jira_key": raw.get("key", jira_key),
            "project_key": project_key,
            "title": fields.get("summary") or jira_key,
            "description": _adf_to_text(fields.get("description")).strip() or None,
            "acceptance_criteria": acceptance,
            "comments": comments,
            "attachments": attachments,
            "raw_jira": raw,
        }

    def issue_browse_url(self, jira_key: str) -> str:
        """The human-facing Jira URL for the iframe (section 6)."""
        return f"{self._base}/browse/{jira_key}"
