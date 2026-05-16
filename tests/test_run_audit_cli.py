from __future__ import annotations

import json
from pathlib import Path
import subprocess

import duckdb
import pytest

from ashare.fixtures.builder import INDEX_CODE, build_fixtures
from ashare.ingest.local import ingest_local


@pytest.fixture()
def fixture_db_path(tmp_path: Path) -> Path:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)
    ingest_local(input_dir=input_dir, db_path=db_path)
    return db_path


def _run_ashare(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["ashare", *args], check=check, capture_output=True, text=True)


def test_calculate_factors_audit_manifest_and_duplicate_run(fixture_db_path: Path) -> None:
    result = _run_ashare(
        [
            "calculate-factors",
            "--db-path", str(fixture_db_path),
            "--as-of", "2026-06-26",
            "--index-code", INDEX_CODE,
            "--source-run-id", "audit-factors",
            "--run-mode", "exploratory",
        ]
    )

    assert "run_id: audit-factors" in result.stdout
    manifest_line = [line for line in result.stdout.splitlines() if line.startswith("manifest: ")][0]
    manifest_path = Path(manifest_line.split(": ", maxsplit=1)[1])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "audit-factors"
    assert manifest["run_mode"] == "exploratory"
    assert manifest["source_run_id"] == "audit-factors"
    assert manifest["status"] == "succeeded"
    assert "worktree_clean" in manifest["git"]

    duplicate = _run_ashare(
        [
            "calculate-factors",
            "--db-path", str(fixture_db_path),
            "--as-of", "2026-06-26",
            "--index-code", INDEX_CODE,
            "--source-run-id", "audit-factors",
        ],
        check=False,
    )
    assert duplicate.returncode != 0
    assert "run_id already exists" in duplicate.stderr


def test_calculate_factors_run_id_must_match_source_run_id(fixture_db_path: Path) -> None:
    result = _run_ashare(
        [
            "calculate-factors",
            "--db-path", str(fixture_db_path),
            "--as-of", "2026-06-26",
            "--source-run-id", "source",
            "--run-id", "other",
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "must equal --source-run-id" in result.stderr


def test_scan_audit_indexes_manifest_and_csv(fixture_db_path: Path, tmp_path: Path) -> None:
    _run_ashare(
        [
            "calculate-factors",
            "--db-path", str(fixture_db_path),
            "--as-of", "2026-06-26",
            "--index-code", INDEX_CODE,
            "--source-run-id", "scan-source",
        ]
    )
    output_dir = tmp_path / "scan"
    result = _run_ashare(
        [
            "scan",
            "--db-path", str(fixture_db_path),
            "--as-of", "2026-06-26",
            "--source-run-id", "scan-source",
            "--sort-factor", "return_20d",
            "--output-dir", str(output_dir),
            "--run-id", "scan-run",
        ]
    )

    assert "run_id: scan-run" in result.stdout
    connection = duckdb.connect(str(fixture_db_path), read_only=True)
    try:
        run = connection.execute(
            "SELECT status, finished_at FROM research_runs WHERE run_id = 'scan-run'"
        ).fetchone()
        artifacts = connection.execute(
            """
            SELECT role, path, sha256
            FROM research_artifacts
            WHERE run_id = 'scan-run'
            ORDER BY role
            """
        ).fetchall()
        inputs = connection.execute(
            "SELECT input_kind, input_ref FROM research_run_inputs WHERE run_id = 'scan-run'"
        ).fetchall()
    finally:
        connection.close()

    assert run[0] == "succeeded"
    assert run[1] is not None
    roles = {row[0] for row in artifacts}
    assert {"candidates_csv", "markdown_report", "manifest"}.issubset(roles)
    assert all(row[2] for row in artifacts)
    assert ("duckdb_table", "factor_values") in inputs


def test_failed_cli_marks_run_failed(fixture_db_path: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "missing"
    result = _run_ashare(
        [
            "scan",
            "--db-path", str(fixture_db_path),
            "--as-of", "2026-06-26",
            "--source-run-id", "missing-source",
            "--sort-factor", "return_20d",
            "--output-dir", str(output_dir),
            "--run-id", "failed-scan",
        ],
        check=False,
    )

    assert result.returncode != 0
    connection = duckdb.connect(str(fixture_db_path), read_only=True)
    try:
        row = connection.execute(
            "SELECT status, finished_at, error FROM research_runs WHERE run_id = 'failed-scan'"
        ).fetchone()
    finally:
        connection.close()

    assert row[0] == "failed"
    assert row[1] is not None
    assert "No scanable factor_values input" in row[2]
