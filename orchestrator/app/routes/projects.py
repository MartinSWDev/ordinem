"""Project routes: bulk-sync a Jira project's issues into the local mirror.

This is strictly READ-ONLY against Jira — it runs a JQL search (GET of data via
POST body) and writes only to our Postgres. It never modifies Jira.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException

from .. import repository, schemas
from ..config import Settings
from ..deps import get_config, get_pool
from ..services.jira import JiraClient, JiraError, JiraNotConfigured

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/{project_key}/sync", response_model=schemas.ProjectSyncResult)
async def sync_project(
    project_key: str,
    body: schemas.ProjectSyncRequest = Body(default=schemas.ProjectSyncRequest()),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.ProjectSyncResult:
    """Pull all of a project's issues from Jira and upsert them locally.

    Requires a `repos` row for the project key (section 11) so tickets can be
    linked to a repo. Returns the synced tickets, newest first.
    """
    try:
        client = JiraClient(settings)
    except JiraNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    async with pool.acquire() as conn:
        repo = await repository.get_repo_by_project_key(conn, project_key)
    if repo is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"no repo registered for Jira project '{project_key}'. "
                "Seed the repos table first (section 11)."
            ),
        )

    jql = body.jql or f"project = {project_key} ORDER BY updated DESC"
    try:
        issues = await client.search_issues(jql)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    synced = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for issue in issues:
                # A JQL like "project = X" can only return issues in that
                # project, but guard anyway so a custom jql can't cross repos.
                if issue["project_key"] != project_key:
                    continue
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
                synced += 1
        tickets = await repository.list_tickets(conn, project_key=project_key)

    return schemas.ProjectSyncResult(
        project_key=project_key, synced=synced, tickets=tickets
    )
