"""run_ticket_agent orchestration (agent dispatch itself is mocked)."""

from __future__ import annotations

import types
from uuid import uuid4

import pytest

from app.islands.tickets import dispatch as dispatch_mod
from app.islands.tickets.state_machine import SubtaskStatus


class _FakeConn:
    """Minimal async connection stand-in for the acquire() context."""

    def __init__(self, store):
        self._store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, store):
        self._store = store

    def acquire(self):
        return _FakeConn(self._store)


async def test_run_ticket_agent_creates_lead_subtask_and_runs_it(monkeypatch):
    created: dict = {}
    ran: dict = {}
    ticket_id = uuid4()
    lead_id = uuid4()

    async def fake_create_subtask(conn, *, ticket_id, title, description, order_index, backend=None):
        created.update(ticket_id=ticket_id, title=title, order_index=order_index)
        return types.SimpleNamespace(id=lead_id)

    async def fake_run_subtask(pool, settings, subtask_id):
        ran["subtask_id"] = subtask_id

    monkeypatch.setattr(dispatch_mod.repository, "create_subtask", fake_create_subtask)
    monkeypatch.setattr(dispatch_mod, "run_subtask", fake_run_subtask)

    await dispatch_mod.run_ticket_agent(_FakePool({}), object(), ticket_id)

    assert created["ticket_id"] == ticket_id
    assert created["order_index"] == 0
    assert ran["subtask_id"] == lead_id


async def test_run_subtask_marks_failed_when_dispatch_raises(monkeypatch):
    """When the Agent SDK isn't available, the subtask is marked failed with the
    error rather than crashing the worker."""
    subtask_id = uuid4()
    ticket_id = uuid4()
    statuses: list = []

    async def fake_set_status(conn, sid, status, *, backend=None, error=None):
        statuses.append((status, error))
        return types.SimpleNamespace(id=sid, ticket_id=ticket_id)

    async def fake_get_ticket(conn, tid):
        return types.SimpleNamespace(
            branch_name="feat/x", jira_key="PROJ-1", title="t",
            description=None, processing_instructions=None,
        )

    class FailingDispatcher:
        def __init__(self, *a, **k):
            pass

        async def dispatch(self, **kwargs):
            raise RuntimeError("claude-agent-sdk is not installed")

    monkeypatch.setattr(dispatch_mod.repository, "set_subtask_status", fake_set_status)
    monkeypatch.setattr(dispatch_mod.repository, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(dispatch_mod, "AgentDispatcher", FailingDispatcher)

    with pytest.raises(RuntimeError):
        await dispatch_mod.run_subtask(_FakePool({}), object(), subtask_id)

    assert (SubtaskStatus.RUNNING, None) in statuses
    assert any(s == SubtaskStatus.FAILED and "not installed" in (e or "") for s, e in statuses)
