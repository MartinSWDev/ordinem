"""Jira ingestion (section 6). Real client over the Jira Cloud REST API v3.

Lights up as soon as JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN are set in
.env. Until then, callers get a clear JiraNotConfigured error rather than a
silent failure.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings


class JiraNotConfigured(RuntimeError):
    pass


class JiraError(RuntimeError):
    pass


def _adf_to_text(node: Any) -> str:
    """Flatten Atlassian Document Format (description/fields come as ADF JSON)
    into plain text.

    A naive two-level walk drops anything nested in lists, tables, panels, etc.
    — which is exactly where 'what to do' (acceptance criteria) usually lives.
    So we recurse through block types (adapted from the proven rocky_ai walk).
    """
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    ntype = node.get("type")
    if ntype == "text":
        text = node.get("text", "")
        # Preserve hyperlinks as markdown so the href survives for the LLM
        # (and can be linkified in the UI) instead of being flattened away.
        for mark in node.get("marks") or []:
            if mark.get("type") == "link":
                href = (mark.get("attrs") or {}).get("href")
                if href:
                    text = f"[{text}]({href})"
        return text
    if ntype == "hardBreak":
        return "\n"
    # Inline / block images (ADF media) — keep a marker so the reader knows an
    # image was here; the actual bytes are served via the attachment proxy.
    if ntype in ("media", "mediaInline"):
        attrs = node.get("attrs") or {}
        label = attrs.get("alt") or attrs.get("id") or "image"
        return f"[image: {label}]"
    inner = "".join(_adf_to_text(c) for c in node.get("content", []))
    if ntype == "listItem":
        return "- " + inner.strip() + "\n"
    if ntype in ("paragraph", "heading", "tableRow", "codeBlock", "blockquote"):
        return inner + "\n"
    if ntype in ("mediaSingle", "mediaGroup"):
        return inner + "\n"
    return inner


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.jira_configured:
            raise JiraNotConfigured(
                "Set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN in .env"
            )
        self._base = settings.jira_base_url.rstrip("/")
        self._auth = (settings.jira_email, settings.jira_api_token)
        self._ac_field = settings.jira_acceptance_criteria_field or None

    # Named fields to pull in bulk search — enough to render list + a rich
    # normalized view, without the full *all firehose. Comments/attachments are
    # left to the per-detail fetch (fetch_issue uses *all).
    _SEARCH_FIELDS = [
        "summary",
        "description",
        "status",
        "priority",
        "issuetype",
        "project",
        "assignee",
        "reporter",
        "labels",
        "components",
        "parent",
        "subtasks",
        "issuelinks",
        "fixVersions",
        "duedate",
        "created",
        "updated",
    ]

    def _search_fields(self) -> list[str]:
        fields = list(self._SEARCH_FIELDS)
        if self._ac_field:
            fields.append(self._ac_field)
        return fields

    def _rich_jira(self, raw: dict[str, Any], jira_key: str) -> dict[str, Any]:
        """Curated, LLM-useful projection of a Jira issue — the subset an agent
        actually needs, instead of raw_jira's ~120 keys.

        Missing sub-fields degrade to None/[]; comments and attachments only
        populate when the payload carried them (i.e. from fetch_issue's *all)."""
        f = raw.get("fields", {}) or {}

        def name(v: Any) -> Any:
            return v.get("name") if isinstance(v, dict) else None

        def display(v: Any) -> Any:
            return v.get("displayName") if isinstance(v, dict) else None

        parent = f.get("parent") or None
        acceptance = None
        if self._ac_field:
            acceptance = _adf_to_text(f.get(self._ac_field)).strip() or None

        comments = [
            {
                "author": display(c.get("author")),
                "created": c.get("created"),
                "body": _adf_to_text(c.get("body")).strip(),
            }
            for c in (f.get("comment", {}) or {}).get("comments", [])
        ]
        attachments = [
            {
                "filename": a.get("filename"),
                "url": a.get("content"),
                "size": a.get("size"),
                "mime": a.get("mimeType"),
            }
            for a in (f.get("attachment") or [])
        ]
        subtasks = [
            {
                "key": st.get("key"),
                "summary": (st.get("fields") or {}).get("summary"),
                "status": name((st.get("fields") or {}).get("status")),
            }
            for st in (f.get("subtasks") or [])
        ]
        links = []
        for link in f.get("issuelinks") or []:
            rel = (link.get("type") or {})
            if link.get("outwardIssue"):
                other, direction, label = link["outwardIssue"], "outward", rel.get("outward")
            elif link.get("inwardIssue"):
                other, direction, label = link["inwardIssue"], "inward", rel.get("inward")
            else:
                continue
            links.append(
                {
                    "relation": label or rel.get("name"),
                    "direction": direction,
                    "key": other.get("key"),
                    "summary": (other.get("fields") or {}).get("summary"),
                    "status": name((other.get("fields") or {}).get("status")),
                }
            )

        status = f.get("status") or {}
        return {
            "key": jira_key,
            "url": self.issue_browse_url(jira_key),
            "summary": f.get("summary"),
            "issue_type": name(f.get("issuetype")),
            "status": status.get("name"),
            "status_category": (status.get("statusCategory") or {}).get("name"),
            "priority": name(f.get("priority")),
            "labels": f.get("labels") or [],
            "components": [name(c) for c in (f.get("components") or [])],
            "assignee": display(f.get("assignee")),
            "reporter": display(f.get("reporter")),
            "created": f.get("created"),
            "updated": f.get("updated"),
            "due_date": f.get("duedate"),
            "fix_versions": [name(v) for v in (f.get("fixVersions") or [])],
            "parent": {
                "key": parent.get("key"),
                "summary": (parent.get("fields") or {}).get("summary"),
            }
            if parent
            else None,
            "description": _adf_to_text(f.get("description")).strip() or None,
            "acceptance_criteria": acceptance,
            "subtasks": subtasks,
            "links": links,
            "comments": comments,
            "attachments": attachments,
        }

    def _normalize_issue(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw Jira issue payload into the fields we persist: the ticket
        table columns plus a curated `jira` object (and raw_jira for debugging).
        Shared by fetch_issue (single) and search_issues (bulk)."""
        jira_key = raw.get("key", "")
        fields = raw.get("fields", {}) or {}
        project_key = (fields.get("project") or {}).get("key") or (
            jira_key.split("-")[0] if "-" in jira_key else jira_key
        )
        project_name = (fields.get("project") or {}).get("name")
        return {
            "jira_key": jira_key,
            "project_key": project_key,
            "project_name": project_name,
            "title": fields.get("summary") or jira_key,
            "description": _adf_to_text(fields.get("description")).strip() or None,
            "jira": self._rich_jira(raw, jira_key),
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

    async def fetch_attachment(self, url: str) -> tuple[bytes, str]:
        """Download an attachment's bytes with Jira auth. The content endpoint
        302s to a signed media URL, so follow redirects. Returns (bytes,
        content_type). Only URLs on the configured Jira host are allowed —
        callers pass URLs straight from stored issue data, but we guard against
        a poisoned payload pointing the proxy at an arbitrary host."""
        if not url.startswith(self._base):
            raise JiraError("attachment url is not on the configured Jira host")
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, auth=self._auth)
        if resp.status_code >= 400:
            raise JiraError(f"attachment fetch failed ({resp.status_code})")
        return resp.content, resp.headers.get("content-type", "application/octet-stream")
