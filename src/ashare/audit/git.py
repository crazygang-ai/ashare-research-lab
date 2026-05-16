"""Non-interactive git status helpers for audit records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class GitStatus:
    sha: str | None
    worktree_clean: bool | None
    dirty_files: list[str]
    warnings: list[str]


def get_git_sha(repo_root: str | Path = ".") -> str | None:
    status = get_worktree_status(repo_root)
    return status.sha


def is_worktree_clean(repo_root: str | Path = ".") -> bool | None:
    return get_worktree_status(repo_root).worktree_clean


def get_worktree_status(repo_root: str | Path = ".", *, max_dirty_files: int = 50) -> GitStatus:
    """Return git sha and dirty files, including untracked files."""

    root = Path(repo_root)
    inside = _run_git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitStatus(
            sha=None,
            worktree_clean=None,
            dirty_files=[],
            warnings=["No git repository found for audit metadata."],
        )

    sha_result = _run_git(root, "rev-parse", "HEAD")
    sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None
    warnings: list[str] = []
    if sha is None:
        warnings.append("Unable to read git sha.")

    status = _run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        return GitStatus(
            sha=sha,
            worktree_clean=False,
            dirty_files=[],
            warnings=[*warnings, "Unable to read git worktree status."],
        )

    dirty = [_parse_status_line(line) for line in status.stdout.splitlines() if line.strip()]
    dirty = [item for item in dirty if item]
    return GitStatus(
        sha=sha,
        worktree_clean=not dirty,
        dirty_files=dirty[:max_dirty_files],
        warnings=warnings,
    )


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def _parse_status_line(line: str) -> str:
    value = line[3:] if len(line) > 3 else line.strip()
    if " -> " in value:
        value = value.split(" -> ", maxsplit=1)[-1]
    return value.strip()
