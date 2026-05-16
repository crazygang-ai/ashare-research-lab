"""Helpers for explicit source isolation in shared DuckDB files."""

from __future__ import annotations

from collections.abc import Sequence

import duckdb


CORE_SOURCE_TABLES = ("trading_calendar", "securities", "daily_prices", "valuation_daily")


def resolve_data_source(
    connection: duckdb.DuckDBPyConnection,
    requested_source: str | None,
    tables: Sequence[str] = CORE_SOURCE_TABLES,
) -> str | None:
    """Return the source to use, failing when a shared DB contains ambiguous sources."""
    if requested_source is not None and str(requested_source).strip():
        return str(requested_source).strip()

    sources = available_data_sources(connection, tables=tables)
    explicit_sources = tuple(source for source in sources if source != "legacy")
    if len(explicit_sources) == 1:
        return explicit_sources[0]
    if len(explicit_sources) > 1:
        raise ValueError(
            "Multiple data sources are present in this DuckDB file; pass --data-source "
            "explicitly. Available sources: " + ", ".join(explicit_sources)
        )
    return sources[0] if sources else None


def available_data_sources(
    connection: duckdb.DuckDBPyConnection,
    tables: Sequence[str] = CORE_SOURCE_TABLES,
) -> tuple[str, ...]:
    """Return distinct non-null source values observed in source-isolated tables."""
    values: set[str] = set()
    for table_name in tables:
        if not _table_has_column(connection, table_name, "source"):
            continue
        rows = connection.execute(
            f"""
            SELECT DISTINCT source
            FROM {table_name}
            WHERE source IS NOT NULL
              AND TRIM(CAST(source AS VARCHAR)) <> ''
            ORDER BY source
            """
        ).fetchall()
        values.update(str(row[0]) for row in rows)
    return tuple(sorted(values))


def _table_has_column(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    column_name: str,
) -> bool:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_name = ?
          AND column_name = ?
        """,
        [table_name, column_name],
    ).fetchone()
    return bool(row and int(row[0]) > 0)
