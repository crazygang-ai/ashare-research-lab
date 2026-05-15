"""Synthetic PIT-universe benchmarks for Phase 1b backtests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import duckdb
import pandas as pd

from ashare.backtest.schedule import open_trading_dates_between
from ashare.pit.asof import DateLike, parse_as_of_date, query_universe_members_as_of


BENCHMARK_COLUMNS = [
    "trade_date",
    "cap_weight_return",
    "equal_weight_return",
    "cap_weight_nav",
    "equal_weight_nav",
    "cap_weight_coverage",
    "equal_weight_coverage",
    "cap_weight_member_count",
    "equal_weight_member_count",
]


def calculate_synthetic_benchmarks(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
    index_code: str,
    signal_dates: Sequence[DateLike],
    benchmark_config: Mapping[str, object] | None = None,
    initial_nav: float = 1.0,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Calculate monthly static cap-weight and equal-weight synthetic benchmarks."""
    start = parse_as_of_date(start_date)
    end = parse_as_of_date(end_date)
    trading_dates = open_trading_dates_between(connection, start, end)
    if not trading_dates:
        return pd.DataFrame(columns=BENCHMARK_COLUMNS), ()

    parsed_signal_dates = sorted(parse_as_of_date(value) for value in signal_dates)
    if not parsed_signal_dates:
        parsed_signal_dates = [trading_dates[0]]
    price_map = _price_map(connection, min(trading_dates), max(trading_dates))
    warnings: list[str] = []
    cap_nav = float(initial_nav)
    equal_nav = float(initial_nav)
    rows: list[dict[str, object]] = []
    previous_date: date | None = None

    for trade_date in trading_dates:
        locked_signal = _locked_signal_date(trade_date, parsed_signal_dates, start)
        members = _benchmark_members(
            connection=connection,
            signal_date=locked_signal,
            index_code=index_code,
            benchmark_config=benchmark_config,
        )
        cap_return, cap_coverage = _portfolio_return(
            members=members,
            price_map=price_map,
            trade_date=trade_date,
            previous_date=previous_date,
            weight_column="cap_weight",
            warnings=warnings,
        )
        equal_return, equal_coverage = _portfolio_return(
            members=members,
            price_map=price_map,
            trade_date=trade_date,
            previous_date=previous_date,
            weight_column="equal_weight",
            warnings=warnings,
        )
        cap_nav *= 1.0 + cap_return
        equal_nav *= 1.0 + equal_return
        member_count = len(members)
        rows.append(
            {
                "trade_date": trade_date,
                "cap_weight_return": cap_return,
                "equal_weight_return": equal_return,
                "cap_weight_nav": cap_nav,
                "equal_weight_nav": equal_nav,
                "cap_weight_coverage": cap_coverage,
                "equal_weight_coverage": equal_coverage,
                "cap_weight_member_count": member_count,
                "equal_weight_member_count": member_count,
            }
        )
        previous_date = trade_date

    result = pd.DataFrame(rows, columns=BENCHMARK_COLUMNS)
    result = result.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    return result, tuple(dict.fromkeys(warnings))


def _benchmark_members(
    *,
    connection: duckdb.DuckDBPyConnection,
    signal_date: date,
    index_code: str,
    benchmark_config: Mapping[str, object] | None,
) -> pd.DataFrame:
    universe = query_universe_members_as_of(
        connection,
        signal_date,
        index_code=index_code,
    )
    if universe.empty:
        return pd.DataFrame(columns=["stock_code", "cap_weight", "equal_weight"])
    members = (
        universe.loc[:, ["stock_code"]]
        .dropna()
        .drop_duplicates("stock_code", keep="first")
        .sort_values("stock_code", kind="mergesort")
        .reset_index(drop=True)
    )
    valuations = _valuation_on_date(connection, signal_date)
    members = members.merge(valuations, on="stock_code", how="left")
    priority = _market_cap_priority(benchmark_config)
    members["market_cap"] = pd.NA
    for field in priority:
        if field in members.columns:
            members["market_cap"] = members["market_cap"].where(
                pd.notna(members["market_cap"]),
                members[field],
            )
    members["market_cap"] = pd.to_numeric(members["market_cap"], errors="coerce")
    total_market_cap = members.loc[members["market_cap"] > 0, "market_cap"].sum()
    if total_market_cap > 0:
        members["cap_weight"] = members["market_cap"].where(
            members["market_cap"] > 0,
            0.0,
        ) / total_market_cap
    else:
        members["cap_weight"] = 1.0 / len(members)
    members["equal_weight"] = 1.0 / len(members)
    return members.loc[:, ["stock_code", "cap_weight", "equal_weight"]]


def _valuation_on_date(
    connection: duckdb.DuckDBPyConnection,
    signal_date: date,
) -> pd.DataFrame:
    frame = connection.execute(
        """
        SELECT stock_code, float_mv, total_mv
        FROM valuation_daily
        WHERE trade_date = ?
        ORDER BY stock_code
        """,
        [signal_date],
    ).df()
    if frame.empty:
        return pd.DataFrame(columns=["stock_code", "float_mv", "total_mv"])
    return frame


def _portfolio_return(
    *,
    members: pd.DataFrame,
    price_map: Mapping[tuple[str, date], Mapping[str, object]],
    trade_date: date,
    previous_date: date | None,
    weight_column: str,
    warnings: list[str],
) -> tuple[float, float]:
    if previous_date is None or members.empty:
        return 0.0, 0.0 if members.empty else 1.0

    total_return = 0.0
    valid_count = 0
    member_count = len(members)
    for row in members.itertuples(index=False):
        stock_code = str(row.stock_code)
        weight = float(getattr(row, weight_column))
        current = price_map.get((stock_code, trade_date))
        previous = price_map.get((stock_code, previous_date))
        if current is None or previous is None or bool(current.get("is_suspended", False)):
            stock_return = 0.0
        else:
            current_price, current_fallback = _adjusted_close(current)
            previous_price, previous_fallback = _adjusted_close(previous)
            if current_price is None or previous_price is None or previous_price <= 0:
                stock_return = 0.0
            else:
                stock_return = current_price / previous_price - 1.0
                valid_count += 1
                if current_fallback or previous_fallback:
                    warnings.append(
                        "Benchmark adjusted_close used close fallback for missing adj_factor."
                    )
        total_return += weight * stock_return
    coverage = valid_count / member_count if member_count else 0.0
    return float(total_return), float(coverage)


def _price_map(
    connection: duckdb.DuckDBPyConnection,
    start_date: date,
    end_date: date,
) -> dict[tuple[str, date], dict[str, object]]:
    frame = connection.execute(
        """
        SELECT stock_code, trade_date, close, adj_factor, is_suspended
        FROM daily_prices
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY stock_code, trade_date
        """,
        [start_date, end_date],
    ).df()
    result: dict[tuple[str, date], dict[str, object]] = {}
    if frame.empty:
        return result
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    for row in frame.itertuples(index=False):
        result[(str(row.stock_code), row.trade_date)] = {
            "close": row.close,
            "adj_factor": row.adj_factor,
            "is_suspended": bool(row.is_suspended) if pd.notna(row.is_suspended) else False,
        }
    return result


def _adjusted_close(row: Mapping[str, object]) -> tuple[float | None, bool]:
    close = row.get("close")
    if pd.isna(close) or float(close) <= 0:
        return None, False
    adj_factor = row.get("adj_factor")
    if pd.isna(adj_factor):
        return float(close), True
    return float(close) * float(adj_factor), False


def _locked_signal_date(trade_date: date, signal_dates: Sequence[date], start_date: date) -> date:
    locked = [value for value in signal_dates if value <= trade_date]
    if locked:
        return locked[-1]
    return min(signal_dates[0], start_date)


def _market_cap_priority(benchmark_config: Mapping[str, object] | None) -> tuple[str, ...]:
    if not benchmark_config:
        return ("float_mv", "total_mv")
    value = benchmark_config.get("market_cap_field_priority")
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    return ("float_mv", "total_mv")
