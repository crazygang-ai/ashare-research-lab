"""DuckDB connection and schema initialization helpers."""

from pathlib import Path

import duckdb


CURRENT_SCHEMA_VERSION = 1
CURRENT_SCHEMA_DESCRIPTION = "phase 1a-3.5 pit interval visibility"

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
    """Initialize a DuckDB database from the bundled schema."""
    resolved_schema_path = Path(schema_path) if schema_path is not None else default_schema_path()
    schema_sql = resolved_schema_path.read_text(encoding="utf-8")

    connection = connect(db_path)
    try:
        try:
            connection.execute(schema_sql)
        except duckdb.Error as exc:
            if "JSON" not in str(exc).upper():
                raise
            connection.execute("INSTALL json;")
            connection.execute("LOAD json;")
            connection.execute(schema_sql)
        ensure_schema_columns(connection)
    finally:
        connection.close()


def ensure_schema_columns(connection: duckdb.DuckDBPyConnection) -> None:
    """Add Phase 1a-3.5 schema columns to older DuckDB files without data loss."""
    for table_name, columns in REQUIRED_COLUMNS.items():
        existing_columns = _existing_columns(connection, table_name)
        for column_name, column_type in columns:
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )
                existing_columns.add(column_name)

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER,
            applied_at TIMESTAMP,
            description VARCHAR
        )
        """
    )
    connection.execute(
        """
        INSERT INTO schema_version (version, applied_at, description)
        SELECT ?, CURRENT_TIMESTAMP, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM schema_version WHERE version = ?
        )
        """,
        [CURRENT_SCHEMA_VERSION, CURRENT_SCHEMA_DESCRIPTION, CURRENT_SCHEMA_VERSION],
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
    return {row[0] for row in rows}
