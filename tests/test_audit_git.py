from __future__ import annotations

from pathlib import Path
import subprocess

from ashare.audit.git import get_git_sha, get_worktree_status, is_worktree_clean


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_git_helpers_detect_clean_dirty_and_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "tracked.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")

    assert get_git_sha(repo)
    assert is_worktree_clean(repo) is True

    (repo / "tracked.txt").write_text("b\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("u\n", encoding="utf-8")
    status = get_worktree_status(repo)

    assert status.worktree_clean is False
    assert "tracked.txt" in status.dirty_files
    assert "untracked.txt" in status.dirty_files


def test_git_helpers_handle_non_git_directory(tmp_path: Path) -> None:
    status = get_worktree_status(tmp_path)

    assert status.sha is None
    assert status.worktree_clean is None
    assert status.warnings
