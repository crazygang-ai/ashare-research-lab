"""Local CSV fixture ingestion into DuckDB."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from ashare.pit.effective_date import calculate_effective_date
from ashare.storage.db import connect, init_db


TABLE_ORDER = (
    "trading_calendar",
    "securities",
    "industry_classifications",
    "universe_members",
    "daily_prices",
    "st_status",
    "valuation_daily",
    "fundamental_reports",
    "announcements",
    "risk_events",
)

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "trading_calendar": ("trade_date", "is_open", "prev_trade_date", "next_trade_date"),
    "securities": (
        "stock_code",
        "stock_name",
        "exchange",
        "list_date",
        "delist_date",
        "delist_publish_time",
        "delist_effective_date",
    ),
    "industry_classifications": (
        "stock_code",
        "industry_standard",
        "industry_l1",
        "industry_l2",
        "in_date",
        "out_date",
        "in_publish_time",
        "in_effective_date",
        "out_publish_time",
        "out_effective_date",
        "version",
        "source",
    ),
    "universe_members": (
        "index_code",
        "stock_code",
        "in_date",
        "out_date",
        "in_publish_time",
        "in_effective_date",
        "out_publish_time",
        "out_effective_date",
        "source",
    ),
    "daily_prices": (
        "stock_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
        "is_suspended",
        "limit_up",
        "limit_down",
    ),
    "st_status": (
        "stock_code",
        "st_type",
        "in_date",
        "out_date",
        "in_publish_time",
        "in_effective_date",
        "out_publish_time",
        "out_effective_date",
        "source",
    ),
    "valuation_daily": (
        "stock_code",
        "trade_date",
        "pe_ttm",
        "pb",
        "ps",
        "dividend_yield",
        "total_mv",
        "float_mv",
        "source",
    ),
    "fundamental_reports": (
        "stock_code",
        "report_period",
        "publish_time",
        "effective_date",
        "revenue",
        "net_profit",
        "roe",
        "gross_margin",
        "operating_cashflow",
        "debt_ratio",
        "goodwill",
        "total_equity",
        "accounts_receivable",
        "inventory",
        "source",
    ),
    "announcements": (
        "announcement_id",
        "source",
        "source_tag",
        "stock_code",
        "title",
        "announcement_type",
        "publish_time",
        "effective_date",
        "url",
        "raw_path",
        "text_hash",
    ),
    "risk_events": (
        "event_id",
        "stock_code",
        "event_type",
        "event_date",
        "publish_time",
        "effective_date",
        "payload_json",
        "source",
    ),
}

PUBLISH_TABLES = {"fundamental_reports", "announcements", "risk_events"}
VISIBILITY_TABLES = {
    "securities",
    "industry_classifications",
    "universe_members",
    "st_status",
}
OPTIONAL_INPUT_COLUMNS: dict[str, set[str]] = {
    "securities": {"delist_publish_time", "delist_effective_date"},
    "industry_classifications": {
        "in_publish_time",
        "in_effective_date",
        "out_publish_time",
        "out_effective_date",
    },
    "universe_members": {
        "in_publish_time",
        "in_effective_date",
        "out_publish_time",
        "out_effective_date",
    },
    "st_status": {
        "in_publish_time",
        "in_effective_date",
        "out_publish_time",
        "out_effective_date",
    },
    "fundamental_reports": {"effective_date"},
    "announcements": {"source", "source_tag", "effective_date"},
    "risk_events": {"effective_date"},
}
IGNORED_INPUT_COLUMNS: dict[str, set[str]] = {
    "announcements": {"body_path", "body_text"},
}
EFFECTIVE_DATE_RULES: dict[str, tuple[tuple[str, str, str | None], ...]] = {
    "securities": (("delist_effective_date", "delist_publish_time", "delist_date"),),
    "industry_classifications": (
        ("in_effective_date", "in_publish_time", "in_date"),
        ("out_effective_date", "out_publish_time", "out_date"),
    ),
    "universe_members": (
        ("in_effective_date", "in_publish_time", "in_date"),
        ("out_effective_date", "out_publish_time", "out_date"),
    ),
    "st_status": (
        ("in_effective_date", "in_publish_time", "in_date"),
        ("out_effective_date", "out_publish_time", "out_date"),
    ),
    "fundamental_reports": (("effective_date", "publish_time", None),),
    "announcements": (("effective_date", "publish_time", None),),
    "risk_events": (("effective_date", "publish_time", None),),
}
DATE_COLUMNS = {
    "trade_date",
    "prev_trade_date",
    "next_trade_date",
    "list_date",
    "delist_date",
    "delist_effective_date",
    "in_date",
    "out_date",
    "in_effective_date",
    "out_effective_date",
    "report_period",
    "effective_date",
    "event_date",
}
TIMESTAMP_COLUMNS = {
    "publish_time",
    "delist_publish_time",
    "in_publish_time",
    "out_publish_time",
}
BOOL_COLUMNS = {"is_open", "is_suspended"}
INT_COLUMNS = {"volume"}
FLOAT_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "amount",
    "adj_factor",
    "limit_up",
    "limit_down",
    "revenue",
    "net_profit",
    "roe",
    "gross_margin",
    "operating_cashflow",
    "debt_ratio",
    "goodwill",
    "total_equity",
    "accounts_receivable",
    "inventory",
    "pe_ttm",
    "pb",
    "ps",
    "dividend_yield",
    "total_mv",
    "float_mv",
}


def ingest_local(input_dir: str | Path, db_path: str | Path) -> dict[str, int]:
    """Load local fixture CSVs into DuckDB.

    This clears and rewrites the target tables, so it is only for local fixture
    and development testing. It does not fetch real data or perform upserts.
    """
    input_dir = Path(input_dir)
    _validate_input_files(input_dir)

    init_db(db_path)
    connection = connect(db_path)
    summary: dict[str, int] = {}
    try:
        _load_json_extension_if_available(connection)
        connection.execute("BEGIN TRANSACTION")
        for table in TABLE_ORDER:
            needs_trading_days = table in PUBLISH_TABLES or table in VISIBILITY_TABLES
            trading_days = _open_trading_days(connection) if needs_trading_days else None
            rows = _read_csv_rows(input_dir / f"{table}.csv", table, trading_days)
            connection.execute(f"DELETE FROM {table}")
            _insert_rows(connection, table, rows)
            summary[table] = len(rows)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    return summary


def _validate_input_files(input_dir: Path) -> None:
    missing = [f"{table}.csv" for table in TABLE_ORDER if not (input_dir / f"{table}.csv").is_file()]
    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(f"Missing fixture CSV file(s) in {input_dir}: {joined}")


def _read_csv_rows(
    csv_path: Path,
    table: str,
    trading_days: list[date] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        _validate_header(table, reader.fieldnames)
        for raw_row in reader:
            rows.append(_convert_row(table, raw_row, trading_days))
    return rows


def _validate_header(table: str, fieldnames: list[str] | None) -> None:
    if fieldnames is None:
        raise ValueError(f"{table}.csv is empty.")

    expected_columns = set(TABLE_COLUMNS[table])
    optional_columns = OPTIONAL_INPUT_COLUMNS.get(table, set())
    ignored_columns = IGNORED_INPUT_COLUMNS.get(table, set())
    required_columns = expected_columns - optional_columns
    actual_columns = set(fieldnames)

    missing = sorted(required_columns - actual_columns)
    unexpected = sorted(actual_columns - expected_columns - ignored_columns)
    if missing or unexpected:
        raise ValueError(
            f"{table}.csv columns are invalid; missing {missing}, unexpected {unexpected}."
        )


def _convert_row(
    table: str,
    raw_row: dict[str, str],
    trading_days: list[date] | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for column in TABLE_COLUMNS[table]:
        row[column] = _convert_value(column, raw_row.get(column, ""))

    _fill_effective_dates(table, row, trading_days)
    return row


def _fill_effective_dates(
    table: str,
    row: dict[str, Any],
    trading_days: list[date] | None,
) -> None:
    for effective_column, publish_column, fallback_column in EFFECTIVE_DATE_RULES.get(table, ()):
        if row[effective_column] is not None:
            continue
        if row[publish_column] is not None:
            if trading_days is None:
                raise ValueError(f"Trading calendar must be loaded before {table}.")
            row[effective_column] = calculate_effective_date(row[publish_column], trading_days)
        elif fallback_column is not None:
            row[effective_column] = row[fallback_column]


def _convert_value(column: str, value: str) -> Any:
    if value == "":
        return None
    if column in DATE_COLUMNS:
        return date.fromisoformat(value)
    if column in TIMESTAMP_COLUMNS:
        return datetime.fromisoformat(value)
    if column in BOOL_COLUMNS:
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if column in INT_COLUMNS:
        return int(value)
    if column in FLOAT_COLUMNS:
        return float(value)
    return value


def _insert_rows(connection: duckdb.DuckDBPyConnection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    columns = TABLE_COLUMNS[table]
    column_sql = ", ".join(columns)
    placeholders = [
        "CAST(? AS JSON)" if table == "risk_events" and column == "payload_json" else "?"
        for column in columns
    ]
    values_sql = ", ".join(placeholders)
    sql = f"INSERT INTO {table} ({column_sql}) VALUES ({values_sql})"
    values = [tuple(row[column] for column in columns) for row in rows]
    connection.executemany(sql, values)


def _open_trading_days(connection: duckdb.DuckDBPyConnection) -> list[date]:
    rows = connection.execute(
        "SELECT trade_date FROM trading_calendar WHERE is_open = true ORDER BY trade_date"
    ).fetchall()
    return [row[0] for row in rows]


def _load_json_extension_if_available(connection: duckdb.DuckDBPyConnection) -> None:
    try:
        connection.execute("LOAD json;")
    except duckdb.Error:
        try:
            connection.execute("INSTALL json;")
            connection.execute("LOAD json;")
        except duckdb.Error:
            pass
