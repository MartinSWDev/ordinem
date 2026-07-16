"""Ticket dispatch orchestration (section 7). Ties together the state machine,
repository, and the AgentDispatcher.

The deterministic parts (repo lookup, docker-project gate, branch confirmation,
status transitions, review roll-up, local-fallback bookkeeping) run here and
now. The agent itself is a backend CLI (Claude Code / Cursor / local proxy —
see services/backends.py) spawned in the repo's checkout.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import asyncpg

from app.islands.tickets import repository
from app.core.config import Settings
from app.islands.tickets.services.agent import AgentDispatcher
from app.islands.tickets.state_machine import SubtaskStatus, TicketStatus


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

            # A ticket from an unregistered project (repo_id null) is visible but
            # not actionable — there's no repo/branch/worktree to dispatch into.
            if ticket.repo_id is None:
                raise DispatchError(
                    f"ticket's project '{ticket.jira_project_key}' has no "
                    "registered repo; seed a repos row for it and re-sync before "
                    "dispatching an agent"
                )

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
            elif ticket.status in (TicketStatus.CHECKS_FAILED, TicketStatus.REVIEW):
                # re-dispatch: after a failed check, or with a newly approved
                # plan from review (both manual intervention paths)
                await repository.set_ticket_status(
                    conn, ticket_id, TicketStatus.IN_PROGRESS
                )
            elif ticket.status != TicketStatus.IN_PROGRESS:
                raise DispatchError(
                    f"ticket in status '{ticket.status}' cannot be dispatched"
                )


def _repo_checkout_dir(repo_row) -> str:
    """The repo's registered checkout, falling back to the compose file's
    directory."""
    if repo_row["local_path"]:
        return repo_row["local_path"]
    if repo_row["docker_compose_path"]:
        return str(Path(repo_row["docker_compose_path"]).parent)
    raise DispatchError(
        "repo has no local_path (or docker_compose_path) to run the agent in; "
        "set repos.local_path to the checkout"
    )


async def _git(repo_dir: str, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo_dir,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", errors="replace")


async def ensure_ticket_worktree(repo_dir: str, branch: str, base_branch: str) -> str:
    """Create (or reuse) the ticket's git worktree on its branch, next to the
    checkout: <repo>-worktrees/<branch>. Every agent for the ticket runs in
    this directory, so the branch in the prompt is the branch under its feet
    and the user's own checkout is never touched."""
    repo = Path(repo_dir)
    wt_path = repo.parent / f"{repo.name}-worktrees" / branch.replace("/", "-")
    if (wt_path / ".git").exists():
        return str(wt_path)
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    code, _ = await _git(repo_dir, "rev-parse", "--verify", "--quiet", branch)
    if code == 0:
        code, out = await _git(repo_dir, "worktree", "add", str(wt_path), branch)
    else:
        code, out = await _git(
            repo_dir, "worktree", "add", "-b", branch, str(wt_path), base_branch
        )
    if code != 0:
        raise DispatchError(
            f"could not create worktree for branch '{branch}': {out.strip()[-500:]}"
        )
    return str(wt_path)


async def run_subtask(
    pool: asyncpg.Pool,
    settings: Settings,
    subtask_id: UUID,
    backend: str = "claude",
) -> None:
    """Run a single already-created subtask through the chosen backend inside
    the ticket's worktree, streaming events to the DB and recording the
    completing backend and its final report. Handles the local-proxy fallback
    via AgentDispatcher. Marks the subtask done/failed and advances the ticket
    to review when appropriate."""
    sink = DbEventSink(pool)
    dispatcher = AgentDispatcher(settings, sink)

    async with pool.acquire() as conn:
        subtask = await repository.set_subtask_status(
            conn, subtask_id, SubtaskStatus.RUNNING
        )
        ticket = await repository.get_ticket(conn, subtask.ticket_id)
        if ticket is None:
            raise DispatchError("subtask has no ticket")
        repo_row = await conn.fetchrow(
            "select * from repos where id = $1", ticket.repo_id
        )
        if repo_row is None:
            raise DispatchError("subtask's ticket has no repo")

    branch = ticket.branch_name or ticket.jira_key
    try:
        cwd = await ensure_ticket_worktree(
            _repo_checkout_dir(repo_row), branch, repo_row["default_branch"]
        )
        async with pool.acquire() as conn:
            await repository.set_subtask_worktree(conn, subtask_id, cwd)
        completed_backend, result = await dispatcher.dispatch(
            subtask_id=subtask_id,
            branch_name=branch,
            ticket_title=ticket.title,
            ticket_description=ticket.description,
            processing_instructions=ticket.processing_instructions,
            backend=backend,
            cwd=cwd,
        )
    except Exception as exc:  # noqa: BLE001 - persist the failure, don't crash the worker
        async with pool.acquire() as conn:
            await repository.set_subtask_status(
                conn, subtask_id, SubtaskStatus.FAILED, error=str(exc)
            )
        raise

    async with pool.acquire() as conn:
        await repository.set_subtask_status(
            conn,
            subtask_id,
            SubtaskStatus.DONE,
            backend=completed_backend,
            result=result,
        )
        await repository.maybe_advance_ticket_to_review(conn, subtask.ticket_id)


async def run_ticket_plan(
    pool: asyncpg.Pool,
    settings: Settings,
    ticket_id: UUID,
    backend: str = "claude",
) -> None:
    """Run every approved mini-ticket for a ticket (called detached by /dispatch).

    All mini-tickets share the ticket's single worktree and branch, so they run
    strictly in sequence, in plan order — two agents editing and committing in
    the same working tree would trip over each other's files and git index.
    (Per-subtask worktrees + a merge step would restore parallelism; that's a
    deliberate later step.) Sequencing also satisfies the docker constraint:
    only one agent ever faces the single active OrbStack project.

    A failing mini-ticket must not take its siblings down: run_subtask already
    records the failure on its own row, so failures are swallowed here. The
    ticket advances to review only once every subtask is done or skipped, which
    a failure prevents by design — the user requeues it.
    """
    async with pool.acquire() as conn:
        subtasks = await repository.get_dispatchable_subtasks(conn, ticket_id)

    for s in subtasks:
        try:
            await run_subtask(pool, settings, s.id, backend)
        except Exception:  # noqa: BLE001 - already recorded on the subtask row
            pass

    async with pool.acquire() as conn:
        await repository.maybe_advance_ticket_to_review(conn, ticket_id)


async def run_ticket_agent(
    pool: asyncpg.Pool,
    settings: Settings,
    ticket_id: UUID,
    backend: str = "claude",
) -> None:
    """Kick off the agent for a ticket (called in the background by /process).

    Creates the lead coordination subtask and runs it on the chosen backend.
    The lead run is a single coordination subtask, and its agent_events feed
    the live progress view. Failures (e.g. the backend CLI missing) are
    recorded on the subtask, not raised to the caller — this runs detached
    from the request."""
    async with pool.acquire() as conn:
        lead = await repository.create_subtask(
            conn,
            ticket_id=ticket_id,
            title="Agent run",
            description="Lead agent: plan and coordinate subtasks.",
            order_index=0,
        )
    await run_subtask(pool, settings, lead.id, backend)
