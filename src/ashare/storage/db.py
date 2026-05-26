"""DuckDB connection and schema initialization helpers."""

from pathlib import Path

import duckdb

from ashare.storage.migrator import (
    CURRENT_SCHEMA_DESCRIPTION,
    CURRENT_SCHEMA_VERSION,
    apply_migrations,
)

__all__ = [
    "CURRENT_SCHEMA_DESCRIPTION",
    "CURRENT_SCHEMA_VERSION",
    "connect",
    "default_schema_path",
    "ensure_schema_columns",
    "init_db",
]

REQUIRED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "securities": (
        ("delist_publish_time", "TIMESTAMP"),
        ("delist_effective_date", "DATE"),
    ),
    "industry_classifications": (
        ("in_publish_time", "TIMESTAMP"),
        ("in_effective_date", "DATE"),
        ("out_publish_time", "TIMESTAMP"),
        ("out_effective_date", "DATE"),
    ),
    "universe_members": (
        ("in_publish_time", "TIMESTAMP"),
        ("in_effective_date", "DATE"),
        ("out_publish_time", "TIMESTAMP"),
        ("out_effective_date", "DATE"),
    ),
    "st_status": (
        ("in_publish_time", "TIMESTAMP"),
        ("in_effective_date", "DATE"),
        ("out_publish_time", "TIMESTAMP"),
        ("out_effective_date", "DATE"),
    ),
    "announcements": (
        ("source", "VARCHAR"),
        ("source_tag", "VARCHAR"),
    ),
}


def connect(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    """Connect to a DuckDB database, creating the parent directory if needed."""
    path = Path(db_path)

    if str(db_path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    return duckdb.connect(str(path))


def default_schema_path() -> Path:
    """Return the bundled DuckDB schema path."""
    return Path(__file__).with_name("schema.sql")


def init_db(db_path: str | Path, schema_path: str | Path | None = None) -> None:
    """Initialize or upgrade a DuckDB database with repo-local migrations."""
    connection = connect(db_path)
    try:
        if schema_path is not None:
            schema_sql = Path(schema_path).read_text(encoding="utf-8")
            try:
                connection.execute(schema_sql)
            except duckdb.Error as exc:
                if "JSON" not in str(exc).upper():
                    raise
                connection.execute("INSTALL json;")
                connection.execute("LOAD json;")
                connection.execute(schema_sql)
        apply_migrations(connection)
    finally:
        connection.close()


def ensure_schema_columns(connection: duckdb.DuckDBPyConnection) -> None:
    """Upgrade older DuckDB files without data loss."""
    apply_migrations(connection)


def _existing_columns(connection: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchall()
    return {row[0] for row in rows}
