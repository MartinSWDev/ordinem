"""Turn a ticket into proposed mini-tickets, for a human to approve.

This is the planning half of the multi-agent flow: one cheap structured call
decomposes the ticket into independently-dispatchable units of work, each of
which later gets its own agent session and worktree. It deliberately does NOT
dispatch anything — the output is a proposal that lands in `proposed` status
and waits for the user to edit and approve it.

Splitting well matters more than splitting a lot: two mini-tickets that touch
the same files will fight in separate worktrees, so the prompt pushes for
file-disjoint units and lets the planner return a single mini-ticket when the
work genuinely doesn't decompose.
"""

from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic

from app.core.config import Settings
from app.islands.tickets.schemas import ProposedSubtask

SYSTEM_PROMPT = """\
You are a tech lead breaking a ticket into mini-tickets. Each mini-ticket is
handed to a separate coding agent working in its OWN git worktree, in parallel
with the others.

Because they run in parallel on separate checkouts, mini-tickets MUST be
file-disjoint: two agents editing the same file will conflict. Prefer fewer,
well-separated units over many overlapping ones. If the ticket does not
genuinely decompose, return exactly one mini-ticket covering all of it — that
is a good answer, not a failure.

For each mini-ticket give:
- title: short imperative summary.
- description: everything the agent needs to do the work without seeing this
  ticket — the relevant context, the expected outcome, and any constraint from
  the processing instructions that applies to it. Assume no other context.
- needs_docker: true only if the work must run against the running docker
  environment (integration tests, migrations against a live DB, service calls).
  Only ONE docker mini-ticket runs at a time, so setting this serializes it.

Order them so that anything others depend on comes first.

<processing_instructions>
{instructions}
</processing_instructions>

The user's processing instructions above are authoritative — follow them over
your own defaults.
"""

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mini_tickets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "needs_docker": {"type": "boolean"},
                },
                "required": ["title", "description", "needs_docker"],
            },
        },
    },
    "required": ["mini_tickets"],
}


def _client(settings: Settings, *, base_url: str | None = None) -> AsyncAnthropic:
    kwargs: dict[str, Any] = {}
    url = base_url or settings.anthropic_base_url
    if url:
        kwargs["base_url"] = url
    if settings.anthropic_api_key:
        kwargs["api_key"] = settings.anthropic_api_key
    return AsyncAnthropic(**kwargs)


async def _call(
    client: AsyncAnthropic, model: str, system: str, ticket_text: str
) -> dict[str, Any]:
    async with client.messages.stream(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema", "schema": PLAN_SCHEMA},
            "effort": "high",
        },
        system=system,
        messages=[{"role": "user", "content": ticket_text}],
    ) as stream:
        message = await stream.get_final_message()
    text = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
    return json.loads(text)


def build_ticket_text(
    title: str, description: str | None, jira: dict | None = None
) -> str:
    """The ticket as the planner sees it. Acceptance criteria live in the Jira
    body, so the curated description carries them when present."""
    parts = [f"# {title}"]
    if description:
        parts.append(description)
    if jira and jira.get("acceptance_criteria"):
        parts.append(f"## Acceptance criteria\n{jira['acceptance_criteria']}")
    return "\n\n".join(parts)


async def plan_ticket(
    *,
    title: str,
    description: str | None,
    processing_instructions: str | None,
    settings: Settings,
    jira: dict | None = None,
) -> list[ProposedSubtask]:
    """Propose mini-tickets for a ticket. Claude first, Qwen proxy on failure —
    same fallback reasoning as the reviewer and the ticket agent."""
    system = SYSTEM_PROMPT.format(
        instructions=processing_instructions or "(none given — use your judgement)"
    )
    ticket_text = build_ticket_text(title, description, jira)
    try:
        data = await _call(_client(settings), settings.review_model, system, ticket_text)
    except Exception:
        if not settings.qwen_configured:
            raise
        qclient = _client(settings, base_url=settings.qwen_proxy_url)
        data = await _call(qclient, settings.review_model, system, ticket_text)
    return [ProposedSubtask(**m) for m in data["mini_tickets"]]
