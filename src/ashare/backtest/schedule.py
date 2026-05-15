"""Monthly rebalance schedule helpers for Phase 1b backtests."""

from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from ashare.pit.asof import DateLike, parse_as_of_date


def get_month_end_signal_dates(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
) -> list[date]:
    """Return the final open trading date in each month within the requested interval."""
    start = parse_as_of_date(start_date)
    end = parse_as_of_date(end_date)
    if start > end:
        raise ValueError(f"start_date {start.isoformat()} is after end_date {end.isoformat()}.")

    frame = connection.execute(
        """
        SELECT trade_date
        FROM trading_calendar
        WHERE trade_date BETWEEN ? AND ?
          AND is_open = true
        ORDER BY trade_date
        """,
        [start, end],
    ).df()
    if frame.empty:
        return []

    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame["month"] = pd.to_datetime(frame["trade_date"]).dt.to_period("M")
    result = frame.groupby("month", sort=True)["trade_date"].max().tolist()
    return [_to_date(value) for value in result]


def get_execution_date(
    connection: duckdb.DuckDBPyConnection,
    signal_date: DateLike,
    end_date: DateLike,
) -> date | None:
    """Return the next open trading day strictly after ``signal_date`` and within ``end_date``."""
    signal = parse_as_of_date(signal_date)
    end = parse_as_of_date(end_date)
    row = connection.execute(
        """
        SELECT trade_date
        FROM trading_calendar
        WHERE trade_date > ?
          AND trade_date <= ?
          AND is_open = true
        ORDER BY trade_date
        LIMIT 1
        """,
        [signal, end],
    ).fetchone()
    if row is None:
        return None
    return _to_date(row[0])


def open_trading_dates_between(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
) -> list[date]:
    """Return all open trading dates in the inclusive interval."""
    start = parse_as_of_date(start_date)
    end = parse_as_of_date(end_date)
    if start > end:
        raise ValueError(f"start_date {start.isoformat()} is after end_date {end.isoformat()}.")
    rows = connection.execute(
        """
        SELECT trade_date
        FROM trading_calendar
        WHERE trade_date BETWEEN ? AND ?
          AND is_open = true
        ORDER BY trade_date
        """,
        [start, end],
    ).fetchall()
    return [_to_date(row[0]) for row in rows]


def next_open_trading_date(
    connection: duckdb.DuckDBPyConnection,
    trade_date: DateLike,
) -> date | None:
    """Return the next open trading date after ``trade_date`` without an end bound."""
    parsed = parse_as_of_date(trade_date)
    row = connection.execute(
        """
        SELECT trade_date
        FROM trading_calendar
        WHERE trade_date > ?
          AND is_open = true
        ORDER BY trade_date
        LIMIT 1
        """,
        [parsed],
    ).fetchone()
    if row is None:
        return None
    return _to_date(row[0])


def _to_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()
