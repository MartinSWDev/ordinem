"""Plan -> human gate -> dispatch.

The two things worth pinning: a proposed mini-ticket can never reach an agent
without passing the gate, and docker mini-tickets never run concurrently.
"""

from __future__ import annotations

import asyncio
import datetime
from uuid import uuid4

import pytest

from app.islands.tickets import dispatch, schemas
from app.islands.tickets.state_machine import (
    IllegalTransition,
    SubtaskStatus,
    assert_subtask_transition,
    can_transition_subtask,
    ticket_review_ready,
)


def _sub(**over) -> schemas.SubtaskRow:
    base = dict(
        id=uuid4(), ticket_id=uuid4(), title="do a thing", description="...",
        order_index=0, status=SubtaskStatus.PENDING, needs_docker=False,
        backend=None, worktree_path=None, sdk_session_id=None,
        started_at=None, finished_at=None, error=None,
    )
    base.update(over)
    return schemas.SubtaskRow(**base)


# --- the human gate ---------------------------------------------------------


def test_proposed_cannot_go_straight_to_running():
    """The whole point of the gate: an agent never picks up unapproved work."""
    assert not can_transition_subtask(SubtaskStatus.PROPOSED, SubtaskStatus.RUNNING)
    with pytest.raises(IllegalTransition):
        assert_subtask_transition(SubtaskStatus.PROPOSED, SubtaskStatus.RUNNING)


def test_proposed_can_be_approved_or_rejected():
    assert can_transition_subtask(SubtaskStatus.PROPOSED, SubtaskStatus.PENDING)
    assert can_transition_subtask(SubtaskStatus.PROPOSED, SubtaskStatus.SKIPPED)


def test_unapproved_plan_does_not_make_a_ticket_review_ready():
    """A ticket with a dangling proposal isn't finished work."""
    assert not ticket_review_ready([SubtaskStatus.DONE, SubtaskStatus.PROPOSED])
    assert ticket_review_ready([SubtaskStatus.DONE, SubtaskStatus.SKIPPED])


# --- dispatch concurrency ---------------------------------------------------


class _Recorder:
    """Records overlap: how many subtasks were mid-run at the same moment."""

    def __init__(self) -> None:
        self.running: set = set()
        self.max_docker_overlap = 0
        self.max_overlap = 0
        self.ran: list = []

    async def run(self, subtask_id, *, docker: bool) -> None:
        self.running.add(subtask_id)
        self.ran.append(subtask_id)
        self.max_overlap = max(self.max_overlap, len(self.running))
        if docker:
            self.max_docker_overlap = max(
                self.max_docker_overlap, sum(1 for s in self.running if s in self.docker_ids)
            )
        await asyncio.sleep(0.01)  # let siblings interleave
        self.running.discard(subtask_id)


async def _run_plan(monkeypatch, subtasks: list[schemas.SubtaskRow]) -> _Recorder:
    rec = _Recorder()
    rec.docker_ids = {s.id for s in subtasks if s.needs_docker}

    async def fake_get(conn, ticket_id):
        return subtasks

    async def fake_run_subtask(pool, settings, subtask_id):
        await rec.run(subtask_id, docker=subtask_id in rec.docker_ids)

    async def fake_advance(conn, ticket_id):
        return None

    monkeypatch.setattr(dispatch.repository, "get_dispatchable_subtasks", fake_get)
    monkeypatch.setattr(dispatch.repository, "maybe_advance_ticket_to_review", fake_advance)
    monkeypatch.setattr(dispatch, "run_subtask", fake_run_subtask)
    await dispatch.run_ticket_plan(_FakePool(), object(), uuid4())
    return rec


class _FakeConn:
    pass


class _FakePool:
    def acquire(self):
        class _Ctx:
            async def __aenter__(self_):
                return _FakeConn()

            async def __aexit__(self_, *a):
                return False

        return _Ctx()


async def test_non_docker_mini_tickets_run_in_parallel(monkeypatch):
    subs = [_sub(order_index=i) for i in range(3)]
    rec = await _run_plan(monkeypatch, subs)
    assert len(rec.ran) == 3
    assert rec.max_overlap == 3, "independent mini-tickets should not serialize"


async def test_docker_mini_tickets_never_overlap(monkeypatch):
    """Only one OrbStack env exists — two docker agents would collide."""
    subs = [_sub(order_index=i, needs_docker=True) for i in range(3)]
    rec = await _run_plan(monkeypatch, subs)
    assert len(rec.ran) == 3
    assert rec.max_docker_overlap == 1


async def test_docker_runs_alongside_parallel_work(monkeypatch):
    """Serializing docker must not stall the independent mini-tickets."""
    subs = [_sub(order_index=0, needs_docker=True), _sub(order_index=1, needs_docker=True)]
    subs += [_sub(order_index=2), _sub(order_index=3)]
    rec = await _run_plan(monkeypatch, subs)
    assert rec.max_docker_overlap == 1
    assert rec.max_overlap > 1, "docker chain should run concurrently with the rest"


async def test_one_failure_does_not_stop_siblings(monkeypatch):
    """A failed mini-ticket is recorded on its own row; the rest still run."""
    subs = [_sub(order_index=i) for i in range(3)]
    boom = subs[0].id
    ran: list = []

    async def fake_get(conn, ticket_id):
        return subs

    async def fake_run_subtask(pool, settings, subtask_id):
        if subtask_id == boom:
            raise RuntimeError("agent died")
        ran.append(subtask_id)

    advanced: list = []

    async def fake_advance(conn, ticket_id):
        advanced.append(ticket_id)

    monkeypatch.setattr(dispatch.repository, "get_dispatchable_subtasks", fake_get)
    monkeypatch.setattr(dispatch.repository, "maybe_advance_ticket_to_review", fake_advance)
    monkeypatch.setattr(dispatch, "run_subtask", fake_run_subtask)

    await dispatch.run_ticket_plan(_FakePool(), object(), uuid4())
    assert len(ran) == 2, "siblings of a failed mini-ticket should still run"
    assert advanced, "review roll-up should still be attempted"
