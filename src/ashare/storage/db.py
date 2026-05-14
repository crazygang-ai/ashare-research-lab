"""DuckDB connection and schema initialization helpers."""

from pathlib import Path

import duckdb


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
    finally:
        connection.close()
