"""Pre-PR review island — Pydantic contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewFinding(BaseModel):
    file: str
    line: int | None = None
    severity: str  # high | medium | low
    category: str
    comment: str
    suggestion: str | None = None


class ReviewResult(BaseModel):
    summary: str
    findings: list[ReviewFinding]


class ReviewRequest(BaseModel):
    """POST /reviews — review a repo's branch diff before opening a PR."""

    repo_id: UUID
    base_branch: str | None = Field(
        None, description="Defaults to the repo's default_branch."
    )
    head_branch: str | None = Field(
        None, description="Defaults to the repo checkout's current branch."
    )


class ReviewRow(BaseModel):
    id: UUID
    repo_id: UUID
    base_branch: str
    head_branch: str
    result: ReviewResult
    created_at: datetime
