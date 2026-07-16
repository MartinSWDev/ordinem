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

    async def fetchrow(self, query, *args):
        # The repo row run_subtask resolves the agent's worktree from.
        return {
            "local_path": "/tmp/repo",
            "docker_compose_path": None,
            "default_branch": "main",
        }


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

    async def fake_run_subtask(pool, settings, subtask_id, backend="claude"):
        ran["subtask_id"] = subtask_id
        ran["backend"] = backend

    monkeypatch.setattr(dispatch_mod.repository, "create_subtask", fake_create_subtask)
    monkeypatch.setattr(dispatch_mod, "run_subtask", fake_run_subtask)

    await dispatch_mod.run_ticket_agent(_FakePool({}), object(), ticket_id, "cursor")

    assert created["ticket_id"] == ticket_id
    assert created["order_index"] == 0
    assert ran["subtask_id"] == lead_id
    assert ran["backend"] == "cursor", "the chosen backend must reach the run"


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
            description=None, processing_instructions=None, repo_id=uuid4(),
        )

    class FailingDispatcher:
        def __init__(self, *a, **k):
            pass

        async def dispatch(self, **kwargs):
            raise RuntimeError("'claude' not installed")

    async def fake_worktree(repo_dir, branch, base_branch):
        return "/tmp/wt"

    async def fake_set_worktree(conn, sid, path):
        return None

    monkeypatch.setattr(dispatch_mod.repository, "set_subtask_status", fake_set_status)
    monkeypatch.setattr(dispatch_mod.repository, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(dispatch_mod.repository, "set_subtask_worktree", fake_set_worktree)
    monkeypatch.setattr(dispatch_mod, "ensure_ticket_worktree", fake_worktree)
    monkeypatch.setattr(dispatch_mod, "AgentDispatcher", FailingDispatcher)

    with pytest.raises(RuntimeError):
        await dispatch_mod.run_subtask(_FakePool({}), object(), subtask_id)

    assert (SubtaskStatus.RUNNING, None) in statuses
    assert any(s == SubtaskStatus.FAILED and "not installed" in (e or "") for s, e in statuses)


# --- worktrees ----------------------------------------------------------------


async def _init_repo(path):
    import asyncio

    async def git(*args):
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(path), *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        assert proc.returncode == 0, out.decode()

    path.mkdir()
    await git("init", "-b", "main")
    await git("config", "user.email", "t@t")
    await git("config", "user.name", "t")
    (path / "f.txt").write_text("hello")
    await git("add", ".")
    await git("commit", "-m", "init")
    return git


async def test_ensure_ticket_worktree_creates_branch_and_dir(tmp_path):
    repo = tmp_path / "repo"
    git = await _init_repo(repo)

    wt = await dispatch_mod.ensure_ticket_worktree(str(repo), "feat/x", "main")

    from pathlib import Path

    assert Path(wt) == tmp_path / "repo-worktrees" / "feat-x"
    assert (Path(wt) / "f.txt").exists(), "worktree carries the repo contents"
    # the branch exists and is checked out there, not in the main checkout
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "git", "-C", wt, "rev-parse", "--abbrev-ref", "HEAD",
        stdout=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    assert out.decode().strip() == "feat/x"


async def test_ensure_ticket_worktree_is_idempotent(tmp_path):
    repo = tmp_path / "repo"
    await _init_repo(repo)
    first = await dispatch_mod.ensure_ticket_worktree(str(repo), "feat/x", "main")
    second = await dispatch_mod.ensure_ticket_worktree(str(repo), "feat/x", "main")
    assert first == second


def test_review_can_go_back_to_in_progress():
    """Re-dispatch from review: approving a fresh plan sends agents back in."""
    from app.islands.tickets.state_machine import TicketStatus, can_transition_ticket

    assert can_transition_ticket(TicketStatus.REVIEW, TicketStatus.IN_PROGRESS)
