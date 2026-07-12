"""Review island data access (the reviews log)."""

from __future__ import annotations

from uuid import UUID

import asyncpg

from app.islands.review import schemas


async def create_review(
    conn: asyncpg.Connection,
    *,
    repo_id: UUID,
    base_branch: str,
    head_branch: str,
    result: dict,
) -> schemas.ReviewRow:
    row = await conn.fetchrow(
        """
        insert into reviews (repo_id, base_branch, head_branch, result)
        values ($1, $2, $3, $4)
        returning *
        """,
        repo_id,
        base_branch,
        head_branch,
        result,
    )
    return schemas.ReviewRow(**dict(row))


async def get_review(conn: asyncpg.Connection, review_id: UUID) -> schemas.ReviewRow | None:
    row = await conn.fetchrow("select * from reviews where id = $1", review_id)
    return schemas.ReviewRow(**dict(row)) if row else None
