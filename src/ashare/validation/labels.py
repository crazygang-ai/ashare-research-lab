"""Forward-return label construction for factor validation."""

from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import Sequence

import duckdb
import numpy as np
import pandas as pd

from ashare.pit.asof import DateLike, parse_as_of_date


LABEL_COLUMNS = [
    "stock_code",
    "trade_date",
    "horizon",
    "target_trade_date",
    "forward_return",
]


def build_forward_return_labels(
    connection: duckdb.DuckDBPyConnection,
    signal_dates: Sequence[DateLike],
    horizons: Sequence[int],
    data_source: str | None = None,
) -> pd.DataFrame:
    """Build close-to-close future return labels for given signal dates and horizons."""
    parsed_signal_dates = sorted({parse_as_of_date(value) for value in signal_dates})
    parsed_horizons = sorted({int(value) for value in horizons})
    if not parsed_signal_dates or not parsed_horizons:
        return _empty_labels()
    if any(horizon <= 0 for horizon in parsed_horizons):
        raise ValueError("horizons must be positive integers.")

    open_dates = _open_trading_dates(connection, data_source=data_source)
    target_map = _target_date_map(parsed_signal_dates, parsed_horizons, open_dates)
    if target_map.empty:
        return _empty_labels()

    price_dates = set(target_map["trade_date"]).union(target_map["target_trade_date"])
    prices = _daily_prices(connection, min(price_dates), max(price_dates), data_source=data_source)
    prices = prices[prices["trade_date"].isin(price_dates)].copy()
    if prices.empty:
        return _empty_labels()

    prices["adjusted_close"] = prices["close"] * prices["adj_factor"].fillna(1.0)
    prices = prices.loc[
        pd.notna(prices["close"]) & pd.notna(prices["adjusted_close"]),
        ["stock_code", "trade_date", "adjusted_close"],
    ]
    if prices.empty:
        return _empty_labels()

    start_prices = prices.rename(columns={"adjusted_close": "start_adjusted_close"})
    target_prices = prices.rename(
        columns={
            "trade_date": "target_trade_date",
            "adjusted_close": "target_adjusted_close",
        }
    )
    labels = target_map.merge(start_prices, on="trade_date", how="inner")
    labels = labels.merge(target_prices, on=["stock_code", "target_trade_date"], how="inner")
    if labels.empty:
        return _empty_labels()

    labels = labels[labels["start_adjusted_close"] != 0].copy()
    labels["forward_return"] = (
        labels["target_adjusted_close"] / labels["start_adjusted_close"] - 1.0
    )
    labels = labels[np.isfinite(labels["forward_return"])]
    labels = labels.loc[:, LABEL_COLUMNS]
    return labels.sort_values(["trade_date", "horizon", "stock_code"]).reset_index(drop=True)


def _open_trading_dates(
    connection: duckdb.DuckDBPyConnection,
    data_source: str | None = None,
) -> list[date]:
    sql = """
        SELECT trade_date
        FROM trading_calendar
        WHERE is_open = true
    """
    params: list[object] = []
    if data_source is not None:
        sql += " AND source = ?"
        params.append(data_source)
    sql += " ORDER BY trade_date"
    rows = connection.execute(sql, params).fetchall()
    return [_to_date(row[0]) for row in rows]


def _target_date_map(
    signal_dates: Sequence[date],
    horizons: Sequence[int],
    open_dates: Sequence[date],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for signal_date in signal_dates:
        first_future_index = bisect_right(open_dates, signal_date)
        for horizon in horizons:
            target_index = first_future_index + horizon - 1
            if target_index < len(open_dates):
                rows.append(
                    {
                        "trade_date": signal_date,
                        "horizon": int(horizon),
                        "target_trade_date": open_dates[target_index],
                    }
                )
    return pd.DataFrame(rows, columns=["trade_date", "horizon", "target_trade_date"])


def _daily_prices(
    connection: duckdb.DuckDBPyConnection,
    start_date: date,
    end_date: date,
    data_source: str | None = None,
) -> pd.DataFrame:
    sql = """
        SELECT stock_code, trade_date, close, adj_factor
        FROM daily_prices
        WHERE trade_date BETWEEN ? AND ?
    """
    params: list[object] = [start_date, end_date]
    if data_source is not None:
        sql += " AND source = ?"
        params.append(data_source)
    prices = connection.execute(sql, params).df()
    if prices.empty:
        return prices
    prices["trade_date"] = pd.to_datetime(prices["trade_date"]).dt.date
    return prices


def _empty_labels() -> pd.DataFrame:
    return pd.DataFrame(columns=LABEL_COLUMNS)


def _to_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()
