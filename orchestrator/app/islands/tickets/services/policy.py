"""The fixed policy preamble prepended to every agent dispatch (section 9)."""

from __future__ import annotations

POLICY_PREAMBLE = """\
You are working inside an isolated git worktree on branch {branch_name}.
Do not run `git push` under any circumstances. You may stage and commit
locally with clear, conventional-commit-style messages. Run the project's
existing test and lint commands before considering a subtask complete, and
report failures rather than working around them. If you are blocked or
uncertain about ticket intent, stop and report rather than guessing.
"""


def build_agent_prompt(
    *,
    branch_name: str,
    ticket_title: str,
    ticket_description: str | None,
    processing_instructions: str | None,
    acceptance_criteria: str | None = None,
) -> str:
    """Compose the initial lead-agent prompt (section 7.3): fixed policy
    preamble + ticket fields + processing instructions."""
    parts: list[str] = [POLICY_PREAMBLE.format(branch_name=branch_name), ""]
    parts.append(f"# Ticket\n{ticket_title}")
    if ticket_description:
        parts.append(f"\n## Description\n{ticket_description}")
    if acceptance_criteria:
        parts.append(f"\n## Acceptance criteria\n{acceptance_criteria}")
    if processing_instructions:
        parts.append(f"\n## Processing instructions\n{processing_instructions}")
    parts.append(
        "\n## Task\n"
        "Break this ticket into independent subtasks and coordinate them via "
        "Agent Teams, each teammate isolated in its own git worktree. Subtasks "
        "that only edit files can run in parallel worktrees; subtasks that need "
        "the live docker-compose stack to verify behavior must run sequentially "
        "against the single active environment."
    )
    return "\n".join(parts)
