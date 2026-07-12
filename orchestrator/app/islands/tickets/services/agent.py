"""Agent dispatch (section 7). Drives the Claude Agent SDK lead agent, persists
every streamed event to `agent_events`, and handles the StopFailure -> Qwen
fallback.

What this module owns:
  - composing the dispatch prompt (via policy.build_agent_prompt)
  - streaming SDK events and mapping them to agent_events rows
  - detecting a rate-limit / auth StopFailure and re-dispatching the affected
    subtask through a second SDK call with ANTHROPIC_BASE_URL -> Qwen proxy
  - recording which backend actually completed each subtask

What the *agent itself* owns (via Agent Teams + subagents in the SDK): breaking
the ticket into subtasks, spawning teammates, and isolating each in its own git
worktree. The orchestrator observes and persists that; it does not micro-manage
worktree creation here.

The claude_agent_sdk import is lazy: install it with `uv sync --extra agent`.
Until then, dispatch raises AgentSdkNotInstalled with a clear message.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.core.config import Settings
from app.islands.tickets.services.policy import build_agent_prompt


class AgentSdkNotInstalled(RuntimeError):
    pass


class EventSink(Protocol):
    """Persists a single agent event. Implemented by the DB layer; kept as a
    protocol so dispatch stays testable without a live database."""

    async def record_event(
        self, subtask_id: UUID, event_type: str, payload: dict
    ) -> None: ...


# Map SDK message classes to the agent_events.event_type vocabulary
# (message | tool_use | tool_result | stop | stop_failure).
def _classify_event(message: Any) -> tuple[str, dict]:
    name = type(message).__name__
    payload: dict = {"sdk_type": name}
    # Best-effort extraction; exact SDK shapes are version-dependent.
    for attr in ("content", "text", "name", "input", "result", "subtype", "data"):
        if hasattr(message, attr):
            try:
                payload[attr] = getattr(message, attr)
            except Exception:  # noqa: BLE001 - never let logging break dispatch
                pass

    lname = name.lower()
    if "toolresult" in lname or "tool_result" in lname:
        return "tool_result", payload
    if "tooluse" in lname or "tool_use" in lname:
        return "tool_use", payload
    if "resultmessage" in lname or "result" in lname:
        # ResultMessage carries success/failure; treat error subtypes as failure
        subtype = str(payload.get("subtype", "")).lower()
        is_error = getattr(message, "is_error", False) or "error" in subtype or "limit" in subtype
        return ("stop_failure" if is_error else "stop"), payload
    return "message", payload


def _is_rate_or_auth_failure(payload: dict) -> bool:
    blob = str(payload).lower()
    return any(k in blob for k in ("rate limit", "rate_limit", "429", "overloaded", "auth", "401", "403"))


class AgentDispatcher:
    def __init__(self, settings: Settings, sink: EventSink) -> None:
        self._settings = settings
        self._sink = sink

    def _load_sdk(self):
        try:
            import claude_agent_sdk  # type: ignore
        except ImportError as exc:  # pragma: no cover - env dependent
            raise AgentSdkNotInstalled(
                "claude-agent-sdk is not installed. Run: uv sync --extra agent"
            ) from exc
        return claude_agent_sdk

    def _options(self, sdk, backend: str):
        """Build ClaudeAgentOptions for the given backend. For 'qwen' we point
        ANTHROPIC_BASE_URL at the LiteLLM proxy (section 2 / 7.6)."""
        env: dict[str, str] = {}
        if backend == "qwen":
            if not self._settings.qwen_configured:
                raise RuntimeError("QWEN_PROXY_URL is not set; cannot fall back to Qwen")
            env["ANTHROPIC_BASE_URL"] = self._settings.qwen_proxy_url
        # ClaudeAgentOptions accepts an env mapping for the spawned agent process.
        return sdk.ClaudeAgentOptions(env=env or None)

    async def dispatch(
        self,
        *,
        subtask_id: UUID,
        branch_name: str,
        ticket_title: str,
        ticket_description: str | None,
        processing_instructions: str | None,
        acceptance_criteria: str | None = None,
        backend: str = "claude",
    ) -> str:
        """Run one dispatch for a subtask and stream its events. Returns the
        backend that completed it ('claude' or 'qwen'). On a StopFailure that
        looks like a rate-limit/auth issue while on 'claude', re-dispatches once
        on 'qwen'."""
        sdk = self._load_sdk()
        prompt = build_agent_prompt(
            branch_name=branch_name,
            ticket_title=ticket_title,
            ticket_description=ticket_description,
            processing_instructions=processing_instructions,
            acceptance_criteria=acceptance_criteria,
        )
        options = self._options(sdk, backend)

        hit_failure = False
        async for message in sdk.query(prompt=prompt, options=options):
            event_type, payload = _classify_event(message)
            payload["backend"] = backend
            await self._sink.record_event(subtask_id, event_type, payload)
            if event_type == "stop_failure" and _is_rate_or_auth_failure(payload):
                hit_failure = True
                break

        if hit_failure and backend == "claude" and self._settings.qwen_configured:
            # Section 7.6: re-dispatch the failed subtask on Qwen.
            return await self.dispatch(
                subtask_id=subtask_id,
                branch_name=branch_name,
                ticket_title=ticket_title,
                ticket_description=ticket_description,
                processing_instructions=processing_instructions,
                acceptance_criteria=acceptance_criteria,
                backend="qwen",
            )
        return backend
