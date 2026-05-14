from pathlib import Path
import subprocess

import duckdb

from ashare.storage.db import default_schema_path, init_db


REQUIRED_TABLES = {
    "trading_calendar",
    "securities",
    "daily_prices",
    "st_status",
    "risk_events",
    "factor_values",
    "research_runs",
}


def _tables(db_path: Path) -> set[str]:
    connection = duckdb.connect(str(db_path))
    try:
        return {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    finally:
        connection.close()


def test_init_db_creates_duckdb_file_and_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "test.duckdb"

    init_db(db_path)

    assert db_path.is_file()
    assert REQUIRED_TABLES.issubset(_tables(db_path))


def test_schema_sql_executes_directly_in_duckdb() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(default_schema_path().read_text(encoding="utf-8"))
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    finally:
        connection.close()

    assert REQUIRED_TABLES.issubset(tables)


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"

    init_db(db_path)
    init_db(db_path)

    assert REQUIRED_TABLES.issubset(_tables(db_path))


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
