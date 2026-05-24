"""Hard-filter factor calculations."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import pandas as pd


HARD_FILTER_FACTORS = {"is_st", "is_suspended", "is_delisted"}


def calculate_hard_filter_factors(
    prices: pd.DataFrame,
    securities: pd.DataFrame,
    st_status: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    factor_names: Sequence[str],
    factor_config: Mapping[str, object],
) -> pd.DataFrame:
    """Calculate boolean hard-filter rows for every stock in the final universe."""
    del factor_config

    selected = set(factor_names) & HARD_FILTER_FACTORS
    if not selected:
        return _empty()

    rows: list[dict[str, object]] = []
    st_codes = set(st_status["stock_code"].dropna()) if not st_status.empty else set()
    delisted_codes = _delisted_codes(securities)
    suspended_by_stock = _suspended_by_stock(prices, as_of_date)

    for stock_code in stock_codes:
        if "is_st" in selected:
            rows.append(_factor_row(stock_code, as_of_date, "is_st", stock_code in st_codes))
        if "is_suspended" in selected:
            rows.append(
                _factor_row(
                    stock_code,
                    as_of_date,
                    "is_suspended",
                    suspended_by_stock.get(stock_code, True),
                )
            )
        if "is_delisted" in selected:
            rows.append(
                _factor_row(stock_code, as_of_date, "is_delisted", stock_code in delisted_codes)
            )

    return pd.DataFrame(rows) if rows else _empty()


def _suspended_by_stock(prices: pd.DataFrame, as_of_date: date) -> dict[str, bool]:
    if prices.empty:
        return {}

    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    current = frame[frame["trade_date"] == as_of_date]
    return {
        row.stock_code: _nullable_bool(row.is_suspended)
        for row in current[["stock_code", "is_suspended"]].itertuples(index=False)
    }


def _nullable_bool(value: object) -> bool:
    if pd.isna(value):
        return False
    return bool(value)


def _delisted_codes(securities: pd.DataFrame) -> set[str]:
    if securities.empty or "is_delisted_as_of" not in securities.columns:
        return set()
    return set(securities.loc[securities["is_delisted_as_of"].fillna(False), "stock_code"])


def _factor_row(
    stock_code: str,
    as_of_date: date,
    factor_name: str,
    value: bool,
) -> dict[str, object]:
    return {
        "stock_code": stock_code,
        "trade_date": as_of_date,
        "factor_name": factor_name,
        "factor_value": 1.0 if value else 0.0,
        "as_of_date": as_of_date,
    }


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["stock_code", "trade_date", "factor_name", "factor_value", "as_of_date"]
    )
