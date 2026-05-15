from __future__ import annotations

from pathlib import Path
import subprocess

import duckdb
import pandas as pd
import pytest

from ashare.fixtures.builder import INDEX_CODE, build_fixtures
from ashare.ingest.local import ingest_local


SOURCE_RUN_ID = "report-cli"


@pytest.fixture(scope="module")
def report_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("report_cli")
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)
    ingest_local(input_dir=input_dir, db_path=db_path)
    _run_ashare(
        [
            "calculate-factors",
            "--db-path",
            str(db_path),
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-29",
            "--index-code",
            INDEX_CODE,
            "--source-run-id",
            SOURCE_RUN_ID,
        ]
    )
    return db_path


def _run_ashare(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ashare", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _tables(db_path: Path) -> set[str]:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    finally:
        connection.close()


def _factor_values_count(db_path: Path) -> int:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0])
    finally:
        connection.close()


def test_report_cli_generates_factor_validation_report_and_does_not_write_db(
    report_db_path: Path,
    tmp_path: Path,
) -> None:
    before_tables = _tables(report_db_path)
    before_factor_values = _factor_values_count(report_db_path)
    output_dir = tmp_path / "report"

    result = _run_ashare(
        [
            "report",
            "--kind",
            "factor-validation",
            "--db-path",
            str(report_db_path),
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-29",
            "--source-run-id",
            SOURCE_RUN_ID,
            "--factor",
            "return_20d",
            "--factor",
            "pe_ttm_percentile",
            "--horizon",
            "5,20",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert "factor_validation_report.md" in result.stdout
    assert "coverage.csv" in result.stdout
    assert (output_dir / "factor_validation_report.md").exists()
    for filename in [
        "coverage.csv",
        "label_summary.csv",
        "rank_ic.csv",
        "ic_summary.csv",
        "group_returns.csv",
        "decay_curve.csv",
    ]:
        assert (output_dir / filename).exists()

    rank_ic = pd.read_csv(output_dir / "rank_ic.csv")
    if not rank_ic.empty:
        expected = rank_ic.sort_values(["factor_name", "horizon", "trade_date"]).reset_index(
            drop=True
        )
        pd.testing.assert_frame_equal(rank_ic.reset_index(drop=True), expected)

    assert _tables(report_db_path) == before_tables
    assert _factor_values_count(report_db_path) == before_factor_values


def test_report_cli_rejects_other_kind() -> None:
    result = _run_ashare(
        [
            "report",
            "--kind",
            "other",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-02",
            "--source-run-id",
            "run",
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "only supports --kind factor-validation" in result.stderr


def test_report_help_mentions_factor_validation() -> None:
    result = _run_ashare(["report", "--help"])

    assert "factor-validation" in result.stdout
    assert "--kind" in result.stdout
