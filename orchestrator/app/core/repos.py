"""Registered repos — shared across islands.

A `repos` row maps a Jira project key to a local git checkout / remote. Tickets
link to it (dispatch, branch, worktree); the reviewer uses its `local_path`.
Kept in core because more than one island reads it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import asyncpg
from pydantic import BaseModel


class RepoRow(BaseModel):
    id: UUID
    name: str
    jira_project_key: str
    git_remote_url: str
    docker_compose_path: str | None = None
    local_path: str | None = None
    default_branch: str = "main"
    created_at: datetime


async def get_repo(conn: asyncpg.Connection, repo_id: UUID) -> RepoRow | None:
    row = await conn.fetchrow("select * from repos where id = $1", repo_id)
    return RepoRow(**dict(row)) if row else None


async def get_repo_by_project_key(
    conn: asyncpg.Connection, project_key: str
) -> RepoRow | None:
    row = await conn.fetchrow(
        "select * from repos where jira_project_key = $1", project_key
    )
    return RepoRow(**dict(row)) if row else None


async def repo_id_by_project(conn: asyncpg.Connection) -> dict[str, UUID]:
    """Map every registered project key -> repo id, for bulk ticket linking."""
    rows = await conn.fetch("select id, jira_project_key from repos")
    return {r["jira_project_key"]: r["id"] for r in rows}


async def list_repos(conn: asyncpg.Connection) -> list[RepoRow]:
    """All registered repos, by name — backs repo pickers (e.g. the reviewer)."""
    rows = await conn.fetch("select * from repos order by name")
    return [RepoRow(**dict(r)) for r in rows]
