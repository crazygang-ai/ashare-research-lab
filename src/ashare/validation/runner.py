"""Orchestration for Phase 1a-5 single-factor validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml

from ashare.pit.asof import DateLike, parse_as_of_date
from ashare.validation.config import merge_validation_config
from ashare.validation.decay import aggregate_decay_curve
from ashare.validation.ic import calculate_rank_ic, summarize_ic
from ashare.validation.labels import build_forward_return_labels
from ashare.validation.quantile_returns import calculate_group_returns


COVERAGE_COLUMNS = [
    "factor_name",
    "trade_date",
    "universe_count",
    "valid_factor_count",
    "missing_count",
    "coverage",
    "missing_rate",
    "universe_source",
]

LABEL_SUMMARY_COLUMNS = ["horizon", "valid_label_count", "latest_usable_signal_date"]

FACTOR_INPUT_COLUMNS = [
    "stock_code",
    "trade_date",
    "factor_name",
    "factor_value",
    "as_of_date",
    "source_run_id",
]

ALLOWED_DIRECTIONS = {"higher_is_better", "lower_is_better", "boolean_filter"}
DEFAULT_DATA_DICTIONARY_PATH = Path("configs/data_dictionary.yaml")


@dataclass(frozen=True)
class FactorValidationResult:
    coverage: pd.DataFrame
    label_summary: pd.DataFrame
    rank_ic: pd.DataFrame
    ic_summary: pd.DataFrame
    group_returns: pd.DataFrame
    decay_curve: pd.DataFrame
    warnings: tuple[str, ...] = ()


def load_data_dictionary(
    data_dictionary_path: str | Path = DEFAULT_DATA_DICTIONARY_PATH,
) -> dict[str, object]:
    """Load the factor data dictionary YAML."""
    path = Path(data_dictionary_path)
    with path.open(encoding="utf-8") as file:
        data_dictionary = yaml.safe_load(file) or {}
    if not isinstance(data_dictionary, dict):
        raise ValueError(f"Data dictionary must be a mapping: {path}")
    return data_dictionary


def validate_factors(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
    source_run_id: str,
    factor_names: Sequence[str] | None = None,
    horizons: Sequence[int] | None = None,
    n_groups: int | None = None,
    include_hard_filters: bool = False,
    validation_config: Mapping[str, object] | None = None,
    data_dictionary: Mapping[str, object] | None = None,
) -> FactorValidationResult:
    """Run single-factor validation on already-stored ``factor_values`` rows."""
    if not source_run_id or not str(source_run_id).strip():
        raise ValueError("source_run_id must be explicitly provided.")

    start = parse_as_of_date(start_date)
    end = parse_as_of_date(end_date)
    if start > end:
        raise ValueError(f"start_date {start.isoformat()} is after end_date {end.isoformat()}.")

    config = merge_validation_config(validation_config, horizons=horizons, n_groups=n_groups)
    parsed_horizons = [int(value) for value in config["horizons"]]  # type: ignore[index]
    parsed_n_groups = int(config["n_groups"])
    min_ic_observations = int(config["min_ic_observations"])
    min_group_size = int(config["min_group_size"])
    require_same_as_of = bool(config["require_same_as_of_trade_date"])
    universe_factor_names = tuple(str(name) for name in config["universe_factor_names"])  # type: ignore[index]

    dictionary = data_dictionary if data_dictionary is not None else load_data_dictionary()
    factor_metadata = _factor_metadata(dictionary)
    selected_factors = _selected_factor_names(
        requested=factor_names,
        factor_metadata=factor_metadata,
        include_hard_filters=include_hard_filters,
    )
    directions = _directions(factor_metadata, selected_factors)

    factor_values = _load_factor_values(
        connection=connection,
        source_run_id=source_run_id,
        start_date=start,
        end_date=end,
        factor_names=selected_factors,
        require_same_as_of_trade_date=require_same_as_of,
    )
    if factor_values.empty:
        return _empty_result(parsed_horizons)

    _fail_on_duplicate_factor_keys(factor_values)
    factor_values = factor_values[pd.notna(factor_values["factor_value"])].reset_index(drop=True)
    if factor_values.empty:
        return _empty_result(parsed_horizons)
    signal_dates = sorted(factor_values["trade_date"].drop_duplicates().tolist())

    coverage, coverage_warnings = _coverage(
        connection=connection,
        source_run_id=source_run_id,
        signal_dates=signal_dates,
        factor_names=selected_factors,
        filtered_factor_values=factor_values,
        require_same_as_of_trade_date=require_same_as_of,
        universe_factor_names=universe_factor_names,
    )

    labels = build_forward_return_labels(connection, signal_dates, parsed_horizons)
    label_summary = _label_summary(labels, parsed_horizons)

    factor_labels = factor_values.merge(
        labels,
        on=["stock_code", "trade_date"],
        how="inner",
    )
    rank_ic = calculate_rank_ic(
        factor_labels,
        directions=directions,
        min_ic_observations=min_ic_observations,
    )
    ic_summary = summarize_ic(rank_ic)
    group_returns = calculate_group_returns(
        factor_labels,
        directions=directions,
        n_groups=parsed_n_groups,
        min_group_size=min_group_size,
    )
    decay_curve = aggregate_decay_curve(rank_ic, group_returns)

    warnings = list(coverage_warnings)
    if include_hard_filters and any(directions[name] == "boolean_filter" for name in selected_factors):
        warnings.append(
            "Boolean hard filters are included; oriented IC and group returns are not "
            "included in the usual factor interpretation."
        )

    return FactorValidationResult(
        coverage=coverage,
        label_summary=label_summary,
        rank_ic=rank_ic,
        ic_summary=ic_summary,
        group_returns=group_returns,
        decay_curve=decay_curve,
        warnings=tuple(warnings),
    )


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


def _selected_factor_names(
    requested: Sequence[str] | None,
    factor_metadata: Mapping[str, Mapping[str, object]],
    include_hard_filters: bool,
) -> tuple[str, ...]:
    if requested:
        selected = tuple(dict.fromkeys(str(name) for name in requested))
    else:
        allowed_types = {"factor", "hard_filter"} if include_hard_filters else {"factor"}
        selected = tuple(
            name
            for name, entry in factor_metadata.items()
            if str(entry.get("type")) in allowed_types
        )

    unknown = [name for name in selected if name not in factor_metadata]
    if unknown:
        raise ValueError(f"Unknown factor name(s): {', '.join(sorted(unknown))}")

    hard_filters = [
        name for name in selected if str(factor_metadata[name].get("type")) == "hard_filter"
    ]
    if hard_filters and not include_hard_filters:
        raise ValueError(
            "Hard filter validation requires include_hard_filters=True: "
            f"{', '.join(sorted(hard_filters))}"
        )
    return selected


def _directions(
    factor_metadata: Mapping[str, Mapping[str, object]],
    factor_names: Sequence[str],
) -> dict[str, str]:
    directions: dict[str, str] = {}
    for factor_name in factor_names:
        direction = factor_metadata[factor_name].get("direction")
        if not isinstance(direction, str) or direction not in ALLOWED_DIRECTIONS:
            raise ValueError(f"Missing or unsupported direction for factor: {factor_name}")
        directions[factor_name] = direction
    return directions


def _load_factor_values(
    connection: duckdb.DuckDBPyConnection,
    source_run_id: str,
    start_date: date,
    end_date: date,
    factor_names: Sequence[str],
    require_same_as_of_trade_date: bool,
) -> pd.DataFrame:
    if not factor_names:
        return pd.DataFrame(columns=FACTOR_INPUT_COLUMNS)
    placeholders = ", ".join("?" for _ in factor_names)
    params: list[Any] = [source_run_id, start_date, end_date, *factor_names]
    sql = f"""
        SELECT stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        FROM factor_values
        WHERE source_run_id = ?
          AND trade_date BETWEEN ? AND ?
          AND factor_name IN ({placeholders})
    """
    if require_same_as_of_trade_date:
        sql += " AND as_of_date = trade_date"
    sql += " ORDER BY trade_date, factor_name, stock_code"
    frame = connection.execute(sql, params).df()
    return _normalize_factor_values(frame)


def _normalize_factor_values(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=FACTOR_INPUT_COLUMNS)
    result = frame.loc[:, FACTOR_INPUT_COLUMNS].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    result["as_of_date"] = pd.to_datetime(result["as_of_date"]).dt.date
    result["factor_value"] = pd.to_numeric(result["factor_value"], errors="coerce")
    return result


def _fail_on_duplicate_factor_keys(factor_values: pd.DataFrame) -> None:
    duplicate_counts = (
        factor_values.groupby(["source_run_id", "stock_code", "trade_date", "factor_name"])
        .size()
        .reset_index(name="row_count")
    )
    duplicates = duplicate_counts[duplicate_counts["row_count"] >= 2]
    if duplicates.empty:
        return
    samples = []
    for row in duplicates.head(5).itertuples(index=False):
        samples.append(
            f"({row.source_run_id}, {row.stock_code}, {row.trade_date}, "
            f"{row.factor_name}, count={row.row_count})"
        )
    raise ValueError(
        "Duplicate factor_values rows for "
        "(source_run_id, stock_code, trade_date, factor_name). "
        f"Examples: {'; '.join(samples)}"
    )


def _coverage(
    connection: duckdb.DuckDBPyConnection,
    source_run_id: str,
    signal_dates: Sequence[date],
    factor_names: Sequence[str],
    filtered_factor_values: pd.DataFrame,
    require_same_as_of_trade_date: bool,
    universe_factor_names: Sequence[str],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    valid_counts = (
        filtered_factor_values.groupby(["factor_name", "trade_date"])["stock_code"]
        .nunique()
        .to_dict()
    )

    for signal_date in signal_dates:
        universe_codes, universe_source = _universe_for_date(
            connection=connection,
            source_run_id=source_run_id,
            trade_date=signal_date,
            require_same_as_of_trade_date=require_same_as_of_trade_date,
            universe_factor_names=universe_factor_names,
        )
        if universe_source == "factor_values_fallback":
            warnings.append(
                f"Coverage universe fallback used for {signal_date.isoformat()}; "
                "coverage may be overestimated because it is inferred from visible "
                "factor_values rows."
            )

        universe_count = len(universe_codes)
        for factor_name in factor_names:
            valid_factor_count = int(valid_counts.get((factor_name, signal_date), 0))
            missing_count = max(universe_count - valid_factor_count, 0)
            coverage = valid_factor_count / universe_count if universe_count else float("nan")
            rows.append(
                {
                    "factor_name": factor_name,
                    "trade_date": signal_date,
                    "universe_count": universe_count,
                    "valid_factor_count": valid_factor_count,
                    "missing_count": missing_count,
                    "coverage": coverage,
                    "missing_rate": 1.0 - coverage if pd.notna(coverage) else float("nan"),
                    "universe_source": universe_source,
                }
            )

    return (
        pd.DataFrame(rows, columns=COVERAGE_COLUMNS).sort_values(
            ["factor_name", "trade_date"]
        ).reset_index(drop=True),
        tuple(dict.fromkeys(warnings)),
    )


def _universe_for_date(
    connection: duckdb.DuckDBPyConnection,
    source_run_id: str,
    trade_date: date,
    require_same_as_of_trade_date: bool,
    universe_factor_names: Sequence[str],
) -> tuple[set[str], str]:
    hard_filter_codes = _stock_codes_for_factor_names(
        connection,
        source_run_id,
        trade_date,
        require_same_as_of_trade_date,
        universe_factor_names,
    )
    if hard_filter_codes:
        return hard_filter_codes, "hard_filters"

    return (
        _stock_codes_for_factor_names(
            connection,
            source_run_id,
            trade_date,
            require_same_as_of_trade_date,
            None,
        ),
        "factor_values_fallback",
    )


def _stock_codes_for_factor_names(
    connection: duckdb.DuckDBPyConnection,
    source_run_id: str,
    trade_date: date,
    require_same_as_of_trade_date: bool,
    factor_names: Sequence[str] | None,
) -> set[str]:
    params: list[Any] = [source_run_id, trade_date]
    sql = """
        SELECT DISTINCT stock_code
        FROM factor_values
        WHERE source_run_id = ?
          AND trade_date = ?
    """
    if require_same_as_of_trade_date:
        sql += " AND as_of_date = trade_date"
    if factor_names is not None:
        if not factor_names:
            return set()
        placeholders = ", ".join("?" for _ in factor_names)
        sql += f" AND factor_name IN ({placeholders})"
        params.extend(factor_names)
    rows = connection.execute(sql, params).fetchall()
    return {str(row[0]) for row in rows}


def _label_summary(labels: pd.DataFrame, horizons: Sequence[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        horizon_labels = labels[labels["horizon"] == int(horizon)] if not labels.empty else labels
        latest = None
        valid_count = 0
        if not horizon_labels.empty:
            valid = horizon_labels[pd.notna(horizon_labels["forward_return"])]
            valid_count = int(len(valid))
            if not valid.empty:
                latest = valid["trade_date"].max()
        rows.append(
            {
                "horizon": int(horizon),
                "valid_label_count": valid_count,
                "latest_usable_signal_date": latest,
            }
        )
    return pd.DataFrame(rows, columns=LABEL_SUMMARY_COLUMNS)


def _empty_result(horizons: Sequence[int]) -> FactorValidationResult:
    return FactorValidationResult(
        coverage=pd.DataFrame(columns=COVERAGE_COLUMNS),
        label_summary=_label_summary(pd.DataFrame(), horizons),
        rank_ic=pd.DataFrame(columns=[
            "factor_name",
            "trade_date",
            "horizon",
            "valid_n",
            "rank_ic",
            "oriented_rank_ic",
        ]),
        ic_summary=pd.DataFrame(columns=[
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
        ]),
        group_returns=pd.DataFrame(columns=[
            "factor_name",
            "trade_date",
            "horizon",
            "top_return",
            "bottom_return",
            "top_minus_bottom_return",
            "long_short_return",
            "valid_group_size",
        ]),
        decay_curve=pd.DataFrame(columns=[
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
        ]),
    )
