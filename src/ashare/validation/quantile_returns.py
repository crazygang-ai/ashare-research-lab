"""Top/bottom group return metrics for single-factor validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


GROUP_RETURN_COLUMNS = [
    "factor_name",
    "trade_date",
    "horizon",
    "top_return",
    "bottom_return",
    "top_minus_bottom_return",
    "long_short_return",
    "valid_group_size",
]


def calculate_group_returns(
    factor_labels: pd.DataFrame,
    directions: Mapping[str, str],
    n_groups: int = 5,
    min_group_size: int = 1,
) -> pd.DataFrame:
    """Calculate deterministic top/bottom forward returns by daily cross-section."""
    if factor_labels.empty:
        return _empty_group_returns()
    if n_groups <= 0:
        raise ValueError("n_groups must be positive.")
    if min_group_size <= 0:
        raise ValueError("min_group_size must be positive.")

    rows: list[dict[str, Any]] = []
    grouped = factor_labels.groupby(["factor_name", "trade_date", "horizon"], sort=True)
    for (factor_name, trade_date, horizon), group in grouped:
        direction = directions.get(str(factor_name))
        if direction == "boolean_filter":
            continue
        if direction not in {"higher_is_better", "lower_is_better"}:
            continue

        clean = group.loc[
            pd.notna(group["factor_value"]) & pd.notna(group["forward_return"]),
            ["stock_code", "factor_value", "forward_return"],
        ].copy()
        valid_n = int(len(clean))
        if valid_n < n_groups * min_group_size:
            continue

        clean["oriented_factor_value"] = clean["factor_value"].astype(float)
        if direction == "lower_is_better":
            clean["oriented_factor_value"] = -clean["oriented_factor_value"]
        clean = clean.sort_values(
            ["oriented_factor_value", "stock_code"],
            ascending=[True, True],
            kind="mergesort",
        ).reset_index(drop=True)
        clean["group_index"] = np.floor(np.arange(valid_n) * n_groups / valid_n).astype(int)
        clean["group_index"] = clean["group_index"].clip(upper=n_groups - 1)

        bottom = clean.loc[clean["group_index"] == 0, "forward_return"].astype(float)
        top = clean.loc[clean["group_index"] == n_groups - 1, "forward_return"].astype(float)
        if top.empty or bottom.empty:
            continue

        top_return = float(top.mean())
        bottom_return = float(bottom.mean())
        spread = top_return - bottom_return
        rows.append(
            {
                "factor_name": factor_name,
                "trade_date": trade_date,
                "horizon": int(horizon),
                "top_return": top_return,
                "bottom_return": bottom_return,
                "top_minus_bottom_return": spread,
                "long_short_return": spread,
                "valid_group_size": int(min(len(top), len(bottom))),
            }
        )

    if not rows:
        return _empty_group_returns()
    return pd.DataFrame(rows, columns=GROUP_RETURN_COLUMNS).sort_values(
        ["factor_name", "horizon", "trade_date"]
    ).reset_index(drop=True)


def _empty_group_returns() -> pd.DataFrame:
    return pd.DataFrame(columns=GROUP_RETURN_COLUMNS)
