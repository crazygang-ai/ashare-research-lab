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
INDUSTRY_VALUATION_FACTORS = {
    "industry_pe_ttm_percentile": "pe_ttm",
}


def calculate_valuation_factors(
    valuation_daily: pd.DataFrame,
    industry_classifications: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    factor_names: Sequence[str],
    factor_config: Mapping[str, object],
) -> pd.DataFrame:
    """Calculate single-stock rolling valuation percentiles."""
    selected = [name for name in VALUATION_FACTORS if name in factor_names]
    selected_industry = [name for name in INDUSTRY_VALUATION_FACTORS if name in factor_names]
    if not selected and not selected_industry:
        return _empty()
    if valuation_daily.empty:
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

    for factor_name in selected_industry:
        source_column = INDUSTRY_VALUATION_FACTORS[factor_name]
        params = factor_params(factor_config, factor_name)
        rows.extend(
            _industry_percentile_rows(
                frame=frame,
                industry_classifications=industry_classifications,
                stock_codes=stock_codes,
                as_of_date=as_of_date,
                factor_name=factor_name,
                source_column=source_column,
                min_observations=int(params["min_industry_observations"]),
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


def _industry_percentile_rows(
    frame: pd.DataFrame,
    industry_classifications: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    factor_name: str,
    source_column: str,
    min_observations: int,
) -> list[dict[str, object]]:
    if industry_classifications.empty:
        return []

    industries = industry_classifications[
        industry_classifications["stock_code"].isin(stock_codes)
    ].copy()
    if industries.empty or "industry_l1" not in industries.columns:
        return []
    industries = industries.dropna(subset=["stock_code", "industry_l1"])
    industries = industries.drop_duplicates(["stock_code"], keep="last")

    current = frame[(frame["trade_date"] == as_of_date) & frame["stock_code"].isin(stock_codes)]
    if current.empty:
        return []
    current = current.loc[:, ["stock_code", source_column]].copy()
    current[source_column] = pd.to_numeric(current[source_column], errors="coerce")
    current = current[pd.notna(current[source_column]) & (current[source_column] > 0)]
    if current.empty:
        return []

    cross_section = current.merge(
        industries.loc[:, ["stock_code", "industry_l1"]],
        on="stock_code",
        how="inner",
    )
    if cross_section.empty:
        return []

    rows: list[dict[str, object]] = []
    for _industry, group in cross_section.groupby("industry_l1", sort=True):
        if len(group) < min_observations or len(group) <= 1:
            continue
        ranks = group[source_column].rank(method="average", ascending=True)
        percentiles = (ranks - 1.0) / (len(group) - 1)
        for row, percentile in zip(group.itertuples(index=False), percentiles, strict=True):
            rows.append(
                _factor_row(str(row.stock_code), as_of_date, factor_name, float(percentile))
            )
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
