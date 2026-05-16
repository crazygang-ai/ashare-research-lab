from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from ashare.storage.db import init_db
from ashare.storage.migrator import CURRENT_SCHEMA_VERSION


def _schema_versions(db_path: Path) -> list[int]:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = connection.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        return [int(row[0]) for row in rows]
    finally:
        connection.close()


def test_init_db_applies_continuous_migration_versions(tmp_path: Path) -> None:
    db_path = tmp_path / "new.duckdb"

    init_db(db_path)
    init_db(db_path)

    assert _schema_versions(db_path) == list(range(1, CURRENT_SCHEMA_VERSION + 1))


def test_legacy_db_gets_source_columns_and_universe_table(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.duckdb"
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            CREATE TABLE daily_prices (
                stock_code VARCHAR,
                trade_date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                amount DOUBLE,
                adj_factor DOUBLE,
                is_suspended BOOLEAN,
                limit_up DOUBLE,
                limit_down DOUBLE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO daily_prices
            VALUES ('000001.SZ', DATE '2026-01-01', 1, 1, 1, 1, 1, 1, 1, false, 1, 1)
            """
        )
        connection.execute(
            """
            CREATE TABLE factor_values (
                stock_code VARCHAR,
                trade_date DATE,
                factor_name VARCHAR,
                factor_value DOUBLE,
                as_of_date DATE,
                source_run_id VARCHAR
            )
            """
        )
    finally:
        connection.close()

    init_db(db_path)

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        source = connection.execute("SELECT DISTINCT source FROM daily_prices").fetchone()[0]
        universe_exists = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = 'factor_run_universe'
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert source == "legacy"
    assert universe_exists == 1


def test_migration_fails_fast_on_legacy_factor_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicate.duckdb"
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            CREATE TABLE factor_values (
                stock_code VARCHAR,
                trade_date DATE,
                factor_name VARCHAR,
                factor_value DOUBLE,
                as_of_date DATE,
                source_run_id VARCHAR
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO factor_values
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("000001.SZ", date(2026, 1, 1), "return_20d", 1.0, date(2026, 1, 1), "run"),
                ("000001.SZ", date(2026, 1, 1), "return_20d", 2.0, date(2026, 1, 1), "run"),
            ],
        )
    finally:
        connection.close()

    with pytest.raises(ValueError, match="factor_values contains duplicate keys"):
        init_db(db_path)
