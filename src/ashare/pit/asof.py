"""Point-in-time as-of queries for local DuckDB research data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


DateLike = str | date | datetime | pd.Timestamp


@dataclass(frozen=True)
class AsOfSnapshot:
    """Visible research data at one explicit point in time."""

    as_of_date: date
    daily_prices: pd.DataFrame
    valuation_daily: pd.DataFrame
    universe_members: pd.DataFrame
    securities: pd.DataFrame
    st_status: pd.DataFrame
    industry_classifications: pd.DataFrame
    fundamental_reports: pd.DataFrame
    announcements: pd.DataFrame
    risk_events: pd.DataFrame


def parse_as_of_date(value: DateLike) -> date:
    """Parse an explicit as-of date without defaulting to the current date."""
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)

    raise TypeError(f"Unsupported as_of_date type: {type(value).__name__}")


def query_daily_prices_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
    source: str | None = None,
) -> pd.DataFrame:
    """Return prices visible as of ``as_of_date`` using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            stock_code,
            trade_date,
            open,
            high,
            low,
            close,
            volume,
            amount,
            adj_factor,
            is_suspended,
            limit_up,
            limit_down,
            source
        FROM daily_prices
        WHERE trade_date <= ?
    """
    params: list[Any] = [parsed_date]
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY stock_code, trade_date"

    return connection.execute(sql, params).df()


def query_valuation_daily_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
    source: str | None = None,
) -> pd.DataFrame:
    """Return valuations visible as of ``as_of_date`` using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            stock_code,
            trade_date,
            pe_ttm,
            pb,
            ps,
            dividend_yield,
            total_mv,
            float_mv,
            source
        FROM valuation_daily
        WHERE trade_date <= ?
    """
    params: list[Any] = [parsed_date]
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY stock_code, trade_date"

    return connection.execute(sql, params).df()


def query_universe_members_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    index_code: str | None = None,
    stock_code: str | None = None,
    source_tag: str | None = None,
    allow_current_snapshot: bool = True,
) -> pd.DataFrame:
    """Return active universe members using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            index_code,
            stock_code,
            in_date,
            CASE
                WHEN out_date IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_date
                ELSE NULL
            END AS out_date,
            in_publish_time,
            in_effective_date,
            CASE
                WHEN out_publish_time IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_publish_time
                ELSE NULL
            END AS out_publish_time,
            CASE
                WHEN out_effective_date IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_effective_date
                ELSE NULL
            END AS out_effective_date,
            source,
            source_tag,
            universe_kind
        FROM universe_members
        WHERE in_date <= ?
          AND COALESCE(in_effective_date, in_date) <= ?
          AND (
              out_date IS NULL
              OR ? < out_date
              OR COALESCE(out_effective_date, out_date) > ?
          )
    """
    params: list[Any] = [
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
    ]
    if index_code is not None:
        sql += " AND index_code = ?"
        params.append(index_code)
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    if source_tag is not None:
        sql += " AND COALESCE(source_tag, source) = ?"
        params.append(source_tag)
    if not allow_current_snapshot:
        sql += " AND COALESCE(universe_kind, 'unknown') = 'historical_pit'"
    sql += " ORDER BY index_code, stock_code, in_date"

    return connection.execute(sql, params).df()


def query_securities_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    include_delisted: bool = False,
    stock_code: str | None = None,
    source: str | None = None,
) -> pd.DataFrame:
    """Return listed securities as of ``as_of_date`` using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            stock_code,
            stock_name,
            exchange,
            list_date,
            CASE
                WHEN delist_date IS NOT NULL
                 AND COALESCE(delist_effective_date, delist_date) <= ?
                THEN delist_date
                ELSE NULL
            END AS delist_date,
            CASE
                WHEN delist_publish_time IS NOT NULL
                 AND COALESCE(delist_effective_date, delist_date) <= ?
                THEN delist_publish_time
                ELSE NULL
            END AS delist_publish_time,
            CASE
                WHEN delist_effective_date IS NOT NULL
                 AND COALESCE(delist_effective_date, delist_date) <= ?
                THEN delist_effective_date
                ELSE NULL
            END AS delist_effective_date,
            (
                delist_date IS NOT NULL
                AND delist_date <= ?
                AND COALESCE(delist_effective_date, delist_date) <= ?
            ) AS is_delisted_as_of
            ,
            source
        FROM securities
        WHERE list_date <= ?
    """
    params: list[Any] = [
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
    ]
    if not include_delisted:
        sql += """
          AND NOT (
              delist_date IS NOT NULL
              AND delist_date <= ?
              AND COALESCE(delist_effective_date, delist_date) <= ?
          )
        """
        params.append(parsed_date)
        params.append(parsed_date)
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY stock_code"

    return connection.execute(sql, params).df()


def query_st_status_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
) -> pd.DataFrame:
    """Return active ST status rows using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            stock_code,
            st_type,
            in_date,
            CASE
                WHEN out_date IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_date
                ELSE NULL
            END AS out_date,
            in_publish_time,
            in_effective_date,
            CASE
                WHEN out_publish_time IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_publish_time
                ELSE NULL
            END AS out_publish_time,
            CASE
                WHEN out_effective_date IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_effective_date
                ELSE NULL
            END AS out_effective_date,
            source
        FROM st_status
        WHERE in_date <= ?
          AND COALESCE(in_effective_date, in_date) <= ?
          AND (
              out_date IS NULL
              OR ? < out_date
              OR COALESCE(out_effective_date, out_date) > ?
          )
    """
    params: list[Any] = [
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
    ]
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    sql += " ORDER BY stock_code, in_date, st_type"

    return connection.execute(sql, params).df()


def query_industry_classifications_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    industry_standard: str | None = None,
    version: str | None = None,
    stock_code: str | None = None,
) -> pd.DataFrame:
    """Return active industry rows using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            stock_code,
            industry_standard,
            industry_l1,
            industry_l2,
            in_date,
            CASE
                WHEN out_date IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_date
                ELSE NULL
            END AS out_date,
            in_publish_time,
            in_effective_date,
            CASE
                WHEN out_publish_time IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_publish_time
                ELSE NULL
            END AS out_publish_time,
            CASE
                WHEN out_effective_date IS NOT NULL
                 AND COALESCE(out_effective_date, out_date) <= ?
                THEN out_effective_date
                ELSE NULL
            END AS out_effective_date,
            version,
            source
        FROM industry_classifications
        WHERE in_date <= ?
          AND COALESCE(in_effective_date, in_date) <= ?
          AND (
              out_date IS NULL
              OR ? < out_date
              OR COALESCE(out_effective_date, out_date) > ?
          )
    """
    params: list[Any] = [
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
        parsed_date,
    ]
    if industry_standard is not None:
        sql += " AND industry_standard = ?"
        params.append(industry_standard)
    if version is not None:
        sql += " AND version = ?"
        params.append(version)
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    sql += " ORDER BY stock_code, industry_standard, version, in_date"

    return connection.execute(sql, params).df()


def query_fundamental_reports_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
) -> pd.DataFrame:
    """Return visible reports using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            stock_code,
            report_period,
            publish_time,
            effective_date,
            revenue,
            net_profit,
            roe,
            gross_margin,
            operating_cashflow,
            debt_ratio,
            goodwill,
            total_equity,
            accounts_receivable,
            inventory,
            source
        FROM fundamental_reports
        WHERE CAST(publish_time AS DATE) <= ?
          AND effective_date <= ?
    """
    params: list[Any] = [parsed_date, parsed_date]
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    sql += " ORDER BY stock_code, report_period, publish_time"

    return connection.execute(sql, params).df()


def query_announcements_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
    announcement_type: str | None = None,
) -> pd.DataFrame:
    """Return visible announcements using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            announcement_id,
            source,
            source_tag,
            stock_code,
            title,
            announcement_type,
            publish_time,
            effective_date,
            url,
            raw_path,
            text_hash
        FROM announcements
        WHERE CAST(publish_time AS DATE) <= ?
          AND effective_date <= ?
    """
    params: list[Any] = [parsed_date, parsed_date]
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    if announcement_type is not None:
        sql += " AND announcement_type = ?"
        params.append(announcement_type)
    sql += " ORDER BY stock_code, publish_time, announcement_id"

    return connection.execute(sql, params).df()


def query_risk_events_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
    event_type: str | None = None,
) -> pd.DataFrame:
    """Return visible risk events using a caller-owned read-only connection."""
    parsed_date = parse_as_of_date(as_of_date)
    sql = """
        SELECT
            event_id,
            stock_code,
            event_type,
            event_date,
            publish_time,
            effective_date,
            payload_json,
            source
        FROM risk_events
        WHERE CAST(publish_time AS DATE) <= ?
          AND effective_date <= ?
    """
    params: list[Any] = [parsed_date, parsed_date]
    if stock_code is not None:
        sql += " AND stock_code = ?"
        params.append(stock_code)
    if event_type is not None:
        sql += " AND event_type = ?"
        params.append(event_type)
    sql += " ORDER BY stock_code, publish_time, event_id"

    return connection.execute(sql, params).df()


def build_as_of_snapshot(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    index_code: str | None = None,
    industry_standard: str | None = None,
    industry_version: str | None = None,
    include_delisted: bool = False,
    stock_code: str | None = None,
    data_source: str | None = None,
) -> AsOfSnapshot:
    """Build a deterministic collection of PIT query results from a caller-owned connection."""
    parsed_date = parse_as_of_date(as_of_date)
    return AsOfSnapshot(
        as_of_date=parsed_date,
        daily_prices=query_daily_prices_as_of(
            connection,
            parsed_date,
            stock_code=stock_code,
            source=data_source,
        ),
        valuation_daily=query_valuation_daily_as_of(
            connection,
            parsed_date,
            stock_code=stock_code,
            source=data_source,
        ),
        universe_members=query_universe_members_as_of(
            connection,
            parsed_date,
            index_code=index_code,
            stock_code=stock_code,
            source_tag=None if data_source == "legacy" else data_source,
        ),
        securities=query_securities_as_of(
            connection,
            parsed_date,
            include_delisted=include_delisted,
            stock_code=stock_code,
            source=data_source,
        ),
        st_status=query_st_status_as_of(connection, parsed_date, stock_code=stock_code),
        industry_classifications=query_industry_classifications_as_of(
            connection,
            parsed_date,
            industry_standard=industry_standard,
            version=industry_version,
            stock_code=stock_code,
        ),
        fundamental_reports=query_fundamental_reports_as_of(
            connection,
            parsed_date,
            stock_code=stock_code,
        ),
        announcements=query_announcements_as_of(connection, parsed_date, stock_code=stock_code),
        risk_events=query_risk_events_as_of(connection, parsed_date, stock_code=stock_code),
    )


def load_as_of_snapshot(
    db_path: str | Path,
    as_of_date: DateLike,
    index_code: str | None = None,
    industry_standard: str | None = None,
    industry_version: str | None = None,
    include_delisted: bool = False,
    stock_code: str | None = None,
    data_source: str | None = None,
) -> AsOfSnapshot:
    """Open DuckDB read-only, build an as-of snapshot, and always close the connection."""
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return build_as_of_snapshot(
            connection=connection,
            as_of_date=as_of_date,
            index_code=index_code,
            industry_standard=industry_standard,
            industry_version=industry_version,
            include_delisted=include_delisted,
            stock_code=stock_code,
            data_source=data_source,
        )
    finally:
        connection.close()
