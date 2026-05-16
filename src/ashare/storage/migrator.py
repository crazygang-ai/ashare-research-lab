"""Repo-local DuckDB schema migration runner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


CURRENT_SCHEMA_VERSION = 4
CURRENT_SCHEMA_DESCRIPTION = "phase 8 source isolation, factor keys, and universe snapshots"

MIGRATION_DESCRIPTIONS = {
    1: "initial research schema",
    2: "PIT effective-date compatibility columns",
    3: "run audit and artifact index",
    4: "source isolation, factor value keys, and universe snapshots",
}


@dataclass(frozen=True)
class Migration:
    version: int
    path: Path
    description: str


def default_migrations_dir() -> Path:
    """Return the bundled migration directory."""
    return Path(__file__).with_name("migrations")


def load_migrations(migrations_dir: str | Path | None = None) -> tuple[Migration, ...]:
    """Load SQL migrations sorted by numeric prefix."""
    resolved = Path(migrations_dir) if migrations_dir is not None else default_migrations_dir()
    migrations: list[Migration] = []
    for path in sorted(resolved.glob("*.sql")):
        prefix = path.name.split("_", 1)[0]
        try:
            version = int(prefix)
        except ValueError as exc:
            raise ValueError(f"Migration file must start with a numeric prefix: {path.name}") from exc
        migrations.append(
            Migration(
                version=version,
                path=path,
                description=MIGRATION_DESCRIPTIONS.get(version, path.stem),
            )
        )
    if not migrations:
        raise FileNotFoundError(f"No DuckDB migrations found in {resolved}")
    expected = list(range(1, max(m.version for m in migrations) + 1))
    actual = [m.version for m in migrations]
    if actual != expected:
        raise ValueError(f"Migration versions must be continuous from 1: {actual}")
    return tuple(migrations)


def apply_migrations(
    connection: duckdb.DuckDBPyConnection,
    migrations_dir: str | Path | None = None,
) -> None:
    """Apply all bundled migrations idempotently and record schema versions."""
    _ensure_schema_version_table(connection)
    for migration in load_migrations(migrations_dir):
        if migration.version == 4:
            _preflight_factor_value_keys(connection)
        sql = migration.path.read_text(encoding="utf-8")
        _execute_sql(connection, sql)
        _record_migration(connection, migration)
    _assert_schema_versions_continuous(connection)


def _execute_sql(connection: duckdb.DuckDBPyConnection, sql: str) -> None:
    try:
        connection.execute(sql)
    except duckdb.Error as exc:
        if "JSON" not in str(exc).upper():
            raise
        connection.execute("INSTALL json;")
        connection.execute("LOAD json;")
        connection.execute(sql)


def _ensure_schema_version_table(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER,
            applied_at TIMESTAMP,
            description VARCHAR
        )
        """
    )


def _record_migration(connection: duckdb.DuckDBPyConnection, migration: Migration) -> None:
    connection.execute(
        """
        INSERT INTO schema_version (version, applied_at, description)
        SELECT ?, CURRENT_TIMESTAMP, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM schema_version WHERE version = ?
        )
        """,
        [migration.version, migration.description, migration.version],
    )


def _assert_schema_versions_continuous(connection: duckdb.DuckDBPyConnection) -> None:
    rows = connection.execute(
        "SELECT DISTINCT version FROM schema_version ORDER BY version"
    ).fetchall()
    versions = [int(row[0]) for row in rows]
    expected = list(range(1, CURRENT_SCHEMA_VERSION + 1))
    missing = [version for version in expected if version not in versions]
    if missing:
        raise RuntimeError(
            "schema_version is missing applied migration version(s): "
            + ", ".join(str(version) for version in missing)
        )


def _preflight_factor_value_keys(connection: duckdb.DuckDBPyConnection) -> None:
    columns = _existing_columns(connection, "factor_values")
    required = {"source_run_id", "stock_code", "trade_date", "as_of_date", "factor_name"}
    if not required.issubset(columns):
        return
    duplicates = connection.execute(
        """
        SELECT
            source_run_id,
            stock_code,
            trade_date,
            as_of_date,
            factor_name,
            COUNT(*) AS row_count
        FROM factor_values
        GROUP BY source_run_id, stock_code, trade_date, as_of_date, factor_name
        HAVING COUNT(*) > 1
        ORDER BY source_run_id, stock_code, trade_date, as_of_date, factor_name
        LIMIT 5
        """
    ).fetchall()
    if not duplicates:
        return
    samples = [
        f"({row[0]}, {row[1]}, {row[2]}, {row[3]}, {row[4]}, count={row[5]})"
        for row in duplicates
    ]
    raise ValueError(
        "Cannot apply schema migration 0004 because factor_values contains duplicate "
        "keys for (source_run_id, stock_code, trade_date, as_of_date, factor_name). "
        "Delete or deduplicate those rows, or rerun calculate-factors with "
        "--overwrite-run for the affected source_run_id. Duplicate sample: "
        + "; ".join(samples)
    )


def _existing_columns(connection: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchall()
    return {str(row[0]) for row in rows}
