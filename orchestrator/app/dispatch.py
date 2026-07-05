"""Ticket dispatch orchestration (section 7). Ties together the state machine,
repository, and the AgentDispatcher.

The deterministic parts (repo lookup, docker-project gate, branch confirmation,
status transitions, review roll-up, Qwen requeue bookkeeping) run here and now.
The one env-dependent seam is parsing teammate subtasks out of the live SDK
stream — that requires the Agent SDK + a real worktree/docker environment and is
marked clearly below.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg

from . import repository
from .config import Settings
from .services.agent import AgentDispatcher
from .state_machine import SubtaskStatus, TicketStatus


class DispatchError(RuntimeError):
    pass


class DbEventSink:
    """EventSink backed by the connection pool. Each event gets its own short
    connection so a long agent run doesn't hold one open."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record_event(self, subtask_id: UUID, event_type: str, payload: dict) -> None:
        async with self._pool.acquire() as conn:
            await repository.record_event(conn, subtask_id, event_type, payload)


async def prepare_dispatch(
    pool: asyncpg.Pool,
    ticket_id: UUID,
    *,
    branch_name: str,
    confirm_active_docker_project: bool,
) -> None:
    """Section 7.1-7.3 + transition to in_progress. Raises DispatchError if a
    precondition fails (unconfirmed docker project, missing repo compose path)."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            ticket = await repository.get_ticket(conn, ticket_id)
            if ticket is None:
                raise DispatchError("ticket not found")

            repo_row = await conn.fetchrow(
                "select * from repos where id = $1", ticket.repo_id
            )
            if repo_row is None:
                raise DispatchError("ticket has no repo")

            # 7.2: don't silently switch OrbStack projects — require explicit
            # acknowledgement that the repo's compose project is the active one.
            if repo_row["docker_compose_path"] and not confirm_active_docker_project:
                raise DispatchError(
                    "active docker project not confirmed; the repo has a "
                    "docker-compose project that must be the active OrbStack "
                    "project before dispatch (set confirm_active_docker_project)"
                )

            # 7.1: branch is confirmed/created manually by the caller.
            await repository.set_ticket_branch(conn, ticket_id, branch_name)

            # Walk new -> planned -> in_progress through legal transitions.
            if ticket.status == TicketStatus.NEW:
                await repository.set_ticket_status(conn, ticket_id, TicketStatus.PLANNED)
                await repository.set_ticket_status(
                    conn, ticket_id, TicketStatus.IN_PROGRESS
                )
            elif ticket.status == TicketStatus.PLANNED:
                await repository.set_ticket_status(
                    conn, ticket_id, TicketStatus.IN_PROGRESS
                )
            elif ticket.status == TicketStatus.CHECKS_FAILED:
                # re-dispatch after a failed check (manual intervention path)
                await repository.set_ticket_status(
                    conn, ticket_id, TicketStatus.IN_PROGRESS
                )
            elif ticket.status != TicketStatus.IN_PROGRESS:
                raise DispatchError(
                    f"ticket in status '{ticket.status}' cannot be dispatched"
                )


async def run_subtask(
    pool: asyncpg.Pool,
    settings: Settings,
    subtask_id: UUID,
) -> None:
    """Run a single already-created subtask through the agent, streaming events
    to the DB and recording the completing backend. Handles the Qwen fallback
    via AgentDispatcher. Marks the subtask done/failed and advances the ticket
    to review when appropriate.

    NOTE: creating subtask rows from the live lead-agent stream (one per
    teammate, section 7.5) is the env-dependent seam — it needs the Agent SDK
    and a real worktree/docker environment. This function runs a subtask once it
    exists; wiring the stream->create_subtask parser happens when the SDK lands.
    """
    sink = DbEventSink(pool)
    dispatcher = AgentDispatcher(settings, sink)

    async with pool.acquire() as conn:
        subtask = await repository.set_subtask_status(
            conn, subtask_id, SubtaskStatus.RUNNING
        )
        ticket = await repository.get_ticket(conn, subtask.ticket_id)
        if ticket is None:
            raise DispatchError("subtask has no ticket")

    try:
        completed_backend = await dispatcher.dispatch(
            subtask_id=subtask_id,
            branch_name=ticket.branch_name or ticket.jira_key,
            ticket_title=ticket.title,
            ticket_description=ticket.description,
            processing_instructions=ticket.processing_instructions,
        )
    except Exception as exc:  # noqa: BLE001 - persist the failure, don't crash the worker
        async with pool.acquire() as conn:
            await repository.set_subtask_status(
                conn, subtask_id, SubtaskStatus.FAILED, error=str(exc)
            )
        raise

    async with pool.acquire() as conn:
        await repository.set_subtask_status(
            conn, subtask_id, SubtaskStatus.DONE, backend=completed_backend
        )
        await repository.maybe_advance_ticket_to_review(conn, subtask.ticket_id)
