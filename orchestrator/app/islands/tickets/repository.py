"""Tickets island data access. Thin async functions over asyncpg returning
Pydantic row models. Status changes go through the state machine so no illegal
transition can be persisted.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.islands.tickets import schemas
from app.islands.tickets.state_machine import (
    SubtaskStatus,
    TicketStatus,
    assert_subtask_transition,
    assert_ticket_transition,
    ticket_review_ready,
)

# --------------------------------------------------------------------------- #
# Tickets
# --------------------------------------------------------------------------- #


async def upsert_ticket_from_jira(
    conn: asyncpg.Connection,
    *,
    repo_id: UUID | None,
    jira_project_key: str,
    jira_key: str,
    title: str,
    description: str | None,
    raw_jira: dict,
    jira: dict,
    processing_instructions: str | None,
) -> schemas.TicketRow:
    """Insert a new ticket or refresh an existing one by jira_key. A refresh
    updates the Jira-sourced fields (including repo_id — so a ticket becomes
    actionable once its project's repo is registered and re-synced) and touches
    updated_at, but never rewinds status (an in-flight ticket stays in-flight)."""
    row = await conn.fetchrow(
        """
        insert into tickets (repo_id, jira_project_key, jira_key, title, description, raw_jira, jira, processing_instructions)
        values ($1, $2, $3, $4, $5, $6, $7, $8)
        on conflict (jira_key) do update set
          repo_id = excluded.repo_id,
          jira_project_key = excluded.jira_project_key,
          title = excluded.title,
          description = excluded.description,
          raw_jira = excluded.raw_jira,
          jira = excluded.jira,
          processing_instructions =
            coalesce(excluded.processing_instructions, tickets.processing_instructions),
          updated_at = now()
        returning *
        """,
        repo_id,
        jira_project_key,
        jira_key,
        title,
        description,
        raw_jira,
        jira,
        processing_instructions,
    )
    return schemas.TicketRow(**dict(row))


async def create_local_ticket(
    conn: asyncpg.Connection,
    *,
    repo_id: UUID,
    title: str,
    description: str | None,
    processing_instructions: str | None,
) -> schemas.TicketRow:
    """Create a self-authored ticket (source='local'). No Jira key, no curated
    jira view — the rest of the pipeline treats it identically."""
    row = await conn.fetchrow(
        """
        insert into tickets (repo_id, source, title, description, processing_instructions)
        values ($1, 'local', $2, $3, $4)
        returning *
        """,
        repo_id,
        title,
        description,
        processing_instructions,
    )
    return schemas.TicketRow(**dict(row))


async def refresh_ticket_jira(
    conn: asyncpg.Connection,
    ticket_id: UUID,
    *,
    title: str,
    description: str | None,
    raw_jira: dict,
    jira: dict,
) -> schemas.TicketRow:
    """Update just the Jira-sourced content of an existing ticket (used when the
    detail view re-fetches fresh from Jira). Never touches status/repo/branch."""
    row = await conn.fetchrow(
        """
        update tickets set
          title = $2, description = $3, raw_jira = $4, jira = $5, updated_at = now()
        where id = $1
        returning *
        """,
        ticket_id,
        title,
        description,
        raw_jira,
        jira,
    )
    return schemas.TicketRow(**dict(row))


async def list_tickets(
    conn: asyncpg.Connection,
    status: TicketStatus | None = None,
    project_key: str | None = None,
) -> list[schemas.TicketRow]:
    """Tickets, newest first, optionally filtered by status and/or Jira project.
    Backs the dashboard island's list view (GET /tickets)."""
    clauses: list[str] = []
    args: list[Any] = []
    if status is not None:
        args.append(str(status))
        clauses.append(f"status = ${len(args)}")
    if project_key is not None:
        args.append(project_key)
        clauses.append(f"jira_project_key = ${len(args)}")
    where = f"where {' and '.join(clauses)}" if clauses else ""
    # No join on repos: tickets in unregistered projects (repo_id null) must
    # still appear — they're visible-but-unactionable. awaiting_input bubbles
    # up so the list can flash tickets whose agent is waiting on the user.
    rows = await conn.fetch(
        f"""
        select t.*, exists(
          select 1 from subtasks s
          where s.ticket_id = t.id and s.status = 'awaiting_input'
        ) as awaiting_input
        from tickets t {where} order by updated_at desc
        """,
        *args,
    )
    return [schemas.TicketRow(**dict(r)) for r in rows]


async def get_ticket(conn: asyncpg.Connection, ticket_id: UUID) -> schemas.TicketRow | None:
    row = await conn.fetchrow(
        """
        select t.*, exists(
          select 1 from subtasks s
          where s.ticket_id = t.id and s.status = 'awaiting_input'
        ) as awaiting_input
        from tickets t where t.id = $1
        """,
        ticket_id,
    )
    return schemas.TicketRow(**dict(row)) if row else None


async def get_ticket_detail(
    conn: asyncpg.Connection, ticket_id: UUID
) -> schemas.TicketDetail | None:
    ticket = await get_ticket(conn, ticket_id)
    if ticket is None:
        return None
    subtasks = await get_subtasks(conn, ticket_id)
    return schemas.TicketDetail(ticket=ticket, subtasks=subtasks)


async def set_ticket_status(
    conn: asyncpg.Connection, ticket_id: UUID, target: TicketStatus
) -> schemas.TicketRow:
    ticket = await get_ticket(conn, ticket_id)
    if ticket is None:
        raise LookupError("ticket not found")
    assert_ticket_transition(ticket.status, target)
    row = await conn.fetchrow(
        "update tickets set status = $2, updated_at = now() where id = $1 returning *",
        ticket_id,
        str(target),
    )
    return schemas.TicketRow(**dict(row))


async def set_ticket_instructions(
    conn: asyncpg.Connection, ticket_id: UUID, processing_instructions: str | None
) -> schemas.TicketRow:
    """The user's context/instructions for the agent — editable any time; the
    next launch picks it up."""
    row = await conn.fetchrow(
        "update tickets set processing_instructions = $2, updated_at = now() "
        "where id = $1 returning *",
        ticket_id,
        processing_instructions,
    )
    if row is None:
        raise LookupError("ticket not found")
    return schemas.TicketRow(**dict(row))


async def set_ticket_branch(
    conn: asyncpg.Connection, ticket_id: UUID, branch_name: str
) -> None:
    await conn.execute(
        "update tickets set branch_name = $2, updated_at = now() where id = $1",
        ticket_id,
        branch_name,
    )


# --------------------------------------------------------------------------- #
# Subtasks
# --------------------------------------------------------------------------- #


async def get_subtasks(
    conn: asyncpg.Connection, ticket_id: UUID
) -> list[schemas.SubtaskRow]:
    rows = await conn.fetch(
        "select * from subtasks where ticket_id = $1 order by order_index, id",
        ticket_id,
    )
    return [schemas.SubtaskRow(**dict(r)) for r in rows]


async def create_subtask(
    conn: asyncpg.Connection,
    *,
    ticket_id: UUID,
    title: str,
    description: str | None,
    order_index: int,
    backend: str | None = None,
    status: SubtaskStatus = SubtaskStatus.PENDING,
    needs_docker: bool = False,
) -> schemas.SubtaskRow:
    row = await conn.fetchrow(
        """
        insert into subtasks
          (ticket_id, title, description, order_index, backend, status, needs_docker)
        values ($1, $2, $3, $4, $5, $6, $7)
        returning *
        """,
        ticket_id,
        title,
        description,
        order_index,
        backend,
        str(status),
        needs_docker,
    )
    return schemas.SubtaskRow(**dict(row))


async def replace_proposed_subtasks(
    conn: asyncpg.Connection,
    ticket_id: UUID,
    proposals: list[schemas.ProposedSubtask],
) -> list[schemas.SubtaskRow]:
    """Store a fresh plan, discarding any previous un-approved one.

    Only `proposed` rows are deleted — re-planning a ticket must never destroy
    subtasks that already ran or are running.
    """
    async with conn.transaction():
        await conn.execute(
            "delete from subtasks where ticket_id = $1 and status = 'proposed'",
            ticket_id,
        )
        return [
            await create_subtask(
                conn,
                ticket_id=ticket_id,
                title=p.title,
                description=p.description,
                order_index=i,
                status=SubtaskStatus.PROPOSED,
                needs_docker=p.needs_docker,
            )
            for i, p in enumerate(proposals)
        ]


async def approve_plan(
    conn: asyncpg.Connection,
    ticket_id: UUID,
    mini_tickets: list[schemas.ProposedSubtask],
) -> list[schemas.SubtaskRow]:
    """The human gate: persist the user's final list as `pending` work.

    The user may have edited, reordered, dropped or added mini-tickets, so
    rather than diffing against the proposal we drop the proposed rows and
    insert what they approved. Returns the dispatchable subtasks.
    """
    async with conn.transaction():
        await conn.execute(
            "delete from subtasks where ticket_id = $1 and status = 'proposed'",
            ticket_id,
        )
        approved = [
            await create_subtask(
                conn,
                ticket_id=ticket_id,
                title=m.title,
                description=m.description,
                order_index=i,
                status=SubtaskStatus.PENDING,
                needs_docker=m.needs_docker,
            )
            for i, m in enumerate(mini_tickets)
        ]
        ticket = await get_ticket(conn, ticket_id)
        if ticket is not None and ticket.status == TicketStatus.NEW and approved:
            await set_ticket_status(conn, ticket_id, TicketStatus.PLANNED)
    return approved


async def get_dispatchable_subtasks(
    conn: asyncpg.Connection, ticket_id: UUID
) -> list[schemas.SubtaskRow]:
    """Approved-but-not-yet-run work, in plan order."""
    rows = await conn.fetch(
        "select * from subtasks where ticket_id = $1 and status = 'pending' "
        "order by order_index, id",
        ticket_id,
    )
    return [schemas.SubtaskRow(**dict(r)) for r in rows]


async def set_subtask_status(
    conn: asyncpg.Connection,
    subtask_id: UUID,
    target: SubtaskStatus,
    *,
    backend: str | None = None,
    error: str | None = None,
    result: str | None = None,
) -> schemas.SubtaskRow:
    row = await conn.fetchrow("select * from subtasks where id = $1", subtask_id)
    if row is None:
        raise LookupError("subtask not found")
    current = SubtaskStatus(row["status"])
    assert_subtask_transition(current, target)

    sets = ["status = $2"]
    args: list[Any] = [subtask_id, str(target)]
    if backend is not None:
        args.append(backend)
        sets.append(f"backend = ${len(args)}")
    if error is not None:
        args.append(error)
        sets.append(f"error = ${len(args)}")
    if result is not None:
        args.append(result)
        sets.append(f"result = ${len(args)}")
    if target == SubtaskStatus.RUNNING:
        sets.append("started_at = now()")
    if target in (SubtaskStatus.DONE, SubtaskStatus.FAILED, SubtaskStatus.SKIPPED):
        sets.append("finished_at = now()")

    updated = await conn.fetchrow(
        f"update subtasks set {', '.join(sets)} where id = $1 returning *", *args
    )
    return schemas.SubtaskRow(**dict(updated))


async def set_subtask_worktree(
    conn: asyncpg.Connection, subtask_id: UUID, worktree_path: str
) -> None:
    await conn.execute(
        "update subtasks set worktree_path = $2 where id = $1",
        subtask_id,
        worktree_path,
    )


async def get_subtask(
    conn: asyncpg.Connection, subtask_id: UUID
) -> schemas.SubtaskRow | None:
    row = await conn.fetchrow("select * from subtasks where id = $1", subtask_id)
    return schemas.SubtaskRow(**dict(row)) if row else None


async def set_subtask_session(
    conn: asyncpg.Connection, subtask_id: UUID, session_id: str
) -> None:
    await conn.execute(
        "update subtasks set sdk_session_id = $2 where id = $1",
        subtask_id,
        session_id,
    )


async def get_conversation_subtask(
    conn: asyncpg.Connection, ticket_id: UUID
) -> schemas.SubtaskRow | None:
    """The ticket's live conversation: the most recent subtask that has (or is
    getting) a CLI session — each launch starts a new one."""
    row = await conn.fetchrow(
        """
        select * from subtasks
        where ticket_id = $1 and (sdk_session_id is not null or status = 'running')
        order by started_at desc nulls last, id desc limit 1
        """,
        ticket_id,
    )
    return schemas.SubtaskRow(**dict(row)) if row else None


async def get_events_for_subtask(
    conn: asyncpg.Connection, subtask_id: UUID
) -> list[schemas.AgentEventRow]:
    rows = await conn.fetch(
        "select * from agent_events where subtask_id = $1 order by id",
        subtask_id,
    )
    return [schemas.AgentEventRow(**dict(r)) for r in rows]


async def maybe_advance_ticket_to_review(
    conn: asyncpg.Connection, ticket_id: UUID
) -> schemas.TicketRow | None:
    """If every subtask is done/skipped and the ticket is in_progress, move it
    to review (section 7.7)."""
    ticket = await get_ticket(conn, ticket_id)
    if ticket is None or ticket.status != TicketStatus.IN_PROGRESS:
        return None
    subtasks = await get_subtasks(conn, ticket_id)
    statuses = [s.status for s in subtasks]
    if ticket_review_ready(statuses):
        return await set_ticket_status(conn, ticket_id, TicketStatus.REVIEW)
    return None


# --------------------------------------------------------------------------- #
# Agent events (append-only)
# --------------------------------------------------------------------------- #


async def record_event(
    conn: asyncpg.Connection, subtask_id: UUID, event_type: str, payload: dict
) -> schemas.AgentEventRow:
    row = await conn.fetchrow(
        """
        insert into agent_events (subtask_id, event_type, payload)
        values ($1, $2, $3)
        returning *
        """,
        subtask_id,
        event_type,
        payload,
    )
    return schemas.AgentEventRow(**dict(row))


async def get_events_for_ticket(
    conn: asyncpg.Connection, ticket_id: UUID, after_id: int = 0
) -> list[schemas.AgentEventRow]:
    rows = await conn.fetch(
        """
        select e.* from agent_events e
        join subtasks s on s.id = e.subtask_id
        where s.ticket_id = $1 and e.id > $2
        order by e.id
        """,
        ticket_id,
        after_id,
    )
    return [schemas.AgentEventRow(**dict(r)) for r in rows]


# --------------------------------------------------------------------------- #
# Commit plans
# --------------------------------------------------------------------------- #


async def create_commit_plan(
    conn: asyncpg.Connection,
    *,
    ticket_id: UUID,
    subtask_id: UUID | None,
    proposed_message: str,
    files: list | dict,
) -> schemas.CommitPlanRow:
    row = await conn.fetchrow(
        """
        insert into commit_plans (ticket_id, subtask_id, proposed_message, files)
        values ($1, $2, $3, $4)
        returning *
        """,
        ticket_id,
        subtask_id,
        proposed_message,
        files,
    )
    return schemas.CommitPlanRow(**dict(row))


async def get_commit_plan(
    conn: asyncpg.Connection, plan_id: UUID
) -> schemas.CommitPlanRow | None:
    row = await conn.fetchrow("select * from commit_plans where id = $1", plan_id)
    return schemas.CommitPlanRow(**dict(row)) if row else None


async def update_commit_plan(
    conn: asyncpg.Connection,
    plan_id: UUID,
    *,
    status: str,
    proposed_message: str | None = None,
    sha: str | None = None,
) -> schemas.CommitPlanRow:
    sets = ["status = $2"]
    args: list[Any] = [plan_id, status]
    if proposed_message is not None:
        args.append(proposed_message)
        sets.append(f"proposed_message = ${len(args)}")
    if sha is not None:
        args.append(sha)
        sets.append(f"sha = ${len(args)}")
    row = await conn.fetchrow(
        f"update commit_plans set {', '.join(sets)} where id = $1 returning *", *args
    )
    return schemas.CommitPlanRow(**dict(row))


# --------------------------------------------------------------------------- #
# Check runs
# --------------------------------------------------------------------------- #


async def create_check_run(
    conn: asyncpg.Connection,
    *,
    ticket_id: UUID,
    check_name: str,
    status: str,
    output: str | None,
) -> schemas.CheckRunRow:
    row = await conn.fetchrow(
        """
        insert into check_runs (ticket_id, check_name, status, output)
        values ($1, $2, $3, $4)
        returning *
        """,
        ticket_id,
        check_name,
        status,
        output,
    )
    return schemas.CheckRunRow(**dict(row))


# --------------------------------------------------------------------------- #
# PR drafts
# --------------------------------------------------------------------------- #


async def create_pr_draft(
    conn: asyncpg.Connection, *, ticket_id: UUID, template_fields: dict
) -> schemas.PrDraftRow:
    row = await conn.fetchrow(
        """
        insert into pr_drafts (ticket_id, template_fields)
        values ($1, $2)
        returning *
        """,
        ticket_id,
        template_fields,
    )
    return schemas.PrDraftRow(**dict(row))


async def mark_pr_draft_opened(
    conn: asyncpg.Connection, ticket_id: UUID, pr_url: str
) -> schemas.PrDraftRow | None:
    row = await conn.fetchrow(
        """
        update pr_drafts set status = 'opened', pr_url = $2
        where id = (
          select id from pr_drafts where ticket_id = $1 order by created_at desc limit 1
        )
        returning *
        """,
        ticket_id,
        pr_url,
    )
    return schemas.PrDraftRow(**dict(row)) if row else None
