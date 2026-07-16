"""Agent backends — where a dispatched mini-ticket actually runs.

Each backend is a headless coding-agent CLI spawned as a subprocess in the
repo's checkout. The one-time setup is logging in once on this machine; after
that the orchestrator never touches credentials:

  - claude:  Claude Code CLI (`claude`), billed to the Claude subscription the
             CLI is logged into. `npm i -g @anthropic-ai/claude-code`, run
             `claude` once to log in.
  - cursor:  Cursor CLI (`cursor-agent`), billed to the Cursor subscription.
             `curl https://cursor.com/install -fsS | bash`, `cursor-agent login`.
  - local:   Claude Code CLI pointed at a local OpenAI/Anthropic-compatible
             proxy (LiteLLM in front of a local model) via ANTHROPIC_BASE_URL.
             Available only while the proxy answers a health probe.

Both CLIs emit newline-delimited JSON with `--output-format stream-json`
(Cursor mirrors Claude's shapes), so one classifier maps their lines onto the
agent_events vocabulary: message | tool_use | tool_result | stop | stop_failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from pydantic import BaseModel

from app.core.config import Settings

BACKEND_LABELS = {
    "claude": "Claude Code (subscription)",
    "cursor": "Cursor (subscription)",
    "local": "Local model (proxy)",
}
BACKEND_NAMES = tuple(BACKEND_LABELS)


class BackendUnavailable(RuntimeError):
    pass


class BackendFailed(RuntimeError):
    pass


class BackendInfo(BaseModel):
    """GET /tickets/backends — one dispatch target for the UI picker."""

    name: str
    label: str
    available: bool
    detail: str | None = None


# --------------------------------------------------------------------------- #
# Stream classification
# --------------------------------------------------------------------------- #


def classify_line(line: dict) -> tuple[str, dict]:
    """Map one stream-json line onto the agent_events vocabulary. Best-effort:
    unknown shapes land as plain messages rather than being dropped."""
    kind = str(line.get("type", "")).lower()
    payload: dict = {"stream": line}

    if kind == "result":
        subtype = str(line.get("subtype", "")).lower()
        is_error = bool(line.get("is_error")) or "error" in subtype or "limit" in subtype
        return ("stop_failure" if is_error else "stop"), payload
    if kind == "assistant":
        content = (line.get("message") or {}).get("content") or []
        if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
            return "tool_use", payload
        return "message", payload
    if kind == "user":
        # In stream-json a user turn mid-run carries tool results back in.
        return "tool_result", payload
    return "message", payload


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #


@dataclass
class CliBackend:
    """A headless agent CLI: spawn, stream json lines, classify."""

    name: str
    label: str
    argv_head: list[str]
    env_overrides: dict[str, str]
    drop_env: tuple[str, ...] = ()
    # Flag that continues a previous session (the conversation loop). Both the
    # Claude and Cursor CLIs use --resume; None = backend can't resume.
    resume_flag: str | None = "--resume"

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in self.drop_env}
        env.update(self.env_overrides)
        return env

    async def run(
        self,
        prompt: str,
        *,
        cwd: str,
        timeout_seconds: int,
        resume_session_id: str | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        """Yield classified events from one agent run. Raises BackendFailed if
        the process dies without ever emitting a result line."""
        argv = list(self.argv_head)
        if resume_session_id:
            if not self.resume_flag:
                raise BackendUnavailable(
                    f"backend '{self.name}' cannot resume a session"
                )
            argv += [self.resume_flag, resume_session_id]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            prompt,
            cwd=cwd,
            env=self._env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        saw_result = False
        try:
            async with asyncio.timeout(timeout_seconds):
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    text = raw.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        line = json.loads(text)
                    except json.JSONDecodeError:
                        yield "message", {"stream": {"type": "raw", "text": text}}
                        continue
                    event_type, payload = classify_line(line)
                    saw_result = saw_result or event_type in ("stop", "stop_failure")
                    yield event_type, payload
                await proc.wait()
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

        if not saw_result:
            stderr = b""
            if proc.stderr is not None:
                stderr = await proc.stderr.read()
            tail = stderr.decode("utf-8", errors="replace").strip()[-2000:]
            raise BackendFailed(
                f"{self.label} exited (code {proc.returncode}) without a result"
                + (f": {tail}" if tail else "")
            )


def _which(cli: str) -> str | None:
    return shutil.which(cli)


def _claude_argv(settings: Settings) -> list[str]:
    return [
        settings.claude_cli,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        settings.agent_permission_mode,
    ]


def build_backend(settings: Settings, name: str) -> CliBackend:
    """Construct a backend or raise BackendUnavailable with a fix-it message."""
    if name == "claude":
        if not _which(settings.claude_cli):
            raise BackendUnavailable(
                f"'{settings.claude_cli}' not found — install Claude Code and "
                "log in once (npm i -g @anthropic-ai/claude-code; claude)"
            )
        # Drop any ambient API key so the CLI bills the subscription login,
        # not the orchestrator's API key.
        return CliBackend(
            name="claude",
            label=BACKEND_LABELS["claude"],
            argv_head=_claude_argv(settings),
            env_overrides={},
            drop_env=("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
        )
    if name == "cursor":
        if not _which(settings.cursor_cli):
            raise BackendUnavailable(
                f"'{settings.cursor_cli}' not found — install the Cursor CLI "
                "and log in once (curl https://cursor.com/install -fsS | bash; "
                "cursor-agent login)"
            )
        argv = [settings.cursor_cli, "--print", "--output-format", "stream-json"]
        if settings.cursor_force:
            argv.append("--force")
        return CliBackend(
            name="cursor",
            label=BACKEND_LABELS["cursor"],
            argv_head=argv,
            env_overrides={},
        )
    if name == "local":
        if not settings.local_proxy:
            raise BackendUnavailable(
                "no local proxy configured — set LOCAL_PROXY_URL (or "
                "QWEN_PROXY_URL) to your LiteLLM endpoint"
            )
        if not _which(settings.claude_cli):
            raise BackendUnavailable(
                f"'{settings.claude_cli}' not found — the local backend drives "
                "the Claude Code CLI against the proxy"
            )
        env = {"ANTHROPIC_BASE_URL": settings.local_proxy}
        if settings.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        return CliBackend(
            name="local",
            label=BACKEND_LABELS["local"],
            argv_head=_claude_argv(settings),
            env_overrides=env,
        )
    raise BackendUnavailable(f"unknown backend '{name}'")


async def _local_proxy_alive(settings: Settings) -> str | None:
    """None if the proxy answers, else the reason it doesn't."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.get(settings.local_proxy)
        return None
    except httpx.HTTPError as exc:
        return f"proxy at {settings.local_proxy} not responding ({exc.__class__.__name__})"


async def list_backends(settings: Settings) -> list[BackendInfo]:
    """Probe every backend — feeds the UI picker. Availability is cheap to
    re-check, so this always probes live rather than caching."""
    out: list[BackendInfo] = []
    for name in BACKEND_NAMES:
        try:
            backend = build_backend(settings, name)
        except BackendUnavailable as exc:
            out.append(
                BackendInfo(
                    name=name,
                    label=BACKEND_LABELS[name],
                    available=False,
                    detail=str(exc),
                )
            )
            continue
        detail: str | None = None
        if name == "local":
            detail = await _local_proxy_alive(settings)
        out.append(
            BackendInfo(
                name=name,
                label=backend.label,
                available=detail is None,
                detail=detail,
            )
        )
    return out
