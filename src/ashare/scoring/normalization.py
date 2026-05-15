"""Cross-sectional factor normalization for Phase 3 scoring."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


NORMALIZED_SCORE_COLUMNS = [
    "stock_code",
    "factor_name",
    "raw_factor_value",
    "direction",
    "normalized_score",
]


def normalize_factor_scores(
    factor_values: pd.DataFrame,
    data_dictionary: Mapping[str, object],
    scoring_config: Mapping[str, object],
) -> pd.DataFrame:
    """Normalize one-day factor rows to 0-100 cross-sectional percentile scores."""
    if factor_values.empty:
        return pd.DataFrame(columns=NORMALIZED_SCORE_COLUMNS)

    factor_metadata = _factor_metadata(data_dictionary)
    risk_directions = _risk_directions(scoring_config)
    normalization = scoring_config.get("normalization", {})
    if not isinstance(normalization, Mapping):
        normalization = {}
    output_min = float(normalization.get("output_min", 0.0))
    output_max = float(normalization.get("output_max", 100.0))
    single_score = float(normalization.get("single_observation_score", 50.0))
    all_equal_score = float(normalization.get("all_equal_score", 50.0))

    working = factor_values.copy()
    working.attrs = {}
    raw_column = "raw_factor_value" if "raw_factor_value" in working.columns else "factor_value"
    rows: list[pd.DataFrame] = []
    for factor_name, group in working.groupby("factor_name", sort=True):
        name = str(factor_name)
        direction = risk_directions.get(name)
        if direction is None:
            entry = factor_metadata.get(name)
            if entry is None:
                raise ValueError(f"Unknown factor in data dictionary: {name}")
            direction_value = entry.get("direction")
            if not isinstance(direction_value, str):
                raise ValueError(f"Missing direction for factor: {name}")
            direction = direction_value
        if direction == "boolean_filter":
            raise ValueError(f"boolean_filter factor cannot be normalized for scoring: {name}")
        if direction not in {
            "higher_is_better",
            "lower_is_better",
            "higher_is_worse",
            "lower_is_worse",
        }:
            raise ValueError(f"Unsupported scoring direction for factor {name}: {direction}")

        clean = group.loc[:, ["stock_code", "factor_name", raw_column]].copy()
        clean.attrs = {}
        clean = clean.rename(columns={raw_column: "raw_factor_value"})
        clean["raw_factor_value"] = pd.to_numeric(clean["raw_factor_value"], errors="coerce")
        clean = clean[pd.notna(clean["raw_factor_value"])].copy()
        if clean.empty:
            continue

        oriented = clean["raw_factor_value"].astype(float)
        if direction in {"lower_is_better", "lower_is_worse"}:
            oriented = -oriented
        scores = _percentile_scores(
            oriented=oriented,
            output_min=output_min,
            output_max=output_max,
            single_score=single_score,
            all_equal_score=all_equal_score,
        )
        clean["direction"] = direction
        clean["normalized_score"] = scores.clip(lower=output_min, upper=output_max)
        rows.append(clean.loc[:, NORMALIZED_SCORE_COLUMNS])

    if not rows:
        return pd.DataFrame(columns=NORMALIZED_SCORE_COLUMNS)
    result = pd.concat(rows, ignore_index=True)
    result.attrs = {}
    return result.sort_values(
        ["factor_name", "stock_code"],
        kind="mergesort",
    ).reset_index(drop=True)


def _percentile_scores(
    oriented: pd.Series,
    output_min: float,
    output_max: float,
    single_score: float,
    all_equal_score: float,
) -> pd.Series:
    n = int(len(oriented))
    if n == 1:
        return pd.Series([single_score], index=oriented.index, dtype=float)
    if oriented.nunique(dropna=True) == 1:
        return pd.Series([all_equal_score] * n, index=oriented.index, dtype=float)
    ranks = oriented.rank(method="average", ascending=True)
    scale = output_max - output_min
    return output_min + scale * (ranks - 1.0) / (n - 1.0)


def _factor_metadata(data_dictionary: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    factors = data_dictionary.get("factors")
    if not isinstance(factors, Mapping):
        raise ValueError("data_dictionary.factors must be a mapping.")
    metadata: dict[str, Mapping[str, object]] = {}
    for name, entry in factors.items():
        if not isinstance(entry, Mapping):
            raise ValueError(f"data_dictionary.factors.{name} must be a mapping.")
        metadata[str(name)] = entry
    return metadata


def _risk_directions(scoring_config: Mapping[str, object]) -> dict[str, str]:
    risk = scoring_config.get("risk_penalty", {})
    if not isinstance(risk, Mapping) or not bool(risk.get("enabled", True)):
        return {}
    factors = risk.get("factors", {})
    if not isinstance(factors, Mapping):
        return {}
    directions: dict[str, str] = {}
    for factor_name, entry in factors.items():
        if not isinstance(entry, Mapping) or not bool(entry.get("enabled", True)):
            continue
        direction = entry.get("risk_direction")
        if isinstance(direction, str):
            directions[str(factor_name)] = direction
    return directions
