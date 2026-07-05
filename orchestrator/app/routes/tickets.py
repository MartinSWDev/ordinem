"""Ticket routes (section 10)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import repository, schemas
from ..config import Settings
from ..deps import get_config, get_pool
from ..dispatch import DispatchError, prepare_dispatch
from ..services.checks import run_pre_push_checks
from ..services.jira import JiraClient, JiraError, JiraNotConfigured
from ..services.pr import build_template_fields
from ..state_machine import TicketStatus

router = APIRouter(prefix="/tickets", tags=["tickets"])


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
        # Link to a repo if the project is registered; otherwise ingest anyway
        # (visible but unactionable until a repos row is seeded and re-synced).
        repo = await repository.get_repo_by_project_key(conn, issue["project_key"])
        ticket = await repository.upsert_ticket_from_jira(
            conn,
            repo_id=repo.id if repo else None,
            jira_project_key=issue["project_key"],
            jira_key=issue["jira_key"],
            title=issue["title"],
            description=issue["description"],
            raw_jira=issue["raw_jira"],
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
    is strictly read-only against Jira. Tickets in projects with no registered
    repo are still ingested (visible, `actionable=false`) and their project keys
    are returned in `unregistered_projects`.
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

    unregistered: set[str] = set()
    async with pool.acquire() as conn:
        repo_map = await repository.repo_id_by_project(conn)
        async with conn.transaction():
            for issue in issues:
                project_key = issue["project_key"]
                repo_id = repo_map.get(project_key)
                if repo_id is None:
                    unregistered.add(project_key)
                await repository.upsert_ticket_from_jira(
                    conn,
                    repo_id=repo_id,
                    jira_project_key=project_key,
                    jira_key=issue["jira_key"],
                    title=issue["title"],
                    description=issue["description"],
                    raw_jira=issue["raw_jira"],
                    processing_instructions=None,
                )
        tickets = await repository.list_tickets(conn)

    return schemas.MyTicketsSyncResult(
        synced=len(issues),
        tickets=tickets,
        unregistered_projects=sorted(unregistered),
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
    ticket_id: UUID, pool: asyncpg.Pool = Depends(get_pool)
) -> schemas.TicketDetail:
    """Ticket + subtasks + status."""
    async with pool.acquire() as conn:
        detail = await repository.get_ticket_detail(conn, ticket_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return detail


@router.post("/{ticket_id}/process", response_model=schemas.TicketDetail, status_code=202)
async def process_ticket(
    ticket_id: UUID,
    body: schemas.ProcessTicketRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> schemas.TicketDetail:
    """Trigger the dispatch sequence (section 7). Runs the deterministic
    preconditions + transition to in_progress synchronously; the agent run
    itself proceeds against the SDK/worktree environment."""
    try:
        await prepare_dispatch(
            pool,
            ticket_id,
            branch_name=body.branch_name,
            confirm_active_docker_project=body.confirm_active_docker_project,
        )
    except DispatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

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
