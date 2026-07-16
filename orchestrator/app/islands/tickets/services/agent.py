"""Agent dispatch (section 7). Runs one mini-ticket through the chosen backend
CLI (see services/backends.py), persists every streamed event to
`agent_events`, and falls back to the local proxy on a rate-limit/auth stop.

What this module owns:
  - composing the dispatch prompt (via policy.build_agent_prompt)
  - streaming backend events and mapping them to agent_events rows
  - detecting a rate-limit / auth StopFailure and re-dispatching the affected
    subtask on the local backend (section 7.6)
  - recording which backend actually completed each subtask

The backends themselves are logged-in subscription CLIs (Claude Code, Cursor)
or the Claude CLI pointed at a local proxy — the orchestrator holds no model
credentials for dispatch.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.islands.tickets.services.backends import (
    BackendUnavailable,
    build_backend,
)
from app.islands.tickets.services.policy import build_agent_prompt


class EventSink(Protocol):
    """Persists a single agent event. Implemented by the DB layer; kept as a
    protocol so dispatch stays testable without a live database."""

    async def record_event(
        self, subtask_id: UUID, event_type: str, payload: dict
    ) -> None: ...


def _is_rate_or_auth_failure(payload: dict) -> bool:
    blob = str(payload).lower()
    return any(k in blob for k in ("rate limit", "rate_limit", "429", "overloaded", "auth", "401", "403"))


class AgentDispatcher:
    def __init__(self, settings: Settings, sink: EventSink) -> None:
        self._settings = settings
        self._sink = sink

    async def dispatch(
        self,
        *,
        subtask_id: UUID,
        branch_name: str,
        ticket_title: str,
        ticket_description: str | None,
        processing_instructions: str | None,
        acceptance_criteria: str | None = None,
        subtask_title: str | None = None,
        subtask_description: str | None = None,
        backend: str = "claude",
        cwd: str,
        resume_session_id: str | None = None,
        prompt_override: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        """Run one dispatch for a subtask and stream its events. Returns the
        backend that completed it, the agent's final report text, and the CLI
        session id (for the conversation loop). With resume_session_id the
        prompt_override (the user's reply) continues that session. On a
        StopFailure that looks like a rate-limit/auth issue, re-dispatches once
        on 'local' if a proxy is configured."""
        runner = build_backend(self._settings, backend)
        prompt = prompt_override or build_agent_prompt(
            branch_name=branch_name,
            ticket_title=ticket_title,
            ticket_description=ticket_description,
            processing_instructions=processing_instructions,
            acceptance_criteria=acceptance_criteria,
            subtask_title=subtask_title,
            subtask_description=subtask_description,
        )

        hit_failure = False
        result: str | None = None
        session_id: str | None = resume_session_id
        async for event_type, payload in runner.run(
            prompt,
            cwd=cwd,
            timeout_seconds=self._settings.agent_timeout_seconds,
            resume_session_id=resume_session_id,
        ):
            payload["backend"] = backend
            await self._sink.record_event(subtask_id, event_type, payload)
            sid = payload.get("stream", {}).get("session_id")
            if sid:
                session_id = str(sid)
            if event_type in ("stop", "stop_failure"):
                raw = payload.get("stream", {}).get("result")
                result = str(raw) if raw is not None else result
            if event_type == "stop_failure" and _is_rate_or_auth_failure(payload):
                hit_failure = True
                break

        if hit_failure and backend != "local" and self._settings.local_proxy:
            # Section 7.6: re-dispatch the failed subtask on the local proxy.
            # A resumed session can't hop backends, so the fallback starts fresh.
            return await self.dispatch(
                subtask_id=subtask_id,
                branch_name=branch_name,
                ticket_title=ticket_title,
                ticket_description=ticket_description,
                processing_instructions=processing_instructions,
                acceptance_criteria=acceptance_criteria,
                subtask_title=subtask_title,
                subtask_description=subtask_description,
                backend="local",
                cwd=cwd,
            )
        if hit_failure:
            raise BackendUnavailable(
                f"backend '{backend}' stopped on a rate-limit/auth failure and "
                "no local fallback is configured"
            )
        return backend, result, session_id
