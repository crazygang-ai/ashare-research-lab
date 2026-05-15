"""Phase 1a-4 basic factor calculation orchestration."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import duckdb
import pandas as pd

from ashare.factors.config import load_factor_config
from ashare.factors.financial import calculate_financial_factors
from ashare.factors.momentum import calculate_momentum_factors
from ashare.factors.risk import calculate_hard_filter_factors
from ashare.factors.valuation import calculate_valuation_factors
from ashare.pit.asof import (
    DateLike,
    parse_as_of_date,
    query_daily_prices_as_of,
    query_fundamental_reports_as_of,
    query_securities_as_of,
    query_st_status_as_of,
    query_universe_members_as_of,
    query_valuation_daily_as_of,
)


SUPPORTED_FACTORS: tuple[str, ...] = (
    "return_20d",
    "return_60d",
    "above_ma60",
    "low_liquidity",
    "is_st",
    "is_suspended",
    "is_delisted",
    "pe_ttm_percentile",
    "pb_percentile",
    "revenue_yoy",
    "profit_yoy",
)

FACTOR_COLUMNS = ["stock_code", "trade_date", "factor_name", "factor_value", "as_of_date"]


def calculate_factors_for_date(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    index_code: str | None = None,
    factor_names: Sequence[str] | None = None,
    include_delisted: bool = False,
    factor_config: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Calculate Phase 1a-4 factors for one explicit trading ``as_of_date``."""
    parsed_date = parse_as_of_date(as_of_date)
    _ensure_open_trading_day(connection, parsed_date)
    selected_factors = _selected_factors(factor_names)
    config = load_factor_config() if factor_config is None else factor_config

    universe = _calculation_universe(
        connection=connection,
        as_of_date=parsed_date,
        index_code=index_code,
        include_delisted=include_delisted,
    )
    if not universe.stock_codes:
        result = _empty_factor_frame()
        result.attrs["universe_size"] = 0
        result.attrs["as_of_date"] = parsed_date
        result.attrs["factor_names"] = selected_factors
        return result

    daily_prices = query_daily_prices_as_of(connection, parsed_date)
    valuation_daily = query_valuation_daily_as_of(connection, parsed_date)
    st_status = query_st_status_as_of(connection, parsed_date)
    fundamental_reports = query_fundamental_reports_as_of(connection, parsed_date)

    frames = [
        calculate_momentum_factors(
            prices=daily_prices,
            stock_codes=universe.stock_codes,
            as_of_date=parsed_date,
            factor_names=selected_factors,
            factor_config=config,
        ),
        calculate_hard_filter_factors(
            prices=daily_prices,
            securities=universe.securities,
            st_status=st_status,
            stock_codes=universe.stock_codes,
            as_of_date=parsed_date,
            factor_names=selected_factors,
            factor_config=config,
        ),
        calculate_valuation_factors(
            valuation_daily=valuation_daily,
            stock_codes=universe.stock_codes,
            as_of_date=parsed_date,
            factor_names=selected_factors,
            factor_config=config,
        ),
        calculate_financial_factors(
            fundamental_reports=fundamental_reports,
            stock_codes=universe.stock_codes,
            as_of_date=parsed_date,
            factor_names=selected_factors,
        ),
    ]
    non_empty = [frame for frame in frames if not frame.empty]
    result = pd.concat(non_empty, ignore_index=True) if non_empty else _empty_factor_frame()
    result = _ordered_factor_frame(result)
    result.attrs["universe_size"] = len(universe.stock_codes)
    result.attrs["as_of_date"] = parsed_date
    result.attrs["factor_names"] = selected_factors
    return result


def open_trading_dates_between(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
) -> list[date]:
    """Return open trading dates in the inclusive range."""
    start = parse_as_of_date(start_date)
    end = parse_as_of_date(end_date)
    if start > end:
        raise ValueError(f"--from date {start.isoformat()} is after --to date {end.isoformat()}.")

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


def _ensure_open_trading_day(connection: duckdb.DuckDBPyConnection, as_of_date: date) -> None:
    is_open = connection.execute(
        """
        SELECT COALESCE(bool_or(is_open), false)
        FROM trading_calendar
        WHERE trade_date = ?
        """,
        [as_of_date],
    ).fetchone()[0]
    if not bool(is_open):
        raise ValueError(f"{as_of_date.isoformat()} is not a trading day.")


class _Universe:
    def __init__(self, stock_codes: tuple[str, ...], securities: pd.DataFrame) -> None:
        self.stock_codes = stock_codes
        self.securities = securities


def _calculation_universe(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: date,
    index_code: str | None,
    include_delisted: bool,
) -> _Universe:
    all_securities = query_securities_as_of(
        connection,
        as_of_date,
        include_delisted=True,
    )
    all_securities = _normalize_date_columns(all_securities, ["list_date", "delist_date"])

    if index_code is not None:
        universe_members = query_universe_members_as_of(
            connection,
            as_of_date,
            index_code=index_code,
        )
        stock_codes = sorted(universe_members["stock_code"].dropna().unique().tolist())
        if not include_delisted and stock_codes:
            delisted = _delisted_codes(all_securities)
            stock_codes = [code for code in stock_codes if code not in delisted]
    else:
        securities = query_securities_as_of(
            connection,
            as_of_date,
            include_delisted=include_delisted,
        )
        stock_codes = sorted(securities["stock_code"].dropna().unique().tolist())

    securities_for_universe = all_securities[all_securities["stock_code"].isin(stock_codes)].copy()
    return _Universe(tuple(stock_codes), securities_for_universe)


def _delisted_codes(securities: pd.DataFrame) -> set[str]:
    if "is_delisted_as_of" not in securities.columns:
        return set()
    return set(securities.loc[securities["is_delisted_as_of"].fillna(False), "stock_code"])


def _selected_factors(factor_names: Sequence[str] | None) -> tuple[str, ...]:
    if not factor_names:
        return SUPPORTED_FACTORS

    unknown = sorted(set(factor_names) - set(SUPPORTED_FACTORS))
    if unknown:
        raise ValueError(f"Unsupported factor(s): {', '.join(unknown)}")

    return tuple(dict.fromkeys(factor_names))


def _ordered_factor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_factor_frame()

    result = frame.loc[:, FACTOR_COLUMNS].copy()
    result = result[pd.notna(result["factor_value"])]
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    result["as_of_date"] = pd.to_datetime(result["as_of_date"]).dt.date
    result["factor_value"] = result["factor_value"].astype(float)
    factor_order = {name: index for index, name in enumerate(SUPPORTED_FACTORS)}
    result["_factor_order"] = result["factor_name"].map(factor_order)
    result = result.sort_values(
        ["trade_date", "_factor_order", "stock_code"],
        kind="mergesort",
    )
    return result.drop(columns=["_factor_order"]).reset_index(drop=True)


def _empty_factor_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=FACTOR_COLUMNS)


def _normalize_date_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_datetime(result[column]).dt.date
    return result


def _to_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()
