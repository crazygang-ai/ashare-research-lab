import inspect
from datetime import date
from pathlib import Path
import subprocess

import duckdb

from ashare.storage import db as db_module
from ashare.storage.db import default_schema_path, ensure_schema_columns, init_db


REQUIRED_TABLES = {
    "trading_calendar",
    "securities",
    "daily_prices",
    "st_status",
    "risk_events",
    "factor_values",
    "research_runs",
    "schema_version",
}


def _tables(db_path: Path) -> set[str]:
    connection = duckdb.connect(str(db_path))
    try:
        return {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    finally:
        connection.close()


def _columns(db_path: Path, table: str) -> set[str]:
    connection = duckdb.connect(str(db_path))
    try:
        return {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = ?
                """,
                [table],
            ).fetchall()
        }
    finally:
        connection.close()


def _schema_version_rows(db_path: Path) -> list[tuple[int, str]]:
    connection = duckdb.connect(str(db_path))
    try:
        return connection.execute(
            "SELECT version, description FROM schema_version ORDER BY version"
        ).fetchall()
    finally:
        connection.close()


def test_init_db_creates_duckdb_file_and_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "test.duckdb"

    init_db(db_path)

    assert db_path.is_file()
    assert REQUIRED_TABLES.issubset(_tables(db_path))
    assert _schema_version_rows(db_path) == [(1, "phase 1a-3.5 pit interval visibility")]


def test_schema_sql_executes_directly_in_duckdb() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(default_schema_path().read_text(encoding="utf-8"))
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        securities_columns = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'securities'
                """
            ).fetchall()
        }
    finally:
        connection.close()

    assert REQUIRED_TABLES.issubset(tables)
    assert {"delist_publish_time", "delist_effective_date"}.issubset(securities_columns)


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"

    init_db(db_path)
    init_db(db_path)

    assert REQUIRED_TABLES.issubset(_tables(db_path))
    assert _schema_version_rows(db_path) == [(1, "phase 1a-3.5 pit interval visibility")]


def test_init_db_backfills_phase_1a_3_5_columns_without_losing_old_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.duckdb"
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            CREATE TABLE securities (
                stock_code VARCHAR,
                stock_name VARCHAR,
                exchange VARCHAR,
                list_date DATE,
                delist_date DATE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO securities
            VALUES ('000003.SZ', 'Delist Sample', 'SZSE', DATE '2020-01-01', DATE '2026-03-06')
            """
        )
        connection.execute(
            """
            CREATE TABLE universe_members (
                index_code VARCHAR,
                stock_code VARCHAR,
                in_date DATE,
                out_date DATE,
                source VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE industry_classifications (
                stock_code VARCHAR,
                industry_standard VARCHAR,
                industry_l1 VARCHAR,
                industry_l2 VARCHAR,
                in_date DATE,
                out_date DATE,
                version VARCHAR,
                source VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE st_status (
                stock_code VARCHAR,
                st_type VARCHAR,
                in_date DATE,
                out_date DATE,
                source VARCHAR
            )
            """
        )
    finally:
        connection.close()

    init_db(db_path)

    assert {"delist_publish_time", "delist_effective_date"}.issubset(
        _columns(db_path, "securities")
    )
    for table in ["universe_members", "industry_classifications", "st_status"]:
        assert {
            "in_publish_time",
            "in_effective_date",
            "out_publish_time",
            "out_effective_date",
        }.issubset(_columns(db_path, table))

    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute(
            """
            SELECT stock_code, stock_name, delist_date, delist_effective_date
            FROM securities
            WHERE stock_code = '000003.SZ'
            """
        ).fetchone()
    finally:
        connection.close()

    assert row == ("000003.SZ", "Delist Sample", date(2026, 3, 6), None)


def test_ensure_schema_columns_is_directly_callable_and_uses_information_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "direct.duckdb"
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(default_schema_path().read_text(encoding="utf-8"))
        connection.execute("ALTER TABLE securities DROP COLUMN delist_publish_time")
        ensure_schema_columns(connection)
        columns = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'securities'
                """
            ).fetchall()
        }
    finally:
        connection.close()

    assert "delist_publish_time" in columns
    assert "information_schema.columns" in inspect.getsource(db_module)


def test_cli_db_init_succeeds(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"

    result = subprocess.run(
        ["ashare", "db-init", "--db-path", str(db_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert db_path.is_file()
    assert "Initialized DuckDB database" in result.stdout
    assert "Schema path:" in result.stdout
