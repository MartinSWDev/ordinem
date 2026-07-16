"""State-machine transition coverage (sections 4 & 5)."""

import pytest

from app.islands.tickets.state_machine import (
    IllegalTransition,
    SubtaskStatus,
    TicketStatus,
    assert_subtask_transition,
    assert_ticket_transition,
    can_transition_subtask,
    can_transition_ticket,
    ticket_review_ready,
)

T = TicketStatus
S = SubtaskStatus


# --- ticket transitions --------------------------------------------------- #


@pytest.mark.parametrize(
    "current,target",
    [
        (T.NEW, T.PLANNED),
        (T.PLANNED, T.IN_PROGRESS),
        (T.IN_PROGRESS, T.REVIEW),
        (T.REVIEW, T.CHECKS_FAILED),
        (T.REVIEW, T.READY_TO_PUSH),
        (T.CHECKS_FAILED, T.IN_PROGRESS),  # agent re-dispatch
        (T.CHECKS_FAILED, T.READY_TO_PUSH),  # fixed by hand
        (T.READY_TO_PUSH, T.PUSHED),
        (T.PUSHED, T.DONE),
    ],
)
def test_legal_ticket_transitions(current, target):
    assert can_transition_ticket(current, target)
    assert_ticket_transition(current, target)  # no raise


@pytest.mark.parametrize(
    "current,target",
    [
        (T.NEW, T.IN_PROGRESS),  # skips planned
        (T.NEW, T.DONE),
        (T.REVIEW, T.PUSHED),  # skips ready_to_push
        (T.DONE, T.IN_PROGRESS),  # terminal
        (T.CHECKS_FAILED, T.REVIEW),  # not allowed backward
    ],
)
def test_illegal_ticket_transitions(current, target):
    assert not can_transition_ticket(current, target)
    with pytest.raises(IllegalTransition):
        assert_ticket_transition(current, target)


@pytest.mark.parametrize(
    "current",
    [T.NEW, T.PLANNED, T.IN_PROGRESS, T.REVIEW, T.CHECKS_FAILED, T.READY_TO_PUSH, T.PUSHED],
)
def test_any_nonterminal_can_abandon(current):
    assert can_transition_ticket(current, T.ABANDONED)


@pytest.mark.parametrize("current", [T.DONE, T.ABANDONED])
def test_terminal_cannot_abandon(current):
    assert not can_transition_ticket(current, T.ABANDONED)


def test_checks_failed_never_auto_loops_without_intervention():
    # Manual-only decision: the only forward paths out of checks_failed are the
    # two deliberate ones. There is no direct checks_failed -> pushed shortcut.
    assert not can_transition_ticket(T.CHECKS_FAILED, T.PUSHED)


# --- subtask transitions -------------------------------------------------- #


@pytest.mark.parametrize(
    "current,target",
    [
        (S.PENDING, S.RUNNING),
        (S.PENDING, S.SKIPPED),
        (S.RUNNING, S.DONE),
        (S.RUNNING, S.FAILED),
        (S.RUNNING, S.AWAITING_INPUT),  # the agent asked the user something
        (S.AWAITING_INPUT, S.RUNNING),  # the user replied
        (S.AWAITING_INPUT, S.SKIPPED),  # conversation abandoned
        (S.DONE, S.RUNNING),  # a reply reopens a finished conversation
        (S.FAILED, S.PENDING),  # requeue (possibly another backend)
    ],
)
def test_legal_subtask_transitions(current, target):
    assert can_transition_subtask(current, target)
    assert_subtask_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        (S.PENDING, S.DONE),
        (S.PENDING, S.AWAITING_INPUT),
        (S.SKIPPED, S.RUNNING),
        (S.RUNNING, S.PENDING),
    ],
)
def test_illegal_subtask_transitions(current, target):
    assert not can_transition_subtask(current, target)
    with pytest.raises(IllegalTransition):
        assert_subtask_transition(current, target)


# --- review-ready rollup -------------------------------------------------- #


def test_review_ready_all_done():
    assert ticket_review_ready([S.DONE, S.DONE, S.SKIPPED])


def test_review_not_ready_with_running():
    assert not ticket_review_ready([S.DONE, S.RUNNING])


def test_review_not_ready_when_empty():
    assert not ticket_review_ready([])
