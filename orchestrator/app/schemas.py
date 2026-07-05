"""Pydantic models: DB row shapes and API request/response contracts.

The `*Row` models mirror table rows (what the DB layer returns). The request
models are the API's input contracts. Keeping them explicit is the point of
this pass — correct contracts over appearance.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from .state_machine import SubtaskStatus, TicketStatus

# --------------------------------------------------------------------------- #
# Row models
# --------------------------------------------------------------------------- #


class RepoRow(BaseModel):
    id: UUID
    name: str
    jira_project_key: str
    git_remote_url: str
    docker_compose_path: str | None = None
    default_branch: str = "main"
    created_at: datetime


class TicketRow(BaseModel):
    id: UUID
    repo_id: UUID | None = None
    jira_project_key: str | None = None
    jira_key: str
    title: str
    description: str | None = None
    # Curated, LLM-useful projection of the Jira issue (comments, acceptance
    # criteria, labels, links, attachments, …). raw_jira stays in the DB for
    # debugging but is deliberately not returned here.
    jira: dict | None = None
    processing_instructions: str | None = None
    branch_name: str | None = None
    status: TicketStatus
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def actionable(self) -> bool:
        """A ticket can be dispatched to an agent only once its project has a
        registered repo (branch/worktree/docker all hang off the repo)."""
        return self.repo_id is not None


class SubtaskRow(BaseModel):
    id: UUID
    ticket_id: UUID
    title: str
    description: str | None = None
    order_index: int = 0
    status: SubtaskStatus
    backend: str | None = None
    worktree_path: str | None = None
    sdk_session_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class AgentEventRow(BaseModel):
    id: int
    subtask_id: UUID
    event_type: str
    payload: dict
    created_at: datetime


class CommitPlanRow(BaseModel):
    id: UUID
    ticket_id: UUID
    subtask_id: UUID | None = None
    proposed_message: str
    files: list | dict
    status: str
    sha: str | None = None
    created_at: datetime


class CheckRunRow(BaseModel):
    id: UUID
    ticket_id: UUID
    check_name: str
    status: str
    output: str | None = None
    run_at: datetime


class PrDraftRow(BaseModel):
    id: UUID
    ticket_id: UUID
    template_fields: dict
    status: str
    pr_url: str | None = None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #


class IngestTicketRequest(BaseModel):
    """POST /tickets — ingest or refresh a ticket from Jira."""

    jira_key: str = Field(..., description="e.g. PROJ-2481")
    processing_instructions: str | None = None


class ProcessTicketRequest(BaseModel):
    """POST /tickets/:id/process — trigger the dispatch sequence (section 7)."""

    branch_name: str = Field(..., description="Confirmed/created manually per section 7.1")
    confirm_active_docker_project: bool = Field(
        False,
        description="Set true to acknowledge the repo's compose project is the active OrbStack project (section 7.2).",
    )


class CommitPlanRequestBody(BaseModel):
    """POST /tickets/:id/commit-plan — request commit plan drafting."""

    subtask_id: UUID | None = None


class ApproveCommitPlanRequest(BaseModel):
    """POST /commit-plans/:id/approve — approve/edit then commit locally."""

    edited_message: str | None = Field(
        None, description="If set, overrides proposed_message (status becomes 'edited')."
    )


class PrDraftOpenedRequest(BaseModel):
    """POST /tickets/:id/pr-draft/opened — mark a PR draft as opened."""

    pr_url: str


# --------------------------------------------------------------------------- #
# Composite responses
# --------------------------------------------------------------------------- #


class TicketDetail(BaseModel):
    """GET /tickets/:id — ticket plus its subtasks and status."""

    ticket: TicketRow
    subtasks: list[SubtaskRow]


class ProjectSyncRequest(BaseModel):
    """POST /projects/:key/sync — bulk-pull one project's issues from Jira."""

    jql: str | None = Field(
        None,
        description=(
            "Override the default JQL. Default: 'project = <KEY> ORDER BY "
            "updated DESC'. Read-only — this only ever GETs from Jira."
        ),
    )


class ProjectSyncResult(BaseModel):
    project_key: str
    synced: int
    tickets: list[TicketRow]


DEFAULT_MY_TICKETS_JQL = (
    "assignee = currentUser() AND resolution = Unresolved ORDER BY priority ASC"
)


class MyTicketsSyncRequest(BaseModel):
    """POST /tickets/sync — pull all my tickets across every project."""

    jql: str | None = Field(
        None,
        description=(
            f"Override the default JQL. Default: '{DEFAULT_MY_TICKETS_JQL}'. "
            "Read-only — this only ever GETs from Jira."
        ),
    )


class MyTicketsSyncResult(BaseModel):
    synced: int
    tickets: list[TicketRow]
    unregistered_projects: list[str] = Field(
        default_factory=list,
        description=(
            "Project keys that had matching tickets but no registered repo. "
            "Those tickets are ingested and visible, but not actionable until "
            "you seed a repos row for them."
        ),
    )
