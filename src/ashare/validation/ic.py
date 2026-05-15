"""Rank IC and ICIR metrics for single-factor validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


RANK_IC_COLUMNS = [
    "factor_name",
    "trade_date",
    "horizon",
    "valid_n",
    "rank_ic",
    "oriented_rank_ic",
]

IC_SUMMARY_COLUMNS = [
    "factor_name",
    "horizon",
    "valid_ic_dates",
    "mean_rank_ic",
    "rank_ic_std",
    "icir",
    "valid_oriented_ic_dates",
    "mean_oriented_rank_ic",
    "oriented_rank_ic_std",
    "oriented_icir",
]


def calculate_rank_ic(
    factor_labels: pd.DataFrame,
    directions: Mapping[str, str],
    min_ic_observations: int = 3,
) -> pd.DataFrame:
    """Calculate daily Spearman rank IC by factor, signal date, and horizon."""
    if factor_labels.empty:
        return _empty_rank_ic()

    rows: list[dict[str, Any]] = []
    grouped = factor_labels.groupby(["factor_name", "trade_date", "horizon"], sort=True)
    for (factor_name, trade_date, horizon), group in grouped:
        clean = group.loc[
            pd.notna(group["factor_value"]) & pd.notna(group["forward_return"]),
            ["factor_value", "forward_return"],
        ].copy()
        valid_n = int(len(clean))
        rank_ic = np.nan
        if valid_n >= min_ic_observations:
            factor_rank = clean["factor_value"].rank(method="average")
            return_rank = clean["forward_return"].rank(method="average")
            if factor_rank.std(ddof=0) > 0 and return_rank.std(ddof=0) > 0:
                rank_ic = float(factor_rank.corr(return_rank, method="pearson"))

        direction = directions.get(str(factor_name))
        oriented_rank_ic = _orient_rank_ic(rank_ic, direction)
        rows.append(
            {
                "factor_name": factor_name,
                "trade_date": trade_date,
                "horizon": int(horizon),
                "valid_n": valid_n,
                "rank_ic": rank_ic,
                "oriented_rank_ic": oriented_rank_ic,
            }
        )

    return pd.DataFrame(rows, columns=RANK_IC_COLUMNS).sort_values(
        ["factor_name", "horizon", "trade_date"]
    ).reset_index(drop=True)


def summarize_ic(rank_ic: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily IC into ICIR summaries by factor and horizon."""
    if rank_ic.empty:
        return _empty_ic_summary()

    rows: list[dict[str, Any]] = []
    for (factor_name, horizon), group in rank_ic.groupby(["factor_name", "horizon"], sort=True):
        ic_values = group["rank_ic"].dropna().astype(float)
        oriented_values = group["oriented_rank_ic"].dropna().astype(float)
        rows.append(
            {
                "factor_name": factor_name,
                "horizon": int(horizon),
                "valid_ic_dates": int(len(ic_values)),
                "mean_rank_ic": _mean_or_nan(ic_values),
                "rank_ic_std": _sample_std_or_nan(ic_values),
                "icir": _icir(ic_values),
                "valid_oriented_ic_dates": int(len(oriented_values)),
                "mean_oriented_rank_ic": _mean_or_nan(oriented_values),
                "oriented_rank_ic_std": _sample_std_or_nan(oriented_values),
                "oriented_icir": _icir(oriented_values),
            }
        )

    return pd.DataFrame(rows, columns=IC_SUMMARY_COLUMNS).sort_values(
        ["factor_name", "horizon"]
    ).reset_index(drop=True)


def _orient_rank_ic(rank_ic: float, direction: str | None) -> float:
    if pd.isna(rank_ic) or direction == "boolean_filter":
        return np.nan
    if direction == "higher_is_better":
        return float(rank_ic)
    if direction == "lower_is_better":
        return -float(rank_ic)
    return np.nan


def _icir(values: pd.Series) -> float:
    if len(values) < 2:
        return np.nan
    std = values.std(ddof=1)
    if pd.isna(std) or std == 0:
        return np.nan
    return float(values.mean() / std)


def _mean_or_nan(values: pd.Series) -> float:
    if values.empty:
        return np.nan
    return float(values.mean())


def _sample_std_or_nan(values: pd.Series) -> float:
    if len(values) < 2:
        return np.nan
    std = values.std(ddof=1)
    if pd.isna(std):
        return np.nan
    return float(std)


def _empty_rank_ic() -> pd.DataFrame:
    return pd.DataFrame(columns=RANK_IC_COLUMNS)


def _empty_ic_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=IC_SUMMARY_COLUMNS)
