"""Diagnostics for Phase 3 composite scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from ashare.pit.asof import DateLike, parse_as_of_date
from ashare.scoring.scorer import (
    CompositeScoreResult,
    compute_composite_scores,
    compute_scores_from_normalized,
)
from ashare.scoring.validation_gate import ValidationGateResult
from ashare.validation.labels import build_forward_return_labels


WEIGHT_SENSITIVITY_COLUMNS = [
    "scenario_name",
    "scenario_type",
    "changed_key",
    "change_direction",
    "change_pct",
    "top_n",
    "baseline_candidate_count",
    "scenario_candidate_count",
    "spearman_rank_corr",
    "top_n_overlap_count",
    "top_n_overlap_ratio",
    "max_abs_rank_change",
    "mean_abs_score_change",
    "warning",
]

YEARLY_STABILITY_COLUMNS = [
    "year",
    "horizon",
    "signal_date_count",
    "stock_observation_count",
    "rank_ic_mean",
    "rank_ic_std",
    "rank_icir",
    "top_bottom_spread_mean",
    "positive_rank_ic_rate",
    "status",
    "warning",
]


def run_weight_sensitivity(
    base_result: CompositeScoreResult,
    scoring_config: Mapping[str, object],
    top_n: int,
) -> pd.DataFrame:
    """Run deterministic group and factor weight perturbation diagnostics."""
    sensitivity = _mapping(
        _mapping(scoring_config.get("diagnostics", {}), "diagnostics").get("sensitivity", {}),
        "diagnostics.sensitivity",
    )
    if not bool(sensitivity.get("enabled", True)):
        return pd.DataFrame(columns=WEIGHT_SENSITIVITY_COLUMNS)
    change_pct = float(sensitivity.get("perturbation_pct", 0.10))
    normalized = base_result.factor_normalized_scores
    passed_stock_codes = _passed_stock_codes(base_result)
    baseline = _scores_from_result(base_result, scoring_config, passed_stock_codes)
    scenarios = _sensitivity_scenarios(scoring_config, change_pct)

    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        scenario_config = scenario["config"]
        warning = str(scenario.get("warning", ""))
        if normalized.empty or not passed_stock_codes:
            scenario_scores = baseline.iloc[0:0].copy()
            warning = _join_warning(warning, "No baseline candidates available.")
        else:
            scenario_scores = compute_scores_from_normalized(
                normalized=normalized,
                passed_stock_codes=passed_stock_codes,
                scoring_config=scenario_config,
                as_of_date=_metadata_value(base_result, "as_of_date"),
                source_run_id=str(_metadata_value(base_result, "source_run_id")),
                index_code=str(_metadata_value(base_result, "index_code")),
            )
        rows.append(
            _sensitivity_row(
                scenario_name=str(scenario["scenario_name"]),
                scenario_type=str(scenario["scenario_type"]),
                changed_key=str(scenario["changed_key"]),
                change_direction=str(scenario["change_direction"]),
                change_pct=change_pct,
                top_n=top_n,
                baseline=baseline,
                scenario=scenario_scores,
                warning=warning,
            )
        )

    frame = pd.DataFrame(rows, columns=WEIGHT_SENSITIVITY_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["scenario_type", "changed_key", "change_direction"],
            kind="mergesort",
        ).reset_index(drop=True)
    return frame


def run_yearly_stability(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
    source_run_id: str,
    index_code: str,
    scoring_config: Mapping[str, object],
    data_dictionary: Mapping[str, object],
    validation_gate: ValidationGateResult,
    horizons: Sequence[int],
) -> pd.DataFrame:
    """Validate total_score as a synthetic factor by calendar year."""
    start = parse_as_of_date(start_date)
    end = parse_as_of_date(end_date)
    if start > end:
        raise ValueError("diagnostics start_date is after end_date.")
    signal_dates = _month_end_signal_dates(connection, start, end)
    parsed_horizons = [int(horizon) for horizon in horizons]
    if not signal_dates or not parsed_horizons:
        return pd.DataFrame(columns=YEARLY_STABILITY_COLUMNS)

    score_rows: list[pd.DataFrame] = []
    warnings_by_year: dict[int, list[str]] = {}
    for signal_date in signal_dates:
        try:
            result = compute_composite_scores(
                connection=connection,
                as_of_date=signal_date,
                source_run_id=source_run_id,
                index_code=index_code,
                scoring_config=scoring_config,
                data_dictionary=data_dictionary,
                validation_gate=validation_gate,
                top_n=1_000_000,
            )
        except (ValueError, duckdb.Error) as exc:
            warnings_by_year.setdefault(signal_date.year, []).append(
                f"{signal_date.isoformat()}: {exc}"
            )
            continue
        if result.scored_candidates.empty:
            warnings_by_year.setdefault(signal_date.year, []).append(
                f"{signal_date.isoformat()}: no scored candidates"
            )
            continue
        frame = result.scored_candidates.loc[:, ["stock_code", "as_of_date", "total_score"]].copy()
        frame = frame.rename(columns={"as_of_date": "trade_date"})
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        score_rows.append(frame)

    score_frame = (
        pd.concat(score_rows, ignore_index=True)
        if score_rows
        else pd.DataFrame(columns=["stock_code", "trade_date", "total_score"])
    )
    labels = build_forward_return_labels(connection, signal_dates, parsed_horizons)
    merged = score_frame.merge(labels, on=["stock_code", "trade_date"], how="inner")
    rows: list[dict[str, object]] = []
    min_dates = int(
        _mapping(
            _mapping(scoring_config.get("diagnostics", {}), "diagnostics").get(
                "yearly_stability",
                {},
            ),
            "diagnostics.yearly_stability",
        ).get("min_signal_dates_per_year", 1)
    )
    for year in sorted({item.year for item in signal_dates}):
        for horizon in parsed_horizons:
            subset = (
                merged[
                    (pd.to_datetime(merged["trade_date"]).dt.year == year)
                    & (merged["horizon"].astype(int) == horizon)
                ].copy()
                if not merged.empty
                else merged
            )
            metrics = _yearly_metrics(subset)
            signal_date_count = int(subset["trade_date"].nunique()) if not subset.empty else 0
            status = "ok" if signal_date_count >= min_dates else "insufficient"
            warning = "; ".join(dict.fromkeys(warnings_by_year.get(year, [])))
            if signal_date_count < min_dates:
                warning = _join_warning(
                    warning,
                    f"signal_date_count {signal_date_count} below minimum {min_dates}",
                )
            rows.append(
                {
                    "year": year,
                    "horizon": horizon,
                    "signal_date_count": signal_date_count,
                    "stock_observation_count": int(len(subset)),
                    "rank_ic_mean": metrics["rank_ic_mean"],
                    "rank_ic_std": metrics["rank_ic_std"],
                    "rank_icir": metrics["rank_icir"],
                    "top_bottom_spread_mean": metrics["top_bottom_spread_mean"],
                    "positive_rank_ic_rate": metrics["positive_rank_ic_rate"],
                    "status": status,
                    "warning": warning,
                }
            )

    return pd.DataFrame(rows, columns=YEARLY_STABILITY_COLUMNS).sort_values(
        ["year", "horizon"],
        kind="mergesort",
    ).reset_index(drop=True)


def _sensitivity_scenarios(
    scoring_config: Mapping[str, object],
    change_pct: float,
) -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    groups = _mapping(scoring_config.get("groups", {}), "groups")
    enabled_group_names = [
        str(name)
        for name, group in groups.items()
        if bool(_mapping(group, f"groups.{name}").get("enabled", False))
        and float(_mapping(group, f"groups.{name}").get("weight", 0.0)) > 0
    ]
    for group_name in enabled_group_names:
        for direction in ["up", "down"]:
            config, warning = _perturb_group_weight(
                scoring_config,
                group_name,
                direction,
                change_pct,
            )
            changed_key = f"groups.{group_name}.weight"
            scenarios.append(
                {
                    "scenario_name": f"{changed_key}.{direction}",
                    "scenario_type": "group_weight",
                    "changed_key": changed_key,
                    "change_direction": direction,
                    "config": config,
                    "warning": warning,
                }
            )

    for group_name in enabled_group_names:
        group = _mapping(groups[group_name], f"groups.{group_name}")
        factors = _mapping(group.get("factors", {}), f"groups.{group_name}.factors")
        factor_names = [
            str(name)
            for name, factor in factors.items()
            if bool(_mapping(factor, f"groups.{group_name}.factors.{name}").get("enabled", False))
            and float(_mapping(factor, f"groups.{group_name}.factors.{name}").get("weight", 0.0)) > 0
        ]
        for factor_name in factor_names:
            for direction in ["up", "down"]:
                config, warning = _perturb_factor_weight(
                    scoring_config,
                    group_name,
                    factor_name,
                    direction,
                    change_pct,
                )
                changed_key = f"groups.{group_name}.factors.{factor_name}.weight"
                scenarios.append(
                    {
                        "scenario_name": f"{changed_key}.{direction}",
                        "scenario_type": "factor_weight",
                        "changed_key": changed_key,
                        "change_direction": direction,
                        "config": config,
                        "warning": warning,
                    }
                )
    return scenarios


def _perturb_group_weight(
    scoring_config: Mapping[str, object],
    group_name: str,
    direction: str,
    change_pct: float,
) -> tuple[dict[str, object], str]:
    config = deepcopy(dict(scoring_config))
    groups = _mapping(config["groups"], "groups")
    target = _mapping(groups[group_name], f"groups.{group_name}")
    old_weight = float(target.get("weight", 0.0))
    new_weight = old_weight * (1.0 + change_pct if direction == "up" else 1.0 - change_pct)
    enabled_others = [
        str(name)
        for name, group in groups.items()
        if name != group_name
        and bool(_mapping(group, f"groups.{name}").get("enabled", False))
        and float(_mapping(group, f"groups.{name}").get("weight", 0.0)) > 0
    ]
    if not enabled_others:
        return config, "No other enabled group weight can be renormalized."
    remaining_total = sum(float(_mapping(groups[name], f"groups.{name}").get("weight", 0.0)) for name in enabled_others)
    new_remaining = max(0.0, 1.0 - new_weight)
    target["weight"] = new_weight
    for other in enabled_others:
        other_group = _mapping(groups[other], f"groups.{other}")
        other_group["weight"] = float(other_group.get("weight", 0.0)) / remaining_total * new_remaining
    return config, ""


def _perturb_factor_weight(
    scoring_config: Mapping[str, object],
    group_name: str,
    factor_name: str,
    direction: str,
    change_pct: float,
) -> tuple[dict[str, object], str]:
    config = deepcopy(dict(scoring_config))
    group = _mapping(_mapping(config["groups"], "groups")[group_name], f"groups.{group_name}")
    factors = _mapping(group["factors"], f"groups.{group_name}.factors")
    target = _mapping(factors[factor_name], f"groups.{group_name}.factors.{factor_name}")
    old_weight = float(target.get("weight", 0.0))
    new_weight = old_weight * (1.0 + change_pct if direction == "up" else 1.0 - change_pct)
    others = [
        str(name)
        for name, factor in factors.items()
        if name != factor_name
        and bool(_mapping(factor, f"groups.{group_name}.factors.{name}").get("enabled", False))
        and float(_mapping(factor, f"groups.{group_name}.factors.{name}").get("weight", 0.0)) > 0
    ]
    if not others:
        return config, "No other enabled factor weight can be renormalized."
    remaining_total = sum(
        float(_mapping(factors[name], f"groups.{group_name}.factors.{name}").get("weight", 0.0))
        for name in others
    )
    new_remaining = max(0.0, 1.0 - new_weight)
    target["weight"] = new_weight
    for other in others:
        other_factor = _mapping(factors[other], f"groups.{group_name}.factors.{other}")
        other_factor["weight"] = float(other_factor.get("weight", 0.0)) / remaining_total * new_remaining
    return config, ""


def _scores_from_result(
    result: CompositeScoreResult,
    scoring_config: Mapping[str, object],
    passed_stock_codes: tuple[str, ...],
) -> pd.DataFrame:
    if result.factor_normalized_scores.empty or not passed_stock_codes:
        return result.scored_candidates.copy()
    return compute_scores_from_normalized(
        normalized=result.factor_normalized_scores,
        passed_stock_codes=passed_stock_codes,
        scoring_config=scoring_config,
        as_of_date=_metadata_value(result, "as_of_date"),
        source_run_id=str(_metadata_value(result, "source_run_id")),
        index_code=str(_metadata_value(result, "index_code")),
    )


def _sensitivity_row(
    scenario_name: str,
    scenario_type: str,
    changed_key: str,
    change_direction: str,
    change_pct: float,
    top_n: int,
    baseline: pd.DataFrame,
    scenario: pd.DataFrame,
    warning: str,
) -> dict[str, object]:
    baseline_count = int(len(baseline))
    scenario_count = int(len(scenario))
    baseline_top = baseline.sort_values("rank", kind="mergesort").head(top_n)
    scenario_top = scenario.sort_values("rank", kind="mergesort").head(top_n)
    baseline_codes = set(baseline_top["stock_code"]) if "stock_code" in baseline_top else set()
    scenario_codes = set(scenario_top["stock_code"]) if "stock_code" in scenario_top else set()
    overlap = len(baseline_codes.intersection(scenario_codes))
    denominator = min(top_n, len(baseline_codes)) if baseline_codes else 0
    overlap_ratio = overlap / denominator if denominator else np.nan

    joined = baseline.loc[:, ["stock_code", "rank", "total_score"]].merge(
        scenario.loc[:, ["stock_code", "rank", "total_score"]],
        on="stock_code",
        suffixes=("_baseline", "_scenario"),
        how="inner",
    ) if not baseline.empty and not scenario.empty else pd.DataFrame()
    if len(joined) >= 2:
        corr = _spearman_corr(joined["rank_baseline"], joined["rank_scenario"])
        rank_change = (joined["rank_baseline"] - joined["rank_scenario"]).abs()
        score_change = (joined["total_score_baseline"] - joined["total_score_scenario"]).abs()
        max_rank_change = float(rank_change.max())
        mean_score_change = float(score_change.mean())
    else:
        corr = np.nan
        max_rank_change = np.nan
        mean_score_change = np.nan
        warning = _join_warning(warning, "Candidate count below 2; rank correlation is NaN.")
    return {
        "scenario_name": scenario_name,
        "scenario_type": scenario_type,
        "changed_key": changed_key,
        "change_direction": change_direction,
        "change_pct": change_pct,
        "top_n": top_n,
        "baseline_candidate_count": baseline_count,
        "scenario_candidate_count": scenario_count,
        "spearman_rank_corr": corr,
        "top_n_overlap_count": overlap,
        "top_n_overlap_ratio": overlap_ratio,
        "max_abs_rank_change": max_rank_change,
        "mean_abs_score_change": mean_score_change,
        "warning": warning,
    }


def _month_end_signal_dates(
    connection: duckdb.DuckDBPyConnection,
    start: date,
    end: date,
) -> list[date]:
    frame = connection.execute(
        """
        SELECT trade_date
        FROM trading_calendar
        WHERE is_open = true
          AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        [start, end],
    ).df()
    if frame.empty:
        return []
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame["year_month"] = pd.to_datetime(frame["trade_date"]).dt.to_period("M")
    grouped = frame.groupby("year_month", sort=True)["trade_date"].max()
    return [value for value in grouped.tolist()]


def _yearly_metrics(subset: pd.DataFrame) -> dict[str, float]:
    if subset.empty:
        return {
            "rank_ic_mean": np.nan,
            "rank_ic_std": np.nan,
            "rank_icir": np.nan,
            "top_bottom_spread_mean": np.nan,
            "positive_rank_ic_rate": np.nan,
        }
    ics: list[float] = []
    spreads: list[float] = []
    for _, group in subset.groupby("trade_date", sort=True):
        clean = group.loc[
            pd.notna(group["total_score"]) & pd.notna(group["forward_return"]),
            ["stock_code", "total_score", "forward_return"],
        ].copy()
        if len(clean) >= 2:
            score_rank = clean["total_score"].rank(method="average")
            return_rank = clean["forward_return"].rank(method="average")
            if score_rank.std(ddof=0) > 0 and return_rank.std(ddof=0) > 0:
                ics.append(float(score_rank.corr(return_rank, method="pearson")))
            spreads.append(_top_bottom_spread(clean))
    ic_series = pd.Series(ics, dtype=float)
    spread_series = pd.Series(spreads, dtype=float).dropna()
    std = ic_series.std(ddof=1) if len(ic_series) >= 2 else np.nan
    return {
        "rank_ic_mean": float(ic_series.mean()) if not ic_series.empty else np.nan,
        "rank_ic_std": float(std) if not pd.isna(std) else np.nan,
        "rank_icir": float(ic_series.mean() / std) if not pd.isna(std) and std != 0 else np.nan,
        "top_bottom_spread_mean": float(spread_series.mean()) if not spread_series.empty else np.nan,
        "positive_rank_ic_rate": float((ic_series > 0).mean()) if not ic_series.empty else np.nan,
    }


def _spearman_corr(left: pd.Series, right: pd.Series) -> float:
    left_rank = left.rank(method="average")
    right_rank = right.rank(method="average")
    if left_rank.std(ddof=0) == 0 or right_rank.std(ddof=0) == 0:
        return np.nan
    return float(left_rank.corr(right_rank, method="pearson"))


def _top_bottom_spread(clean: pd.DataFrame) -> float:
    sorted_frame = clean.sort_values(
        ["total_score", "stock_code"],
        ascending=[True, True],
        kind="mergesort",
    )
    n = len(sorted_frame)
    if n < 2:
        return np.nan
    group_size = max(1, n // 5)
    bottom = sorted_frame.head(group_size)["forward_return"].astype(float)
    top = sorted_frame.tail(group_size)["forward_return"].astype(float)
    return float(top.mean() - bottom.mean())


def _passed_stock_codes(result: CompositeScoreResult) -> tuple[str, ...]:
    if result.score_breakdown.empty:
        return tuple(str(code) for code in result.scored_candidates["stock_code"].tolist())
    return tuple(
        sorted(str(code) for code in result.score_breakdown["stock_code"].drop_duplicates().tolist())
    )


def _metadata_value(result: CompositeScoreResult, key: str) -> object:
    for frame in [result.factor_normalized_scores, result.score_breakdown, result.scored_candidates]:
        if not frame.empty and key in frame.columns:
            return frame.iloc[0][key]
    if key == "as_of_date":
        return date(1970, 1, 1)
    return ""


def _join_warning(existing: str, new: str) -> str:
    if existing and new:
        return existing + "; " + new
    return existing or new


def _mapping(value: object, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping.")
    return value
