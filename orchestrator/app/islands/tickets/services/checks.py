"""Local checks (section 8). Shells out to the repo's EXISTING pre-push hook —
we deliberately do not reimplement lint/test logic here.

If the repo has no pre-push hook, that's reported as an 'error' check_run
rather than a silent pass.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    check_name: str
    status: str  # 'pass' | 'fail' | 'error'
    output: str


async def run_pre_push_checks(repo_path: str) -> CheckResult:
    """Run the repo's .git/hooks/pre-push (or core.hooksPath equivalent).

    Git normally feeds pre-push refs on stdin; for a manual check run we invoke
    it with empty stdin, which is what a hook sees when there's nothing to push
    but still exercises lint/test gates that ignore the ref list.
    """
    repo = Path(repo_path)
    hook = repo / ".git" / "hooks" / "pre-push"
    if not hook.exists():
        return CheckResult(
            check_name="pre-push",
            status="error",
            output=f"no pre-push hook found at {hook}",
        )
    if not os.access(hook, os.X_OK):
        return CheckResult(
            check_name="pre-push",
            status="error",
            output=f"pre-push hook is not executable: {hook}",
        )

    proc = await asyncio.create_subprocess_exec(
        str(hook),
        cwd=str(repo),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode(errors="replace")
    status = "pass" if proc.returncode == 0 else "fail"
    return CheckResult(check_name="pre-push", status=status, output=output)
