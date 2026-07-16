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


# --- dispatch sequencing ------------------------------------------------------


class _Recorder:
    """Records overlap: how many subtasks were mid-run at the same moment."""

    def __init__(self) -> None:
        self.running: set = set()
        self.max_overlap = 0
        self.ran: list = []

    async def run(self, subtask_id) -> None:
        self.running.add(subtask_id)
        self.ran.append(subtask_id)
        self.max_overlap = max(self.max_overlap, len(self.running))
        await asyncio.sleep(0.01)  # would let siblings interleave, if any could
        self.running.discard(subtask_id)


async def _run_plan(monkeypatch, subtasks: list[schemas.SubtaskRow]) -> _Recorder:
    rec = _Recorder()

    async def fake_get(conn, ticket_id):
        return subtasks

    async def fake_run_subtask(pool, settings, subtask_id, backend="claude"):
        await rec.run(subtask_id)

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


async def test_mini_tickets_run_strictly_in_sequence(monkeypatch):
    """All mini-tickets share the ticket's single worktree and branch, so two
    agents must never be mid-run at once — they'd trip over each other's files
    and git index. (Parallelism returns with per-subtask worktrees + merge.)"""
    subs = [_sub(order_index=i) for i in range(3)] + [
        _sub(order_index=3, needs_docker=True)
    ]
    rec = await _run_plan(monkeypatch, subs)
    assert len(rec.ran) == 4
    assert rec.max_overlap == 1, "shared-worktree agents must serialize"


async def test_mini_tickets_run_in_plan_order(monkeypatch):
    subs = [_sub(order_index=i) for i in range(4)]
    rec = await _run_plan(monkeypatch, subs)
    assert rec.ran == [s.id for s in subs]


async def test_one_failure_does_not_stop_siblings(monkeypatch):
    """A failed mini-ticket is recorded on its own row; the rest still run."""
    subs = [_sub(order_index=i) for i in range(3)]
    boom = subs[0].id
    ran: list = []

    async def fake_get(conn, ticket_id):
        return subs

    async def fake_run_subtask(pool, settings, subtask_id, backend="claude"):
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
