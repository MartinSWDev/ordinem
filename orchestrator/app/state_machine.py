"""Ticket and subtask state machines (sections 4 & 5 of the spec).

Transitions are validated centrally so no route can persist an illegal status
jump. `checks_failed` is resolved by manual intervention only (per decision):
it can loop back to in_progress (agent re-dispatch) or go straight to
ready_to_push if the user fixed the check by hand — but never auto-retries.
"""

from __future__ import annotations

from enum import StrEnum


class TicketStatus(StrEnum):
    NEW = "new"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    CHECKS_FAILED = "checks_failed"
    READY_TO_PUSH = "ready_to_push"
    PUSHED = "pushed"
    DONE = "done"
    ABANDONED = "abandoned"


class SubtaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


# section 4. `abandoned` is reachable from any non-terminal state (added below).
_TICKET_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.NEW: {TicketStatus.PLANNED},
    TicketStatus.PLANNED: {TicketStatus.IN_PROGRESS},
    TicketStatus.IN_PROGRESS: {TicketStatus.REVIEW},
    # review can pass its checks (ready_to_push) or fail them (checks_failed)
    TicketStatus.REVIEW: {TicketStatus.CHECKS_FAILED, TicketStatus.READY_TO_PUSH},
    # manual intervention only: back to the agent, or forward once fixed by hand
    TicketStatus.CHECKS_FAILED: {TicketStatus.IN_PROGRESS, TicketStatus.READY_TO_PUSH},
    TicketStatus.READY_TO_PUSH: {TicketStatus.PUSHED},
    TicketStatus.PUSHED: {TicketStatus.DONE},
    TicketStatus.DONE: set(),
    TicketStatus.ABANDONED: set(),
}

# "any state -> abandoned" (except the terminal ones)
_TERMINAL_TICKET = {TicketStatus.DONE, TicketStatus.ABANDONED}

# section 5
_SUBTASK_TRANSITIONS: dict[SubtaskStatus, set[SubtaskStatus]] = {
    SubtaskStatus.PENDING: {SubtaskStatus.RUNNING, SubtaskStatus.SKIPPED},
    SubtaskStatus.RUNNING: {SubtaskStatus.DONE, SubtaskStatus.FAILED},
    # requeued after a failure, possibly with backend switched to qwen
    SubtaskStatus.FAILED: {SubtaskStatus.PENDING},
    SubtaskStatus.DONE: set(),
    SubtaskStatus.SKIPPED: set(),
}


class IllegalTransition(ValueError):
    def __init__(self, current: str, target: str, kind: str) -> None:
        super().__init__(f"illegal {kind} transition: {current} -> {target}")
        self.current = current
        self.target = target
        self.kind = kind


def can_transition_ticket(current: TicketStatus, target: TicketStatus) -> bool:
    if target == TicketStatus.ABANDONED:
        return current not in _TERMINAL_TICKET
    return target in _TICKET_TRANSITIONS.get(current, set())


def assert_ticket_transition(current: TicketStatus, target: TicketStatus) -> None:
    if not can_transition_ticket(current, target):
        raise IllegalTransition(current, target, "ticket")


def can_transition_subtask(current: SubtaskStatus, target: SubtaskStatus) -> bool:
    return target in _SUBTASK_TRANSITIONS.get(current, set())


def assert_subtask_transition(current: SubtaskStatus, target: SubtaskStatus) -> None:
    if not can_transition_subtask(current, target):
        raise IllegalTransition(current, target, "subtask")


def ticket_review_ready(subtask_statuses: list[SubtaskStatus]) -> bool:
    """A ticket becomes `review` once every subtask is done or skipped
    (section 7.7). An empty subtask list is not review-ready."""
    if not subtask_statuses:
        return False
    return all(
        s in (SubtaskStatus.DONE, SubtaskStatus.SKIPPED) for s in subtask_statuses
    )
