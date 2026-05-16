from __future__ import annotations

import json
from pathlib import Path
import subprocess

import duckdb
import pandas as pd
import pytest

from ashare.fixtures.builder import INDEX_CODE, build_fixtures
from ashare.ingest.local import ingest_local
from ashare.reports.event_study_report import EVENT_STUDY_REPORT_FILES


@pytest.fixture()
def fixture_db_path(tmp_path: Path) -> Path:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)
    ingest_local(input_dir=input_dir, db_path=db_path)
    return db_path


def _run_ashare(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["ashare", *args], check=check, capture_output=True, text=True)


def test_event_study_cli_writes_reports_manifest_and_audit_rows(
    fixture_db_path: Path,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "event-study"
    result = _run_ashare(
        [
            "event-study",
            "--db-path",
            str(fixture_db_path),
            "--event-source",
            "announcements",
            "--event-type",
            "earnings_forecast",
            "--from",
            "2026-01-01",
            "--to",
            "2026-06-26",
            "--horizon",
            "5,20,60",
            "--index-code",
            INDEX_CODE,
            "--benchmark",
            "synthetic_equal_weight",
            "--run-id",
            "event-study-cli",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert "事件研究报告仅供信号验证" in result.stdout
    assert set(path.name for path in output_dir.iterdir()) == {
        *set(EVENT_STUDY_REPORT_FILES.values()),
        "run_manifest.json",
    }
    samples = pd.read_csv(output_dir / "event_samples.csv")
    window_returns = pd.read_csv(output_dir / "event_window_returns.csv")
    summary = pd.read_csv(output_dir / "event_summary.csv")
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert samples["event_source"].tolist() == ["announcements"]
    assert {5, 20, 60}.issubset(set(window_returns["horizon"]))
    assert not summary.empty
    assert manifest["run_id"] == "event-study-cli"
    assert manifest["status"] == "succeeded"

    connection = duckdb.connect(str(fixture_db_path), read_only=True)
    try:
        run = connection.execute(
            "SELECT status, finished_at FROM research_runs WHERE run_id = 'event-study-cli'"
        ).fetchone()
        artifacts = connection.execute(
            """
            SELECT role, artifact_kind
            FROM research_artifacts
            WHERE run_id = 'event-study-cli'
            ORDER BY role
            """
        ).fetchall()
        inputs = connection.execute(
            """
            SELECT input_kind, input_ref
            FROM research_run_inputs
            WHERE run_id = 'event-study-cli'
            """
        ).fetchall()
    finally:
        connection.close()

    assert run[0] == "succeeded"
    assert run[1] is not None
    assert {row[1] for row in artifacts} == {"event_study"}
    assert {"event_samples_csv", "event_window_returns_csv", "event_summary_csv", "manifest"}.issubset(
        {row[0] for row in artifacts}
    )
    assert ("duckdb_table", "announcements") in inputs
    assert ("duckdb_table", "daily_prices") in inputs
    assert ("duckdb_table", "universe_members") in inputs


def test_event_study_cli_requires_explicit_filters(fixture_db_path: Path) -> None:
    result = _run_ashare(
        [
            "event-study",
            "--db-path",
            str(fixture_db_path),
            "--event-source",
            "announcements",
            "--from",
            "2026-01-01",
            "--to",
            "2026-06-26",
            "--horizon",
            "5",
            "--index-code",
            INDEX_CODE,
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "event-type" in result.stderr
