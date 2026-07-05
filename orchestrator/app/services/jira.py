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

    # Fields worth pulling for both single-issue and bulk search. Acceptance
    # criteria is appended when configured.
    _BASE_FIELDS = [
        "summary",
        "description",
        "status",
        "issuetype",
        "project",
        "updated",
        "comment",
        "attachment",
    ]

    def _search_fields(self) -> list[str]:
        fields = list(self._BASE_FIELDS)
        if self._ac_field:
            fields.append(self._ac_field)
        return fields

    def _normalize_issue(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw Jira issue payload into our normalized ticket dict. Shared
        by fetch_issue (single) and search_issues (bulk)."""
        jira_key = raw.get("key", "")
        fields = raw.get("fields", {}) or {}

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

        project_key = (fields.get("project") or {}).get("key") or (
            jira_key.split("-")[0] if "-" in jira_key else jira_key
        )

        return {
            "jira_key": jira_key,
            "project_key": project_key,
            "title": fields.get("summary") or jira_key,
            "description": _adf_to_text(fields.get("description")).strip() or None,
            "acceptance_criteria": acceptance,
            "comments": comments,
            "attachments": attachments,
            "raw_jira": raw,
        }

    async def fetch_issue(self, jira_key: str) -> dict[str, Any]:
        """Pull a single issue by key. Returns a normalized dict + raw payload."""
        url = f"{self._base}/rest/api/3/issue/{jira_key}"
        params = {"fields": "*all"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, auth=self._auth)
        if resp.status_code == 404:
            raise JiraError(f"Jira issue {jira_key} not found")
        if resp.status_code >= 400:
            raise JiraError(f"Jira API error {resp.status_code} for {jira_key}")
        return self._normalize_issue(resp.json())

    async def search_issues(
        self, jql: str, *, page_size: int = 100, max_issues: int = 5000
    ) -> list[dict[str, Any]]:
        """Run a JQL search and return all matching issues, normalized.

        Uses the current POST /rest/api/3/search/jql endpoint (the old
        /rest/api/3/search was removed Aug 2025). Pagination is token-based via
        nextPageToken — there is no `total`, so we page until no token comes
        back, guarded by max_issues.
        """
        url = f"{self._base}/rest/api/3/search/jql"
        fields = self._search_fields()
        issues: list[dict[str, Any]] = []
        token: str | None = None

        async with httpx.AsyncClient(timeout=30) as client:
            while len(issues) < max_issues:
                body: dict[str, Any] = {
                    "jql": jql,
                    "fields": fields,
                    "maxResults": page_size,
                }
                if token:
                    body["nextPageToken"] = token
                resp = await client.post(url, json=body, auth=self._auth)
                if resp.status_code >= 400:
                    raise JiraError(
                        f"Jira search failed ({resp.status_code}): {resp.text[:300]}"
                    )
                data = resp.json()
                page = data.get("issues", [])
                issues.extend(self._normalize_issue(i) for i in page)

                token = data.get("nextPageToken")
                # End when there's no next token, the API flags the last page,
                # or a page came back empty (defensive against token loops).
                if not token or data.get("isLast") or not page:
                    break

        return issues

    def issue_browse_url(self, jira_key: str) -> str:
        """The human-facing Jira URL for the iframe (section 6)."""
        return f"{self._base}/browse/{jira_key}"
