"""Valuation percentile factor calculations."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import pandas as pd

from ashare.factors.config import factor_params


VALUATION_FACTORS = {
    "pe_ttm_percentile": "pe_ttm",
    "pb_percentile": "pb",
}


def calculate_valuation_factors(
    valuation_daily: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    factor_names: Sequence[str],
    factor_config: Mapping[str, object],
) -> pd.DataFrame:
    """Calculate single-stock rolling valuation percentiles."""
    selected = [name for name in VALUATION_FACTORS if name in factor_names]
    if not selected or valuation_daily.empty:
        return _empty()

    frame = valuation_daily[valuation_daily["stock_code"].isin(stock_codes)].copy()
    if frame.empty:
        return _empty()

    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame = frame.sort_values(["stock_code", "trade_date"], kind="mergesort")

    rows: list[dict[str, object]] = []
    for factor_name in selected:
        source_column = VALUATION_FACTORS[factor_name]
        params = factor_params(factor_config, factor_name)
        rows.extend(
            _percentile_rows(
                frame=frame,
                stock_codes=stock_codes,
                as_of_date=as_of_date,
                factor_name=factor_name,
                source_column=source_column,
                window=int(params["window_days"]),
                min_observations=int(params["min_observations"]),
            )
        )

    return pd.DataFrame(rows) if rows else _empty()


def _percentile_rows(
    frame: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    factor_name: str,
    source_column: str,
    window: int,
    min_observations: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for stock_code in stock_codes:
        stock_rows = frame[frame["stock_code"] == stock_code]
        current = stock_rows[stock_rows["trade_date"] == as_of_date]
        if current.empty:
            continue
        current_value = current.iloc[-1][source_column]
        if pd.isna(current_value) or float(current_value) <= 0:
            continue

        valid = stock_rows[pd.notna(stock_rows[source_column])].copy()
        valid = valid[valid[source_column] > 0]
        valid = valid[valid["trade_date"] <= as_of_date].tail(window)
        if len(valid) < min_observations or len(valid) <= 1:
            continue

        ranks = valid[source_column].rank(method="average", ascending=True)
        percentile = (float(ranks.iloc[-1]) - 1.0) / (len(valid) - 1)
        rows.append(_factor_row(stock_code, as_of_date, factor_name, percentile))
    return rows


def _factor_row(
    stock_code: str,
    as_of_date: date,
    factor_name: str,
    factor_value: float,
) -> dict[str, object]:
    return {
        "stock_code": stock_code,
        "trade_date": as_of_date,
        "factor_name": factor_name,
        "factor_value": float(factor_value),
        "as_of_date": as_of_date,
    }


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["stock_code", "trade_date", "factor_name", "factor_value", "as_of_date"]
    )
