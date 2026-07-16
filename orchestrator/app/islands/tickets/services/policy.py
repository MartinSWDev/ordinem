"""The fixed policy preamble prepended to every agent dispatch (section 9)."""

from __future__ import annotations

POLICY_PREAMBLE = """\
You are working inside an isolated git worktree on branch {branch_name}.
Do not run `git push` under any circumstances. You may stage and commit
locally with clear, conventional-commit-style messages. Run the project's
existing test and lint commands before considering work complete, and
report failures rather than working around them.
"""

# The conversation protocol: the orchestrator parks the run as awaiting_input
# unless the agent explicitly closes it out, so the user is never shown "done"
# when the agent is actually waiting on them.
CONVERSATION_PROTOCOL = """\
## Talking to Martin
You are in a resumable conversation with Martin (the user). He reads your
final message in the ticket UI and can reply; your session continues with
full context. End your final message with exactly one of these markers on
its own last line:
- AWAITING_REPLY — you need something from him (answers, a decision, review
  of what you did so far). Ask crisply; he will reply.
- WORK_COMPLETE — the ticket's work is finished, tested, and committed.
If you are blocked or the ticket's premise looks wrong, say so and use
AWAITING_REPLY rather than guessing or ending silently.
"""

LEAD_TASK = """\
## Task
Work this ticket to completion in the current worktree. You own the whole
ticket: investigate, decide how to split the work, and use your own
subagents where parallel investigation or implementation helps. Commit as
you go.
"""

MINI_TICKET_TASK = """\
## Your mini-ticket
{title}

{description}

The ticket above is context; this mini-ticket is YOUR task and other
mini-tickets are handled separately, so stay inside its scope. Commit when
it is complete.
"""


def build_agent_prompt(
    *,
    branch_name: str,
    ticket_title: str,
    ticket_description: str | None,
    processing_instructions: str | None,
    acceptance_criteria: str | None = None,
    subtask_title: str | None = None,
    subtask_description: str | None = None,
) -> str:
    """Compose the dispatch prompt: fixed policy preamble + ticket fields +
    the user's instructions + either the lead-agent task or one mini-ticket."""
    parts: list[str] = [POLICY_PREAMBLE.format(branch_name=branch_name), ""]
    parts.append(f"# Ticket\n{ticket_title}")
    if ticket_description:
        parts.append(f"\n## Description\n{ticket_description}")
    if acceptance_criteria:
        parts.append(f"\n## Acceptance criteria\n{acceptance_criteria}")
    if processing_instructions:
        parts.append(f"\n## Martin's instructions\n{processing_instructions}")
    if subtask_title:
        parts.append(
            "\n"
            + MINI_TICKET_TASK.format(
                title=subtask_title, description=subtask_description or ""
            )
        )
    else:
        parts.append("\n" + LEAD_TASK)
    parts.append("\n" + CONVERSATION_PROTOCOL)
    return "\n".join(parts)
