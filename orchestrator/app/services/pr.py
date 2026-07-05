"""PR draft generation (section 8). Parse an existing PR template's named
sections, auto-fill what's derivable from the ticket + commit messages, and
leave everything else blank for the human.
"""

from __future__ import annotations

import re
from pathlib import Path

# Common locations for a repo's PR template.
_TEMPLATE_CANDIDATES = [
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
]

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def find_template(repo_path: str) -> Path | None:
    repo = Path(repo_path)
    for rel in _TEMPLATE_CANDIDATES:
        p = repo / rel
        if p.exists():
            return p
    return None


def parse_sections(template_text: str) -> dict[str, str]:
    """Split a markdown template into {heading: body} named sections. Content
    before the first heading is stored under the empty-string key."""
    sections: dict[str, str] = {}
    current = ""
    buf: list[str] = []
    for line in template_text.splitlines():
        m = _HEADING.match(line)
        if m:
            sections[current] = "\n".join(buf).strip()
            current = m.group(2).strip()
            buf = []
        else:
            buf.append(line)
    sections[current] = "\n".join(buf).strip()
    return sections


def build_template_fields(
    *,
    repo_path: str,
    jira_key: str,
    jira_browse_url: str,
    ticket_title: str,
    commit_messages: list[str],
) -> dict:
    """Produce the template_fields payload for a pr_drafts row.

    Auto-fills a 'Summary'-like section from the ticket title/commits and links
    the ticket; any other named section is left blank for the human.
    """
    template = find_template(repo_path)
    fields: dict = {
        "ticket_link": jira_browse_url,
        "jira_key": jira_key,
        "title": ticket_title,
    }

    summary_lines = [ticket_title]
    if commit_messages:
        summary_lines.append("")
        summary_lines.extend(f"- {m.splitlines()[0]}" for m in commit_messages)
    summary = "\n".join(summary_lines)

    if template is None:
        fields["sections"] = {"Summary": summary}
        fields["template_found"] = False
        return fields

    sections = parse_sections(template.read_text())
    filled: dict[str, str] = {}
    for name, body in sections.items():
        if not name:
            continue
        lname = name.lower()
        if "summary" in lname or "description" in lname or "what" in lname:
            filled[name] = summary
        elif "ticket" in lname or "jira" in lname or "link" in lname:
            filled[name] = jira_browse_url
        else:
            filled[name] = ""  # leave blank for the human
    fields["sections"] = filled
    fields["template_found"] = True
    fields["template_path"] = str(template)
    return fields
