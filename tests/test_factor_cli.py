from __future__ import annotations

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
    return subprocess.run(
        ["ashare", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _factor_count(db_path: Path, source_run_id: str) -> int:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM factor_values WHERE source_run_id = ?",
            [source_run_id],
        ).fetchone()[0]
    finally:
        connection.close()


def test_cli_calculate_factors_single_date_writes_factor_values(
    fixture_db_path: Path,
) -> None:
    result = _run_ashare(
        [
            "calculate-factors",
            "--db-path",
            str(fixture_db_path),
            "--as-of",
            "2026-06-26",
            "--index-code",
            INDEX_CODE,
            "--source-run-id",
            "cli-single",
        ]
    )

    assert "Date mode: as-of 2026-06-26" in result.stdout
    assert "universe_size: 4" in result.stdout
    assert "written_rows: 58" in result.stdout
    assert "  return_20d: 4" in result.stdout
    assert "  volatility_20d: 4" in result.stdout
    assert "  operating_cashflow_to_profit: 4" in result.stdout
    assert _factor_count(fixture_db_path, "cli-single") == 58

    connection = duckdb.connect(str(fixture_db_path), read_only=True)
    try:
        research_runs = connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0]
        run = connection.execute(
            """
            SELECT run_id, status, finished_at, error
            FROM research_runs
            WHERE run_id = 'cli-single'
            """
        ).fetchone()
        manifest_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM research_artifacts
            WHERE run_id = 'cli-single' AND role = 'manifest'
            """
        ).fetchone()[0]
    finally:
        connection.close()
    assert research_runs == 1
    assert run[0] == "cli-single"
    assert run[1] == "succeeded"
    assert run[2] is not None
    assert run[3] is None
    assert manifest_count == 1


def test_cli_calculate_factors_range_mode_filters_open_dates(
    fixture_db_path: Path,
) -> None:
    result = _run_ashare(
        [
            "calculate-factors",
            "--db-path",
            str(fixture_db_path),
            "--from",
            "2026-06-25",
            "--to",
            "2026-06-28",
            "--index-code",
            INDEX_CODE,
            "--source-run-id",
            "cli-range",
        ]
    )

    assert "Date mode: range 2026-06-25 to 2026-06-28" in result.stdout
    assert "  2026-06-25: 4" in result.stdout
    assert "  2026-06-26: 4" in result.stdout
    assert _factor_count(fixture_db_path, "cli-range") > 0


def test_cli_range_with_no_open_dates_succeeds_with_zero_rows(
    fixture_db_path: Path,
) -> None:
    result = _run_ashare(
        [
            "calculate-factors",
            "--db-path",
            str(fixture_db_path),
            "--from",
            "2026-06-27",
            "--to",
            "2026-06-28",
            "--source-run-id",
            "cli-empty-range",
        ]
    )

    assert "(no open trading dates)" in result.stdout
    assert "written_rows: 0" in result.stdout
    assert _factor_count(fixture_db_path, "cli-empty-range") == 0


def test_cli_empty_universe_succeeds_with_zero_rows(fixture_db_path: Path) -> None:
    result = _run_ashare(
        [
            "calculate-factors",
            "--db-path",
            str(fixture_db_path),
            "--as-of",
            "2026-06-26",
            "--index-code",
            "EMPTY_INDEX",
            "--source-run-id",
            "cli-empty-universe",
        ]
    )

    assert "universe_size: 0" in result.stdout
    assert "written_rows: 0" in result.stdout


def test_cli_repeated_factor_option_limits_written_factor_names(fixture_db_path: Path) -> None:
    _run_ashare(
        [
            "calculate-factors",
            "--db-path",
            str(fixture_db_path),
            "--as-of",
            "2026-06-26",
            "--factor",
            "return_20d",
            "--factor",
            "is_st",
            "--source-run-id",
            "cli-subset",
        ]
    )

    connection = duckdb.connect(str(fixture_db_path), read_only=True)
    try:
        names = {
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT factor_name
                FROM factor_values
                WHERE source_run_id = 'cli-subset'
                """
            ).fetchall()
        }
    finally:
        connection.close()

    assert names == {"return_20d", "is_st"}


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["calculate-factors"], "Choose single-date mode"),
        (
            [
                "calculate-factors",
                "--as-of",
                "2026-06-26",
                "--from",
                "2026-06-25",
                "--to",
                "2026-06-26",
            ],
            "mutually exclusive",
        ),
        (["calculate-factors", "--from", "2026-06-25"], "requires both --from and --to"),
        (["calculate-factors", "--as-of", "2026-06-27"], "not a trading day"),
    ],
)
def test_cli_calculate_factors_rejects_invalid_date_modes(
    fixture_db_path: Path,
    args: list[str],
    message: str,
) -> None:
    result = _run_ashare([args[0], "--db-path", str(fixture_db_path), *args[1:]], check=False)

    assert result.returncode != 0
    assert message in result.stderr


def test_cli_help_lists_calculate_factors_and_existing_commands() -> None:
    result = _run_ashare(["--help"])

    for command in [
        "calculate-factors",
        "as-of",
        "db-init",
        "ingest-local",
        "validate-factors",
        "scan",
    ]:
        assert command in result.stdout
