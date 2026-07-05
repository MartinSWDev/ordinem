"""Commit-plan routes (section 8 / 10). Committing is LOCAL ONLY and
human-gated: approve/edit here, then it's staged+committed in the worktree.
The agent never pushes.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from .. import repository, schemas
from ..deps import get_pool

router = APIRouter(prefix="/commit-plans", tags=["commit-plans"])


@router.post("/{plan_id}/approve", response_model=schemas.CommitPlanRow)
async def approve_commit_plan(
    plan_id: UUID,
    body: schemas.ApproveCommitPlanRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> schemas.CommitPlanRow:
    """Approve or edit a proposed commit plan. Sets status to 'approved' (or
    'edited' if the message was changed). Actual local commit + sha capture is
    performed by the worktree executor and recorded via a later 'committed'
    update — this endpoint is the human gate before anything is staged."""
    async with pool.acquire() as conn:
        plan = await repository.get_commit_plan(conn, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="commit plan not found")
        if plan.status not in ("proposed", "approved", "edited"):
            raise HTTPException(
                status_code=409,
                detail=f"commit plan in status '{plan.status}' cannot be approved",
            )

        if body.edited_message is not None and body.edited_message != plan.proposed_message:
            updated = await repository.update_commit_plan(
                conn,
                plan_id,
                status="edited",
                proposed_message=body.edited_message,
            )
        else:
            updated = await repository.update_commit_plan(conn, plan_id, status="approved")
    return updated
