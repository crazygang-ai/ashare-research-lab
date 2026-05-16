from pathlib import Path
import subprocess

import duckdb

from ashare.fixtures.builder import build_fixtures


def test_cli_source_csv_requires_fallback_dir(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "ashare",
            "ingest",
            "--source",
            "csv",
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-14",
            "--db-path",
            str(tmp_path / "missing.duckdb"),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--source csv requires --fallback-csv-dir" in result.stderr


def test_cli_source_auto_without_fallback_prints_warning(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "ashare",
            "ingest",
            "--source",
            "auto",
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-14",
            "--db-path",
            str(tmp_path / "auto.duckdb"),
            "--cache-mode",
            "offline",
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--source auto without --allow-fallback is equivalent to --source akshare" in (
        result.stdout + result.stderr
    )


def test_cli_csv_ingest_succeeds_and_does_not_write_factor_values(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    db_path = tmp_path / "cli.duckdb"
    report_dir = tmp_path / "reports"
    build_fixtures(fixture_dir)

    result = subprocess.run(
        [
            "ashare",
            "ingest",
            "--source",
            "csv",
            "--source-tag",
            "phase1a7-cli",
            "--universe",
            "hs300",
            "--index-code",
            "LOCAL_FIXTURE",
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-14",
            "--universe-as-of",
            "2026-03-30",
            "--db-path",
            str(db_path),
            "--fallback-csv-dir",
            str(fixture_dir),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--quality-report-dir",
            str(report_dir),
            "--overwrite-report",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        factor_rows = connection.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0]
        sources = {
            row[0]
            for row in connection.execute("SELECT DISTINCT source FROM valuation_daily").fetchall()
        }
    finally:
        connection.close()

    assert "Phase 1a-7 ingest completed." in result.stdout
    assert "effective_source: csv" in result.stdout
    assert "cache:" in result.stdout
    assert factor_rows == 0
    assert sources == {"phase1a7-cli"}
    assert (report_dir / "data_quality_report.md").is_file()
    assert not (tmp_path / "reports" / "scan").exists()
    assert not (tmp_path / "reports" / "factor-validation").exists()


def test_cli_help_lists_required_commands() -> None:
    result = subprocess.run(
        ["ashare", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    for command in [
        "ingest",
        "validate-factors",
        "event-study",
        "daily-report",
        "scan",
        "backtest",
        "report",
        "stock-report",
        "db-init",
        "ingest-local",
        "ingest-announcements",
        "parse-announcements",
        "as-of",
        "calculate-factors",
    ]:
        assert command in result.stdout
