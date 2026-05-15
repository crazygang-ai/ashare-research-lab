from pathlib import Path
import subprocess

import duckdb

from ashare.fixtures.builder import build_fixtures


def test_announcement_ingest_and_parse_cli_roundtrip(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    db_path = tmp_path / "phase2.duckdb"
    build_fixtures(fixture_dir)

    subprocess.run(
        [
            "ashare",
            "ingest-local",
            "--input-dir",
            str(fixture_dir),
            "--db-path",
            str(db_path),
            "--no-build-fixtures",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    ingest = subprocess.run(
        [
            "ashare",
            "ingest-announcements",
            "--source",
            "csv",
            "--source-tag",
            "phase2-fixture",
            "--input-csv",
            str(fixture_dir / "announcements.csv"),
            "--body-dir",
            str(fixture_dir / "announcement_bodies"),
            "--from",
            "2026-01-05",
            "--to",
            "2026-03-31",
            "--db-path",
            str(db_path),
            "--raw-output-dir",
            str(tmp_path / "raw"),
            "--overwrite",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    parse = subprocess.run(
        [
            "ashare",
            "parse-announcements",
            "--db-path",
            str(db_path),
            "--from",
            "2026-01-06",
            "--to",
            "2026-03-31",
            "--as-of",
            "2026-03-31",
            "--source-tag",
            "phase2-fixture",
            "--parse-run-id",
            "phase2-fixture-parse",
            "--llm-mode",
            "fixture",
            "--fixture-response-dir",
            str(fixture_dir / "llm_responses"),
            "--model",
            "fixture-llm",
            "--overwrite",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        parse_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM announcement_llm_results
            WHERE parse_run_id = 'phase2-fixture-parse'
              AND status = 'success'
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert "date_filter: publish_time 2026-01-05 to 2026-03-31" in ingest.stdout
    assert "date_filter: effective_date 2026-01-06 to 2026-03-31" in parse.stdout
    assert parse_rows == 3


def test_cli_help_lists_phase2_commands() -> None:
    result = subprocess.run(
        ["ashare", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "ingest-announcements" in result.stdout
    assert "parse-announcements" in result.stdout
