"""Local (self-authored) tickets — no Jira involved."""

from __future__ import annotations

import datetime
from uuid import uuid4

from app.islands.tickets import repository, schemas


def _row(**over):
    base = dict(
        id=uuid4(), repo_id=uuid4(), jira_project_key=None, jira_key=None,
        source="local", title="Add rate limiting", description="cap at 5rps",
        jira=None, processing_instructions="start with the worker",
        branch_name=None, status="new",
        created_at=datetime.datetime.now(), updated_at=datetime.datetime.now(),
    )
    base.update(over)
    return base


async def test_create_local_ticket_has_no_jira_key(monkeypatch):
    captured = {}

    class FakeConn:
        async def fetchrow(self, q, *args):
            captured.setdefault("sqls", []).append(q)
            # First call is the insert (returning *); create_local_ticket then
            # re-fetches via get_ticket, whose row carries the joined checkout.
            return _row(repo_local_path="/Users/me/Repos/app")

    t = await repository.create_local_ticket(
        FakeConn(), repo_id=uuid4(), title="Add rate limiting",
        description="cap at 5rps", processing_instructions="start with the worker",
    )
    assert t.source == "local"
    assert t.jira_key is None
    assert t.jira is None
    # actionable once the repo has a resolved checkout
    assert t.actionable is True
    assert any("'local'" in sql for sql in captured["sqls"])


def test_ticket_row_allows_missing_jira_key():
    """A local ticket must validate without a jira_key (jira-sourced ones keep theirs)."""
    local = schemas.TicketRow(**_row())
    assert local.jira_key is None and local.source == "local"

    jira = schemas.TicketRow(**_row(source="jira", jira_key="PROJ-1", jira_project_key="PROJ"))
    assert jira.jira_key == "PROJ-1" and jira.source == "jira"
