"""Registered repos — shared across islands.

A `repos` row maps a Jira project key to a local git checkout. Rows are
auto-created from tickets on sync (one per project); the only field dispatch
needs is `local_path`, which is guessed from `repos_base_dir/<name>` and
otherwise bound by the user via the repo picker. Kept in core because more than
one island reads it.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg
from pydantic import BaseModel


class RepoRow(BaseModel):
    id: UUID
    name: str
    jira_project_key: str
    git_remote_url: str | None = None
    docker_compose_path: str | None = None
    local_path: str | None = None
    default_branch: str = "main"
    created_at: datetime


class RepoCandidate(BaseModel):
    """A git checkout discovered under repos_base_dir — a pick for the repo's
    local_path when the name-based guess doesn't land."""

    name: str
    path: str


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def discover_local_repos(base_dir: str) -> list[RepoCandidate]:
    """Immediate subdirectories of base_dir that are git checkouts."""
    base = Path(os.path.expanduser(base_dir))
    if not base.is_dir():
        return []
    found: list[RepoCandidate] = []
    for child in sorted(base.iterdir()):
        if (child / ".git").exists():
            found.append(RepoCandidate(name=child.name, path=str(child)))
    return found


def guess_local_path(base_dir: str, name: str, project_key: str) -> str | None:
    """Best-effort match of a repo to a checkout under base_dir, by name/key.
    Matches against the actual on-disk directories (case-insensitively, so it
    behaves the same on macOS and Linux) and returns the real path, or None
    (→ the user picks) when nothing matches."""
    wanted = {v.lower() for v in (name, _slug(name), project_key) if v}
    for candidate in discover_local_repos(base_dir):
        if candidate.name.lower() in wanted:
            return candidate.path
    return None


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


async def ensure_repo_for_project(
    conn: asyncpg.Connection,
    *,
    project_key: str,
    name: str | None,
    base_dir: str,
) -> RepoRow:
    """Return the repo for a Jira project, creating it if absent. On create,
    local_path is auto-guessed from base_dir/<name> and left null (→ picker) if
    nothing matches. Existing rows are returned untouched, so a bound
    local_path is never clobbered by a later sync."""
    existing = await get_repo_by_project_key(conn, project_key)
    if existing is not None:
        return existing
    repo_name = name or project_key
    local_path = guess_local_path(base_dir, repo_name, project_key)
    row = await conn.fetchrow(
        """
        insert into repos (name, jira_project_key, local_path)
        values ($1, $2, $3)
        on conflict (jira_project_key) do update set jira_project_key = excluded.jira_project_key
        returning *
        """,
        repo_name,
        project_key,
        local_path,
    )
    return RepoRow(**dict(row))


async def set_repo_local_path(
    conn: asyncpg.Connection, repo_id: UUID, local_path: str | None
) -> RepoRow | None:
    row = await conn.fetchrow(
        "update repos set local_path = $2 where id = $1 returning *",
        repo_id,
        local_path,
    )
    return RepoRow(**dict(row)) if row else None
