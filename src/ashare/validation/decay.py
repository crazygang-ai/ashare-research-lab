"""Horizon-level decay aggregation for single-factor validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DECAY_COLUMNS = [
    "factor_name",
    "horizon",
    "valid_ic_dates",
    "valid_group_dates",
    "mean_rank_ic",
    "icir",
    "mean_oriented_rank_ic",
    "oriented_icir",
    "mean_top_return",
    "mean_bottom_return",
    "mean_top_minus_bottom_return",
    "mean_long_short_return",
]


def aggregate_decay_curve(rank_ic: pd.DataFrame, group_returns: pd.DataFrame) -> pd.DataFrame:
    """Aggregate IC and group-return metrics by factor and horizon."""
    keys = _factor_horizon_keys(rank_ic, group_returns)
    if not keys:
        return pd.DataFrame(columns=DECAY_COLUMNS)

    rows: list[dict[str, Any]] = []
    for factor_name, horizon in sorted(keys):
        ic_group = _slice(rank_ic, factor_name, horizon)
        return_group = _slice(group_returns, factor_name, horizon)
        rank_values = ic_group["rank_ic"].dropna().astype(float) if not ic_group.empty else []
        oriented_values = (
            ic_group["oriented_rank_ic"].dropna().astype(float) if not ic_group.empty else []
        )
        rows.append(
            {
                "factor_name": factor_name,
                "horizon": int(horizon),
                "valid_ic_dates": int(len(rank_values)),
                "valid_group_dates": int(
                    0
                    if return_group.empty
                    else return_group["top_minus_bottom_return"].dropna().shape[0]
                ),
                "mean_rank_ic": _mean(rank_values),
                "icir": _icir(rank_values),
                "mean_oriented_rank_ic": _mean(oriented_values),
                "oriented_icir": _icir(oriented_values),
                "mean_top_return": _column_mean(return_group, "top_return"),
                "mean_bottom_return": _column_mean(return_group, "bottom_return"),
                "mean_top_minus_bottom_return": _column_mean(
                    return_group,
                    "top_minus_bottom_return",
                ),
                "mean_long_short_return": _column_mean(return_group, "long_short_return"),
            }
        )

    return pd.DataFrame(rows, columns=DECAY_COLUMNS).reset_index(drop=True)


def _factor_horizon_keys(
    rank_ic: pd.DataFrame,
    group_returns: pd.DataFrame,
) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    for frame in (rank_ic, group_returns):
        if frame.empty:
            continue
        for row in frame[["factor_name", "horizon"]].drop_duplicates().itertuples(index=False):
            keys.add((str(row.factor_name), int(row.horizon)))
    return keys


def _slice(frame: pd.DataFrame, factor_name: str, horizon: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame[(frame["factor_name"] == factor_name) & (frame["horizon"] == horizon)]


def _column_mean(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return np.nan
    values = frame[column].dropna().astype(float)
    return _mean(values)


def _mean(values: object) -> float:
    series = pd.Series(values, dtype="float64")
    if series.empty:
        return np.nan
    return float(series.mean())


def _icir(values: object) -> float:
    series = pd.Series(values, dtype="float64")
    if len(series) < 2:
        return np.nan
    std = series.std(ddof=1)
    if pd.isna(std) or std == 0:
        return np.nan
    return float(series.mean() / std)
