import csv
from datetime import date, datetime
from pathlib import Path
import subprocess

import duckdb

from ashare.fixtures.builder import build_fixtures
from ashare.ingest.local import TABLE_ORDER, ingest_local


def _csv_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as file:
        return sum(1 for _ in csv.DictReader(file))


def _drop_csv_columns(path: Path, columns: set[str]) -> None:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = [field for field in reader.fieldnames or [] if field not in columns]
        rows = [{field: row[field] for field in fieldnames} for row in reader]

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _blank_csv_columns(path: Path, columns: set[str]) -> None:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    for row in rows:
        for column in columns:
            if column in row:
                row[column] = ""

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _table_counts(db_path: Path) -> dict[str, int]:
    connection = duckdb.connect(str(db_path))
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLE_ORDER
        }
    finally:
        connection.close()


def test_ingest_local_loads_fixture_csvs_and_expected_counts(tmp_path: Path) -> None:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)

    summary = ingest_local(input_dir=input_dir, db_path=db_path)
    expected_counts = {table: _csv_count(input_dir / f"{table}.csv") for table in TABLE_ORDER}

    assert summary == expected_counts
    assert _table_counts(db_path) == expected_counts


def test_ingest_local_casts_payload_json_and_calculates_effective_dates(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)

    ingest_local(input_dir=input_dir, db_path=db_path)

    connection = duckdb.connect(str(db_path))
    try:
        payload_holder = connection.execute(
            """
            SELECT json_extract_string(payload_json, '$.holder')
            FROM risk_events
            WHERE event_type = 'pledge'
            """
        ).fetchone()[0]
        fundamental_effective_date = connection.execute(
            """
            SELECT effective_date
            FROM fundamental_reports
            WHERE publish_time = TIMESTAMP '2026-01-05 18:00:00'
            """
        ).fetchone()[0]
        announcement_effective_date = connection.execute(
            """
            SELECT effective_date
            FROM announcements
            WHERE announcement_type = 'buyback'
            """
        ).fetchone()[0]
        risk_effective_date = connection.execute(
            """
            SELECT effective_date
            FROM risk_events
            WHERE event_type = 'shareholder_reduce'
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert payload_holder == "controlling_shareholder"
    assert fundamental_effective_date == date(2026, 1, 6)
    assert announcement_effective_date == date(2026, 1, 12)
    assert risk_effective_date == date(2026, 1, 12)


def test_ingest_local_imports_interval_visibility_fields(tmp_path: Path) -> None:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)

    ingest_local(input_dir=input_dir, db_path=db_path)

    connection = duckdb.connect(str(db_path))
    try:
        delist = connection.execute(
            """
            SELECT delist_publish_time, delist_effective_date
            FROM securities
            WHERE stock_code = '000003.SZ'
            """
        ).fetchone()
        universe_exit = connection.execute(
            """
            SELECT out_publish_time, out_effective_date
            FROM universe_members
            WHERE stock_code = '000003.SZ'
            """
        ).fetchone()
        st_exit = connection.execute(
            """
            SELECT in_publish_time, in_effective_date, out_publish_time, out_effective_date
            FROM st_status
            WHERE stock_code = '000002.SZ'
            """
        ).fetchone()
    finally:
        connection.close()

    assert delist == (datetime(2026, 3, 2, 18, 0), date(2026, 3, 3))
    assert universe_exit == (datetime(2026, 3, 2, 18, 0), date(2026, 3, 3))
    assert st_exit == (
        datetime(2026, 1, 20, 18, 0),
        date(2026, 1, 21),
        datetime(2026, 2, 16, 18, 0),
        date(2026, 2, 17),
    )


def test_ingest_local_accepts_legacy_interval_csvs_and_backfills_effective_dates(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "legacy"
    db_path = tmp_path / "legacy.duckdb"
    build_fixtures(input_dir)
    _drop_csv_columns(input_dir / "securities.csv", {"delist_publish_time", "delist_effective_date"})
    for filename in ["industry_classifications.csv", "universe_members.csv", "st_status.csv"]:
        _drop_csv_columns(
            input_dir / filename,
            {"in_publish_time", "in_effective_date", "out_publish_time", "out_effective_date"},
        )

    ingest_local(input_dir=input_dir, db_path=db_path)

    connection = duckdb.connect(str(db_path))
    try:
        delist = connection.execute(
            """
            SELECT delist_publish_time, delist_effective_date
            FROM securities
            WHERE stock_code = '000003.SZ'
            """
        ).fetchone()
        universe = connection.execute(
            """
            SELECT in_effective_date, out_publish_time, out_effective_date
            FROM universe_members
            WHERE stock_code = '000003.SZ'
            """
        ).fetchone()
        st = connection.execute(
            """
            SELECT in_effective_date, out_effective_date
            FROM st_status
            WHERE stock_code = '000002.SZ'
            """
        ).fetchone()
        industry = connection.execute(
            """
            SELECT in_effective_date, out_effective_date
            FROM industry_classifications
            WHERE stock_code = '000005.SZ'
              AND industry_l2 = 'Software'
            """
        ).fetchone()
    finally:
        connection.close()

    assert delist == (None, date(2026, 3, 6))
    assert universe == (date(2026, 1, 5), None, date(2026, 3, 6))
    assert st == (date(2026, 1, 21), date(2026, 2, 18))
    assert industry == (date(2026, 1, 5), date(2026, 2, 16))


def test_ingest_local_backfills_empty_visibility_effective_dates_from_publish_time(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)
    _blank_csv_columns(input_dir / "securities.csv", {"delist_effective_date"})
    _blank_csv_columns(
        input_dir / "universe_members.csv",
        {"in_effective_date", "out_effective_date"},
    )
    _blank_csv_columns(input_dir / "st_status.csv", {"in_effective_date", "out_effective_date"})
    _blank_csv_columns(
        input_dir / "industry_classifications.csv",
        {"in_effective_date", "out_effective_date"},
    )

    ingest_local(input_dir=input_dir, db_path=db_path)

    connection = duckdb.connect(str(db_path))
    try:
        delist_effective = connection.execute(
            """
            SELECT delist_effective_date
            FROM securities
            WHERE stock_code = '000003.SZ'
            """
        ).fetchone()[0]
        universe = connection.execute(
            """
            SELECT in_effective_date, out_effective_date
            FROM universe_members
            WHERE stock_code = '000003.SZ'
            """
        ).fetchone()
        st = connection.execute(
            """
            SELECT in_effective_date, out_effective_date
            FROM st_status
            WHERE stock_code = '000002.SZ'
            """
        ).fetchone()
        industry = connection.execute(
            """
            SELECT in_effective_date, out_effective_date
            FROM industry_classifications
            WHERE stock_code = '000005.SZ'
              AND industry_l2 = 'Software'
            """
        ).fetchone()
    finally:
        connection.close()

    assert delist_effective == date(2026, 3, 3)
    assert universe == (date(2026, 1, 6), date(2026, 3, 3))
    assert st == (date(2026, 1, 21), date(2026, 2, 17))
    assert industry == (date(2026, 1, 6), date(2026, 2, 13))


def test_ingest_local_is_idempotent_without_row_growth(tmp_path: Path) -> None:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)

    first_summary = ingest_local(input_dir=input_dir, db_path=db_path)
    first_counts = _table_counts(db_path)
    second_summary = ingest_local(input_dir=input_dir, db_path=db_path)
    second_counts = _table_counts(db_path)

    assert second_summary == first_summary
    assert second_counts == first_counts


def test_cli_ingest_local_succeeds_and_builds_fixtures(tmp_path: Path) -> None:
    input_dir = tmp_path / "generated"
    db_path = tmp_path / "cli.duckdb"

    result = subprocess.run(
        [
            "ashare",
            "ingest-local",
            "--input-dir",
            str(input_dir),
            "--db-path",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (input_dir / "daily_prices.csv").is_file()
    assert db_path.is_file()
    assert "Local fixture ingest completed." in result.stdout
    assert "risk_events: 4" in result.stdout


def test_cli_help_lists_phase0_and_phase1_commands() -> None:
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
        "scan",
        "backtest",
        "report",
        "stock-report",
        "db-init",
        "ingest-local",
        "as-of",
    ]:
        assert command in result.stdout
