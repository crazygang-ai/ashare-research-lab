from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from ashare.audit.context import AuditContext


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo_with_audit_config(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "configs").mkdir(parents=True)
    (repo / "src" / "ashare").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "configs" / "audit.yaml").write_text(
        """
version: phase5.v1
run_tracking:
  enabled: true
  default_run_mode: exploratory
  formal_requires_clean_worktree: true
  fail_on_duplicate_run_id: true
  manifest_filename: run_manifest.json
""".lstrip(),
        encoding="utf-8",
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    return repo


def test_formal_run_requires_clean_worktree(tmp_path: Path) -> None:
    repo = _repo_with_audit_config(tmp_path)

    with pytest.raises(ValueError, match="formal run requires a clean git worktree"):
        AuditContext(
            command="scan",
            artifact_kind="scan",
            db_path=repo / "db.duckdb",
            run_id="formal",
            run_mode="formal",
            overwrite_run=False,
            audit_config_path=repo / "configs/audit.yaml",
            output_dir=repo / "reports/formal",
            as_of_date="2026-01-02",
            source_run_id="source",
            params={},
        )


def test_exploratory_run_allows_dirty_and_marks_manifest(tmp_path: Path) -> None:
    repo = _repo_with_audit_config(tmp_path)
    context = AuditContext(
        command="scan",
        artifact_kind="scan",
        db_path=repo / "db.duckdb",
        run_id="explore",
        run_mode="exploratory",
        overwrite_run=False,
        audit_config_path=repo / "configs/audit.yaml",
        output_dir=repo / "reports/explore",
        as_of_date="2026-01-02",
        source_run_id="source",
        params={},
    )

    context.begin()
    context.succeed()
    context.close()
    manifest = json.loads((repo / "reports/explore/run_manifest.json").read_text(encoding="utf-8"))

    assert manifest["run_mode"] == "exploratory"
    assert manifest["git"]["worktree_clean"] is False
    assert "dirty.txt" in manifest["git"]["dirty_files"]
