"""Ticket routes (section 10)."""

from __future__ import annotations

import asyncio
import logging
from typing import Coroutine
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.core import repos
from app.islands.tickets import repository, schemas
from app.core.config import Settings
from app.core.deps import get_config, get_pool
from app.islands.tickets.dispatch import (
    DispatchError,
    prepare_dispatch,
    resolve_outcome,
    resume_subtask,
    run_ticket_agent,
    run_ticket_plan,
)
from app.islands.tickets.services import planner
from app.islands.tickets.services.backends import (
    BackendInfo,
    BackendUnavailable,
    build_backend,
    list_backends,
)
from app.islands.tickets.services.checks import run_pre_push_checks
from app.islands.tickets.services.jira import JiraClient, JiraError, JiraNotConfigured
from app.islands.tickets.services.pr import build_template_fields
from app.islands.tickets.state_machine import SubtaskStatus, TicketStatus

logger = logging.getLogger("ordinem.orchestrator")

router = APIRouter(prefix="/tickets", tags=["tickets"])

# Hold strong references to detached background agent runs so they aren't
# garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


def _launch(coro: Coroutine, ticket_id: UUID, label: str) -> None:
    """Run an agent workload detached from the request, holding a strong
    reference so it isn't garbage-collected mid-flight."""

    async def _runner() -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001 - detached; failures are recorded on the subtask
            logger.exception("%s failed for ticket %s", label, ticket_id)

    task = asyncio.create_task(_runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _launch_agent(
    pool: asyncpg.Pool, settings: Settings, ticket_id: UUID, backend: str
) -> None:
    _launch(run_ticket_agent(pool, settings, ticket_id, backend), ticket_id, "agent run")


def _require_backend(settings: Settings, name: str) -> None:
    """409 with the backend's own fix-it message if it can't run here."""
    try:
        build_backend(settings, name)
    except BackendUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/backends", response_model=list[BackendInfo])
async def list_agent_backends(
    settings: Settings = Depends(get_config),
) -> list[BackendInfo]:
    """Probe the dispatch backends (Claude Code / Cursor / local proxy) so the
    UI can offer a picker with live availability."""
    return await list_backends(settings)


@router.get("/repos", response_model=list[repos.RepoRow])
async def list_registered_repos(
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[repos.RepoRow]:
    """Registered repos, for the new-ticket repo picker."""
    async with pool.acquire() as conn:
        return await repos.list_repos(conn)


@router.get("/repos/candidates", response_model=list[repos.RepoCandidate])
async def list_repo_candidates(
    settings: Settings = Depends(get_config),
) -> list[repos.RepoCandidate]:
    """Git checkouts found under repos_base_dir — the options for binding a
    repo's local_path when the auto-guess didn't match."""
    return repos.discover_local_repos(settings.repos_base_dir)


@router.patch("/repos/{repo_id}", response_model=repos.RepoRow)
async def set_repo_checkout(
    repo_id: UUID,
    body: schemas.SetRepoCheckoutRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> repos.RepoRow:
    """Bind (or clear) a repo's local checkout — this is what makes its tickets
    actionable, replacing the old manual `insert into repos`."""
    async with pool.acquire() as conn:
        repo = await repos.set_repo_local_path(conn, repo_id, body.local_path)
    if repo is None:
        raise HTTPException(status_code=404, detail="repo not found")
    return repo


@router.post("/local", response_model=schemas.TicketRow, status_code=201)
async def create_local_ticket(
    body: schemas.CreateLocalTicketRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> schemas.TicketRow:
    """Write your own ticket — no Jira. Used for personal work; the ticket then
    flows through the same pipeline (instructions -> plan -> mini-tickets ->
    agents -> review & ship)."""
    async with pool.acquire() as conn:
        repo = await repos.get_repo(conn, body.repo_id)
        if repo is None:
            raise HTTPException(status_code=422, detail="repo not found")
        return await repository.create_local_ticket(
            conn,
            repo_id=repo.id,
            title=body.title,
            description=body.description,
            processing_instructions=body.processing_instructions,
        )


@router.post("", response_model=schemas.TicketRow)
async def ingest_ticket(
    body: schemas.IngestTicketRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.TicketRow:
    """Ingest or refresh a ticket from Jira (section 6)."""
    try:
        client = JiraClient(settings)
    except JiraNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    try:
        issue = await client.fetch_issue(body.jira_key)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    async with pool.acquire() as conn:
        # Auto-create the project's repo (guessing its checkout) and link it —
        # no manual seeding. It's actionable once local_path resolves.
        repo = await repos.ensure_repo_for_project(
            conn,
            project_key=issue["project_key"],
            name=issue.get("project_name"),
            base_dir=settings.repos_base_dir,
        )
        ticket = await repository.upsert_ticket_from_jira(
            conn,
            repo_id=repo.id,
            jira_project_key=issue["project_key"],
            jira_key=issue["jira_key"],
            title=issue["title"],
            description=issue["description"],
            raw_jira=issue["raw_jira"],
            jira=issue["jira"],
            processing_instructions=body.processing_instructions,
        )
    return ticket


@router.post("/sync", response_model=schemas.MyTicketsSyncResult)
async def sync_my_tickets(
    body: schemas.MyTicketsSyncRequest = Body(default=schemas.MyTicketsSyncRequest()),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.MyTicketsSyncResult:
    """Pull ALL my tickets across every project from Jira and upsert them,
    grouped-by-project on the client via each ticket's jira_project_key.

    Default JQL is `assignee = currentUser() AND resolution = Unresolved`. This
    is strictly read-only against Jira. A repo row is auto-created per project
    (its checkout guessed from repos_base_dir); tickets whose repo has no
    resolvable checkout yet are ingested and visible, `actionable=false`, and
    their project keys are returned in `unregistered_projects` (i.e. "need a
    checkout bound").
    """
    try:
        client = JiraClient(settings)
    except JiraNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    jql = body.jql or schemas.DEFAULT_MY_TICKETS_JQL
    try:
        issues = await client.search_issues(jql)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    needs_checkout: set[str] = set()
    async with pool.acquire() as conn:
        async with conn.transaction():
            repo_cache: dict[str, repos.RepoRow] = {}
            for issue in issues:
                project_key = issue["project_key"]
                repo = repo_cache.get(project_key)
                if repo is None:
                    repo = await repos.ensure_repo_for_project(
                        conn,
                        project_key=project_key,
                        name=issue.get("project_name"),
                        base_dir=settings.repos_base_dir,
                    )
                    repo_cache[project_key] = repo
                if not repo.local_path:
                    needs_checkout.add(project_key)
                await repository.upsert_ticket_from_jira(
                    conn,
                    repo_id=repo.id,
                    jira_project_key=project_key,
                    jira_key=issue["jira_key"],
                    title=issue["title"],
                    description=issue["description"],
                    raw_jira=issue["raw_jira"],
                    jira=issue["jira"],
                    processing_instructions=None,
                )
        tickets = await repository.list_tickets(conn)

    return schemas.MyTicketsSyncResult(
        synced=len(issues),
        tickets=tickets,
        unregistered_projects=sorted(needs_checkout),
    )


@router.get("", response_model=list[schemas.TicketRow])
async def list_tickets(
    status: TicketStatus | None = None,
    project: str | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[schemas.TicketRow]:
    """All tickets, newest first, optionally filtered by `?status=` and/or
    `?project=<JIRA_KEY>`. This is what the dashboard island fetches against its
    endpoint_base."""
    async with pool.acquire() as conn:
        return await repository.list_tickets(conn, status, project)


@router.get("/{ticket_id}", response_model=schemas.TicketDetail)
async def get_ticket(
    ticket_id: UUID,
    refresh: bool = True,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.TicketDetail:
    """Ticket + subtasks + status. When `refresh` (default) and Jira is
    configured, re-fetches the issue fresh via fetch_issue (*all fields) so the
    detail carries up-to-date comments/attachments/links, then persists the
    curated `jira` projection. Falls back to the stored copy if Jira is
    unavailable, so the detail always renders."""
    async with pool.acquire() as conn:
        detail = await repository.get_ticket_detail(conn, ticket_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    # Local tickets have no Jira counterpart — never try to refresh them.
    if refresh and settings.jira_configured and detail.ticket.jira_key:
        try:
            issue = await JiraClient(settings).fetch_issue(detail.ticket.jira_key)
            async with pool.acquire() as conn:
                refreshed = await repository.refresh_ticket_jira(
                    conn,
                    ticket_id,
                    title=issue["title"],
                    description=issue["description"],
                    raw_jira=issue["raw_jira"],
                    jira=issue["jira"],
                )
            detail.ticket = refreshed
        except (JiraNotConfigured, JiraError):
            pass  # keep the stored copy; detail still renders

    return detail


@router.get("/{ticket_id}/attachments/{index}")
async def get_attachment(
    ticket_id: UUID,
    index: int,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> Response:
    """Proxy a Jira attachment through the orchestrator (which holds the creds)
    so the webview can display images without exposing the token or hitting
    Jira's auth/CORS directly. Indexes into the ticket's stored
    jira.attachments list."""
    async with pool.acquire() as conn:
        ticket = await repository.get_ticket(conn, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    attachments = (ticket.jira or {}).get("attachments") or []
    if index < 0 or index >= len(attachments):
        raise HTTPException(status_code=404, detail="attachment not found")
    url = attachments[index].get("url")
    if not url:
        raise HTTPException(status_code=404, detail="attachment has no url")

    try:
        data, content_type = await JiraClient(settings).fetch_attachment(url)
    except JiraNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/{ticket_id}/plan", response_model=list[schemas.SubtaskRow])
async def plan_ticket_route(
    ticket_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> list[schemas.SubtaskRow]:
    """Propose mini-tickets for a ticket. Nothing is dispatched: the proposals
    land in `proposed` and wait for /plan/approve. Runs inline (not detached) —
    it's one structured call and the user is watching for the result."""
    async with pool.acquire() as conn:
        ticket = await repository.get_ticket(conn, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")

    try:
        proposals = await planner.plan_ticket(
            title=ticket.title,
            description=ticket.description,
            processing_instructions=ticket.processing_instructions,
            settings=settings,
            jira=ticket.jira.model_dump() if ticket.jira else None,
        )
    except Exception as exc:  # noqa: BLE001 - surface the LLM failure to the user
        logger.exception("planning failed for ticket %s", ticket_id)
        raise HTTPException(status_code=502, detail=f"planner failed: {exc}")

    async with pool.acquire() as conn:
        return await repository.replace_proposed_subtasks(conn, ticket_id, proposals)


@router.post("/{ticket_id}/plan/approve", response_model=list[schemas.SubtaskRow])
async def approve_plan_route(
    ticket_id: UUID,
    body: schemas.ApprovePlanRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[schemas.SubtaskRow]:
    """The human gate. Persists the user's final, possibly-edited list as
    dispatchable work. Approving an empty list rejects the plan."""
    async with pool.acquire() as conn:
        ticket = await repository.get_ticket(conn, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        return await repository.approve_plan(conn, ticket_id, body.mini_tickets)


@router.post("/{ticket_id}/dispatch", response_model=schemas.TicketDetail, status_code=202)
async def dispatch_plan_route(
    ticket_id: UUID,
    body: schemas.DispatchPlanRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.TicketDetail:
    """Set the approved mini-tickets running, each in its own agent session and
    worktree — parallel, except docker ones which serialize. Returns immediately
    with the ticket in_progress; per-subtask progress arrives via agent_events."""
    async with pool.acquire() as conn:
        pending = await repository.get_dispatchable_subtasks(conn, ticket_id)
    if not pending:
        raise HTTPException(
            status_code=409,
            detail="no approved mini-tickets to dispatch; run /plan and approve one first",
        )
    if any(s.needs_docker for s in pending) and not body.confirm_active_docker_project:
        raise HTTPException(
            status_code=409,
            detail="a mini-ticket needs docker; confirm the repo's compose project is the active OrbStack project",
        )
    _require_backend(settings, body.backend)

    try:
        await prepare_dispatch(
            pool,
            ticket_id,
            branch_name=body.branch_name,
            confirm_active_docker_project=body.confirm_active_docker_project,
        )
    except DispatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    _launch(
        run_ticket_plan(pool, settings, ticket_id, body.backend),
        ticket_id,
        "plan dispatch",
    )

    async with pool.acquire() as conn:
        detail = await repository.get_ticket_detail(conn, ticket_id)
    assert detail is not None
    return detail


@router.post("/{ticket_id}/process", response_model=schemas.TicketDetail, status_code=202)
async def process_ticket(
    ticket_id: UUID,
    body: schemas.ProcessTicketRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.TicketDetail:
    """Trigger the dispatch sequence (section 7). Runs the deterministic
    preconditions + transition to in_progress synchronously, then launches the
    agent run in the background (streaming agent_events the live view consumes).
    Returns immediately with the ticket now in_progress."""
    _require_backend(settings, body.backend)
    try:
        await prepare_dispatch(
            pool,
            ticket_id,
            branch_name=body.branch_name,
            confirm_active_docker_project=body.confirm_active_docker_project,
        )
    except DispatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    _launch_agent(pool, settings, ticket_id, body.backend)

    async with pool.acquire() as conn:
        detail = await repository.get_ticket_detail(conn, ticket_id)
    assert detail is not None
    return detail


@router.patch("/{ticket_id}/instructions", response_model=schemas.TicketRow)
async def update_instructions(
    ticket_id: UUID,
    body: schemas.UpdateInstructionsRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> schemas.TicketRow:
    """Save the user's context/instructions for the agent. Editable any time;
    the next launch (not a resume) picks it up."""
    async with pool.acquire() as conn:
        try:
            return await repository.set_ticket_instructions(
                conn, ticket_id, body.processing_instructions
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="ticket not found")


@router.get("/{ticket_id}/conversation", response_model=schemas.ConversationView)
async def get_conversation(
    ticket_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
) -> schemas.ConversationView:
    """The agent <-> user thread for the ticket's live conversation subtask:
    each agent turn's closing report plus the user's replies, in order."""
    async with pool.acquire() as conn:
        subtask = await repository.get_conversation_subtask(conn, ticket_id)
        if subtask is None:
            return schemas.ConversationView()
        events = await repository.get_events_for_subtask(conn, subtask.id)

    messages: list[schemas.ConversationMessage] = []
    for ev in events:
        if ev.event_type == "message" and ev.payload.get("role") == "user":
            messages.append(
                schemas.ConversationMessage(
                    role="user", text=str(ev.payload.get("text", "")), at=ev.created_at
                )
            )
        elif ev.event_type in ("stop", "stop_failure"):
            raw = (ev.payload.get("stream") or {}).get("result")
            if raw:
                _, text = resolve_outcome(str(raw))
                messages.append(
                    schemas.ConversationMessage(
                        role="agent", text=text or "", at=ev.created_at
                    )
                )
    return schemas.ConversationView(subtask=subtask, messages=messages)


@router.post("/{ticket_id}/agent/reply", response_model=schemas.TicketDetail, status_code=202)
async def reply_to_agent(
    ticket_id: UUID,
    body: schemas.AgentReplyRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.TicketDetail:
    """Answer the waiting agent: resumes its CLI session in the same worktree.
    Returns immediately; the turn streams into agent_events and the subtask
    ends done / awaiting_input again via the marker protocol."""
    async with pool.acquire() as conn:
        if body.subtask_id is not None:
            target = await repository.get_subtask(conn, body.subtask_id)
        else:
            target = await repository.get_conversation_subtask(conn, ticket_id)
    if target is None or target.ticket_id != ticket_id:
        raise HTTPException(status_code=404, detail="no conversation for ticket")
    if target.status not in (SubtaskStatus.AWAITING_INPUT, SubtaskStatus.DONE):
        raise HTTPException(
            status_code=409,
            detail=f"conversation is '{target.status}' — reply when it's awaiting_input or done",
        )
    if not target.sdk_session_id:
        raise HTTPException(
            status_code=409,
            detail="conversation has no resumable session (backend may not support resume)",
        )

    _launch(
        resume_subtask(pool, settings, target.id, body.message),
        ticket_id,
        "agent reply",
    )

    async with pool.acquire() as conn:
        detail = await repository.get_ticket_detail(conn, ticket_id)
    assert detail is not None
    return detail


@router.get("/{ticket_id}/events")
async def stream_events(
    ticket_id: UUID,
    request: Request,
    after_id: int = 0,
    pool: asyncpg.Pool = Depends(get_pool),
) -> StreamingResponse:
    """Stream agent_events for a ticket as Server-Sent Events (section 10).
    Polls the append-only log from `after_id` and pushes new rows."""

    async def event_gen():
        last = after_id
        while True:
            if await request.is_disconnected():
                break
            async with pool.acquire() as conn:
                events = await repository.get_events_for_ticket(conn, ticket_id, last)
            for ev in events:
                last = ev.id
                yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {ev.model_dump_json()}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/{ticket_id}/checks", response_model=schemas.CheckRunRow)
async def run_checks(
    ticket_id: UUID, pool: asyncpg.Pool = Depends(get_pool)
) -> schemas.CheckRunRow:
    """Run the repo's existing pre-push checks and record the result. On failure
    the ticket moves review -> checks_failed (manual intervention only)."""
    async with pool.acquire() as conn:
        ticket = await repository.get_ticket(conn, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        repo = await conn.fetchrow("select * from repos where id = $1", ticket.repo_id)
        if repo is None:
            raise HTTPException(status_code=422, detail="ticket has no repo")

    # Derive the working checkout path from the repo compose path's directory,
    # falling back to the git remote's basename is not meaningful locally, so we
    # require a compose path (which points at the repo checkout).
    repo_dir = repo["docker_compose_path"]
    if not repo_dir:
        raise HTTPException(
            status_code=422,
            detail="repo has no docker_compose_path to locate the checkout for checks",
        )
    from pathlib import Path

    result = await run_pre_push_checks(str(Path(repo_dir).parent))

    async with pool.acquire() as conn:
        run = await repository.create_check_run(
            conn,
            ticket_id=ticket_id,
            check_name=result.check_name,
            status=result.status,
            output=result.output,
        )
        if result.status != "pass" and ticket.status == TicketStatus.REVIEW:
            await repository.set_ticket_status(
                conn, ticket_id, TicketStatus.CHECKS_FAILED
            )
    return run


@router.post("/{ticket_id}/commit-plan", response_model=schemas.CommitPlanRow)
async def request_commit_plan(
    ticket_id: UUID,
    body: schemas.CommitPlanRequestBody,
    pool: asyncpg.Pool = Depends(get_pool),
) -> schemas.CommitPlanRow:
    """Request commit-plan drafting (section 8). The agent proposes a message +
    file list; the user approves/edits before anything is staged.

    Producing the proposal is an agent action; this endpoint persists a
    'proposed' commit_plans row that the agent (or a human) fills in. For now it
    creates an empty proposal shell to be populated, keeping committing local
    and human-gated.
    """
    async with pool.acquire() as conn:
        ticket = await repository.get_ticket(conn, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        plan = await repository.create_commit_plan(
            conn,
            ticket_id=ticket_id,
            subtask_id=body.subtask_id,
            proposed_message="",
            files=[],
        )
    return plan


@router.post("/{ticket_id}/pr-draft", response_model=schemas.PrDraftRow)
async def create_pr_draft(
    ticket_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.PrDraftRow:
    """Generate a PR template fill (section 8)."""
    async with pool.acquire() as conn:
        ticket = await repository.get_ticket(conn, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        repo = await conn.fetchrow("select * from repos where id = $1", ticket.repo_id)
        plans = await conn.fetch(
            "select proposed_message from commit_plans where ticket_id = $1 and status in ('approved','edited','committed')",
            ticket_id,
        )

    from pathlib import Path

    repo_dir = (
        str(Path(repo["docker_compose_path"]).parent)
        if repo and repo["docker_compose_path"]
        else "."
    )
    browse_url = ""
    try:
        browse_url = JiraClient(settings).issue_browse_url(ticket.jira_key)
    except JiraNotConfigured:
        browse_url = ticket.jira_key

    fields = build_template_fields(
        repo_path=repo_dir,
        jira_key=ticket.jira_key,
        jira_browse_url=browse_url,
        ticket_title=ticket.title,
        commit_messages=[p["proposed_message"] for p in plans],
    )

    async with pool.acquire() as conn:
        draft = await repository.create_pr_draft(
            conn, ticket_id=ticket_id, template_fields=fields
        )
    return draft


@router.post("/{ticket_id}/pr-draft/opened", response_model=schemas.PrDraftRow)
async def mark_pr_opened(
    ticket_id: UUID,
    body: schemas.PrDraftOpenedRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> schemas.PrDraftRow:
    """Mark the latest PR draft as opened, storing the URL (section 8)."""
    async with pool.acquire() as conn:
        draft = await repository.mark_pr_draft_opened(conn, ticket_id, body.pr_url)
    if draft is None:
        raise HTTPException(status_code=404, detail="no pr draft for ticket")
    return draft
