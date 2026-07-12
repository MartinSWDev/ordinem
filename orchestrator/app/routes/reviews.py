"""Pre-PR review routes. Reviews a repo's local branch diff against the
device-global company semantics — runs entirely on this machine (code only ever
goes to the configured LLM)."""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from .. import repository, schemas
from ..config import Settings
from ..deps import get_config, get_pool
from ..services.git import GitError, branch_diff, current_branch
from ..services.review import load_semantics, run_review

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=schemas.ReviewRow)
async def create_review(
    body: schemas.ReviewRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_config),
) -> schemas.ReviewRow:
    async with pool.acquire() as conn:
        repo = await repository.get_repo(conn, body.repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="repo not found")
    if not repo.local_path:
        raise HTTPException(
            status_code=422,
            detail="repo has no local_path; set it so the reviewer can find the checkout",
        )

    base = body.base_branch or repo.default_branch
    try:
        head = body.head_branch or await current_branch(repo.local_path)
        diff = await branch_diff(repo.local_path, base, head)
    except GitError as exc:
        raise HTTPException(status_code=422, detail=f"git error: {exc}")

    if not diff.strip():
        result = schemas.ReviewResult(
            summary=f"No changes on {head} relative to {base}.", findings=[]
        )
    else:
        try:
            result = await run_review(diff, load_semantics(), settings)
        except Exception as exc:  # noqa: BLE001 - surface a clean 502 to the caller
            raise HTTPException(status_code=502, detail=f"review failed: {exc}")

    async with pool.acquire() as conn:
        return await repository.create_review(
            conn,
            repo_id=repo.id,
            base_branch=base,
            head_branch=head,
            result=result.model_dump(),
        )


@router.get("/{review_id}", response_model=schemas.ReviewRow)
async def get_review(
    review_id: UUID, pool: asyncpg.Pool = Depends(get_pool)
) -> schemas.ReviewRow:
    async with pool.acquire() as conn:
        review = await repository.get_review(conn, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="review not found")
    return review
