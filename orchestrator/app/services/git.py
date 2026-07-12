"""Local git helpers for the pre-PR reviewer. Read-only: computes the branch
diff to review; never pushes or mutates the repo."""

from __future__ import annotations

import asyncio


class GitError(RuntimeError):
    pass


async def _git(repo_path: str, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo_path,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise GitError(err.decode(errors="replace").strip() or "git command failed")
    return out.decode(errors="replace")


async def current_branch(repo_path: str) -> str:
    return (await _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")).strip()


async def branch_diff(repo_path: str, base: str, head: str = "HEAD") -> str:
    """Diff of `head` against its merge-base with `base` (i.e. what the branch
    added) — the same set of changes a PR from head into base would show."""
    return await _git(repo_path, "diff", "--merge-base", base, head)
