"""Hard-filter handling for Phase 3 composite scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd

from ashare.scoring.config import enabled_hard_filter_names


HARD_FILTER_EXCLUSION_COLUMNS = [
    "as_of_date",
    "source_run_id",
    "index_code",
    "stock_code",
    "hard_filter_name",
    "factor_value",
    "exclusion_reason",
]


@dataclass(frozen=True)
class HardFilterResult:
    passed_stock_codes: tuple[str, ...]
    exclusions: pd.DataFrame


def apply_hard_filters(
    factor_values: pd.DataFrame,
    universe: pd.DataFrame,
    as_of_date: date,
    source_run_id: str,
    index_code: str,
    scoring_config: Mapping[str, object],
) -> HardFilterResult:
    """Apply configured hard filters, conservatively excluding missing fields."""
    filter_names = enabled_hard_filter_names(scoring_config)
    if universe.empty:
        return HardFilterResult(
            passed_stock_codes=(),
            exclusions=pd.DataFrame(columns=HARD_FILTER_EXCLUSION_COLUMNS),
        )
    universe_codes = tuple(str(code) for code in universe["stock_code"].drop_duplicates())
    filter_config = _filter_config(scoring_config)
    wide = _wide_hard_filter_values(factor_values, filter_names)
    rows: list[dict[str, object]] = []

    for stock_code in universe_codes:
        for filter_name in filter_names:
            config = filter_config[filter_name]
            pass_value = float(config.get("pass_value", 0.0))
            value = wide.get((stock_code, filter_name))
            if value is None or pd.isna(value):
                rows.append(
                    _exclusion_row(
                        as_of_date=as_of_date,
                        source_run_id=source_run_id,
                        index_code=index_code,
                        stock_code=stock_code,
                        hard_filter_name=filter_name,
                        factor_value=pd.NA,
                        exclusion_reason="missing_hard_filter",
                    )
                )
            elif float(value) != pass_value:
                rows.append(
                    _exclusion_row(
                        as_of_date=as_of_date,
                        source_run_id=source_run_id,
                        index_code=index_code,
                        stock_code=stock_code,
                        hard_filter_name=filter_name,
                        factor_value=float(value),
                        exclusion_reason="failed_hard_filter",
                    )
                )

    exclusions = pd.DataFrame(rows, columns=HARD_FILTER_EXCLUSION_COLUMNS)
    if not exclusions.empty:
        exclusions = exclusions.sort_values(
            ["stock_code", "hard_filter_name"],
            kind="mergesort",
        ).reset_index(drop=True)
    excluded_codes = set(exclusions["stock_code"].astype(str)) if not exclusions.empty else set()
    passed = tuple(code for code in universe_codes if code not in excluded_codes)
    return HardFilterResult(passed_stock_codes=passed, exclusions=exclusions)


def empty_hard_filter_exclusions() -> pd.DataFrame:
    """Return an empty hard-filter exclusion frame with fixed columns."""
    return pd.DataFrame(columns=HARD_FILTER_EXCLUSION_COLUMNS)


def _filter_config(scoring_config: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    filters = scoring_config.get("hard_filters")
    if not isinstance(filters, Mapping):
        raise ValueError("hard_filters must be a mapping.")
    result: dict[str, Mapping[str, object]] = {}
    for name, entry in filters.items():
        if not isinstance(entry, Mapping):
            raise ValueError(f"hard_filters.{name} must be a mapping.")
        if bool(entry.get("enabled", True)):
            result[str(name)] = entry
    return result


def _wide_hard_filter_values(
    factor_values: pd.DataFrame,
    filter_names: Sequence[str],
) -> dict[tuple[str, str], float]:
    if factor_values.empty or not filter_names:
        return {}
    frame = factor_values[factor_values["factor_name"].isin(filter_names)].copy()
    frame["factor_value"] = pd.to_numeric(frame["factor_value"], errors="coerce")
    return {
        (str(row.stock_code), str(row.factor_name)): row.factor_value
        for row in frame.itertuples(index=False)
    }


def _exclusion_row(
    as_of_date: date,
    source_run_id: str,
    index_code: str,
    stock_code: str,
    hard_filter_name: str,
    factor_value: object,
    exclusion_reason: str,
) -> dict[str, object]:
    return {
        "as_of_date": as_of_date,
        "source_run_id": source_run_id,
        "index_code": index_code,
        "stock_code": stock_code,
        "hard_filter_name": hard_filter_name,
        "factor_value": factor_value,
        "exclusion_reason": exclusion_reason,
    }
