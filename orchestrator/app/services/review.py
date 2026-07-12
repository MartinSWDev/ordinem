"""Pre-PR code review via Claude, guided by device-global company semantics.

Reviews the branch diff against `~/.ordinem/review.md` (freeform team
conventions) plus general best practice, returning structured findings. Runs on
the work Mac so code never leaves the machine except to the LLM the user chose:
Claude by default, or the local Qwen proxy as a fallback (same reasoning as the
ticket agent's StopFailure fallback).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from ..config import Settings
from ..schemas import ReviewResult

SEMANTICS_PATH = Path.home() / ".ordinem" / "review.md"

# Coverage-first prompt: current Claude models follow "only high-severity"
# instructions literally, so we explicitly ask for everything and rank by
# severity — a downstream/human step filters. (See the claude-api code-review
# guidance.)
SYSTEM_PROMPT = """\
You are a senior code reviewer for this team, doing a pre-PR review of a diff.

<company_semantics>
{semantics}
</company_semantics>

Review the diff against BOTH the company semantics above and general
engineering best practice (correctness, security, error handling, tests,
clarity). Report EVERY issue you find, including low-severity and uncertain
ones — do not filter for importance; a downstream step does that. For each
finding give: the file path, the line number (best guess, or null), a severity
of high/medium/low, a short kebab-case category, a clear comment, and a
concrete suggestion when you have one (else null). Also write a one-paragraph
summary. Only review the provided diff; do not invent files.
"""

# Structured-output schema (no unsupported constraints like minLength).
FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": ["integer", "null"]},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "category": {"type": "string"},
                    "comment": {"type": "string"},
                    "suggestion": {"type": ["string", "null"]},
                },
                "required": ["file", "line", "severity", "category", "comment", "suggestion"],
            },
        },
    },
    "required": ["summary", "findings"],
}


def load_semantics() -> str | None:
    """The device-global company conventions, if present."""
    return SEMANTICS_PATH.read_text() if SEMANTICS_PATH.exists() else None


def _client(settings: Settings, *, base_url: str | None = None) -> AsyncAnthropic:
    kwargs: dict[str, Any] = {}
    url = base_url or settings.anthropic_base_url
    if url:
        kwargs["base_url"] = url
    if settings.anthropic_api_key:
        kwargs["api_key"] = settings.anthropic_api_key
    return AsyncAnthropic(**kwargs)


async def _call(client: AsyncAnthropic, model: str, system: str, diff: str) -> dict[str, Any]:
    """One structured-output review call. Streaming keeps large outputs under
    HTTP timeouts; adaptive thinking + high effort for review quality."""
    async with client.messages.stream(
        model=model,
        max_tokens=32000,
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema", "schema": FINDINGS_SCHEMA},
            "effort": "high",
        },
        system=system,
        messages=[{"role": "user", "content": diff}],
    ) as stream:
        message = await stream.get_final_message()
    text = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
    return json.loads(text)


async def run_review(diff: str, semantics: str | None, settings: Settings) -> ReviewResult:
    """Review a diff. Tries Claude first; on any failure, retries against the
    Qwen proxy if configured (requires an Anthropic-compatible endpoint)."""
    system = SYSTEM_PROMPT.format(semantics=semantics or "(no company semantics configured)")
    try:
        data = await _call(_client(settings), settings.review_model, system, diff)
    except Exception:
        if not settings.qwen_configured:
            raise
        qclient = _client(settings, base_url=settings.qwen_proxy_url)
        data = await _call(qclient, settings.review_model, system, diff)
    return ReviewResult(**data)
