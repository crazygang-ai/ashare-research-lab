"""Composite scoring engine for Phase 3."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb
import pandas as pd

from ashare.pit.asof import (
    DateLike,
    parse_as_of_date,
    query_industry_classifications_as_of,
    query_securities_as_of,
)
from ashare.scoring.config import (
    GROUP_SCORE_COLUMNS,
    enabled_hard_filter_names,
    enabled_risk_penalty_factors,
    enabled_scoring_factors,
    is_strict_mode,
)
from ashare.scoring.filters import HARD_FILTER_EXCLUSION_COLUMNS, apply_hard_filters
from ashare.scoring.loaders import load_score_inputs
from ashare.scoring.normalization import normalize_factor_scores
from ashare.scoring.validation_gate import ValidationGateResult, VALIDATION_GATE_COLUMNS


SCORED_CANDIDATE_COLUMNS = [
    "rank",
    "stock_code",
    "stock_name",
    "industry_l1",
    "industry_l2",
    "as_of_date",
    "source_run_id",
    "index_code",
    "total_score",
    "positive_score",
    "financial_score",
    "valuation_score",
    "momentum_score",
    "event_score",
    "risk_penalty",
    "hard_filter_passed",
    "selection_reason",
    "risk_tips",
]

SCORE_BREAKDOWN_COLUMNS = [
    "as_of_date",
    "source_run_id",
    "index_code",
    "stock_code",
    "score_group",
    "group_enabled",
    "group_required",
    "group_weight",
    "group_score",
    "weighted_contribution",
    "available_factor_weight",
    "missing_factor_count",
]

FACTOR_NORMALIZED_COLUMNS = [
    "as_of_date",
    "source_run_id",
    "index_code",
    "stock_code",
    "factor_name",
    "score_role",
    "score_group",
    "raw_factor_value",
    "direction",
    "normalized_score",
    "factor_weight",
    "weighted_contribution",
    "validation_status",
]

NO_RISK_TIPS = "未触发本阶段软风险扣分"


@dataclass(frozen=True)
class CompositeScoreResult:
    scored_candidates: pd.DataFrame
    score_breakdown: pd.DataFrame
    factor_normalized_scores: pd.DataFrame
    hard_filter_exclusions: pd.DataFrame
    validation_gate: pd.DataFrame
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ScoreComputation:
    scored_candidates_all: pd.DataFrame
    score_breakdown: pd.DataFrame
    factor_normalized_scores: pd.DataFrame
    warnings: tuple[str, ...]


def compute_composite_scores(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    source_run_id: str,
    index_code: str,
    scoring_config: Mapping[str, object],
    data_dictionary: Mapping[str, object],
    validation_gate: ValidationGateResult,
    top_n: int | None = None,
    data_source: str | None = None,
) -> CompositeScoreResult:
    """Compute one-day Phase 3 composite scores from stored factor values."""
    score_date = parse_as_of_date(as_of_date)
    if not source_run_id or not str(source_run_id).strip():
        raise ValueError("source_run_id must be explicitly provided.")
    if not index_code or not str(index_code).strip():
        raise ValueError("index_code must be explicitly provided.")
    resolved_top_n = _resolved_top_n(scoring_config, top_n)

    positive_factors, risk_factors, eligibility_warnings = _eligible_configured_factors(
        scoring_config,
        validation_gate,
    )
    if not positive_factors:
        raise ValueError("No eligible positive scoring factors remained after validation gate.")

    hard_filter_names = enabled_hard_filter_names(scoring_config)
    factor_values = load_score_inputs(
        connection=connection,
        as_of_date=score_date,
        source_run_id=source_run_id,
        index_code=index_code,
        factor_names=[*positive_factors, *risk_factors],
        hard_filter_names=hard_filter_names,
        data_source=data_source,
    )
    universe_source = str(factor_values.attrs.get("universe_source", "unknown"))
    universe_warnings = []
    if universe_source != "factor_run_universe":
        universe_warnings.append(
            "Score used PIT universe fallback because factor_run_universe was missing."
        )
    universe = factor_values.attrs.get("universe", pd.DataFrame(columns=["stock_code"]))
    hard_filter_result = apply_hard_filters(
        factor_values=factor_values,
        universe=universe,
        as_of_date=score_date,
        source_run_id=source_run_id,
        index_code=index_code,
        scoring_config=scoring_config,
    )
    if not hard_filter_result.passed_stock_codes:
        warnings = tuple(
            [
                *eligibility_warnings,
                "No stocks remained after hard filters.",
            ]
        )
        return CompositeScoreResult(
            scored_candidates=_empty_scored_candidates(),
            score_breakdown=_empty_score_breakdown(),
            factor_normalized_scores=_empty_factor_normalized_scores(),
            hard_filter_exclusions=hard_filter_result.exclusions,
            validation_gate=_ordered_validation_gate(validation_gate.table),
            warnings=warnings,
        )

    passed_values = factor_values[
        factor_values["stock_code"].isin(hard_filter_result.passed_stock_codes)
        & factor_values["factor_name"].isin([*positive_factors, *risk_factors])
    ].copy()
    normalized = normalize_factor_scores(
        passed_values,
        data_dictionary=data_dictionary,
        scoring_config=scoring_config,
    )
    normalized = _decorate_normalized_scores(
        normalized=normalized,
        scoring_config=scoring_config,
        positive_factors=positive_factors,
        risk_factors=risk_factors,
        as_of_date=score_date,
        source_run_id=source_run_id,
        index_code=index_code,
    )
    computation = _compute_scores_from_normalized(
        normalized=normalized,
        passed_stock_codes=hard_filter_result.passed_stock_codes,
        scoring_config=scoring_config,
        as_of_date=score_date,
        source_run_id=source_run_id,
        index_code=index_code,
    )
    enriched = _enrich_candidates(
        connection=connection,
        as_of_date=score_date,
        candidates=computation.scored_candidates_all,
        data_source=data_source,
    )
    scored = enriched.sort_values(
        ["total_score", "stock_code"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    scored["rank"] = range(1, len(scored) + 1)
    scored["selection_reason"] = scored.apply(_selection_reason, axis=1)
    scored["risk_tips"] = scored["risk_penalty"].map(_risk_tips)
    scored = scored.loc[:, SCORED_CANDIDATE_COLUMNS]
    if resolved_top_n is not None:
        scored = scored.head(resolved_top_n).reset_index(drop=True)

    return CompositeScoreResult(
        scored_candidates=scored,
        score_breakdown=computation.score_breakdown,
        factor_normalized_scores=computation.factor_normalized_scores,
        hard_filter_exclusions=hard_filter_result.exclusions,
        validation_gate=_ordered_validation_gate(validation_gate.table),
        warnings=tuple(dict.fromkeys([*eligibility_warnings, *universe_warnings, *computation.warnings])),
    )


def compute_scores_from_normalized(
    normalized: pd.DataFrame,
    passed_stock_codes: tuple[str, ...],
    scoring_config: Mapping[str, object],
    as_of_date: DateLike,
    source_run_id: str,
    index_code: str,
) -> pd.DataFrame:
    """Recompute total scores from normalized factor rows for diagnostics."""
    computation = _compute_scores_from_normalized(
        normalized=normalized,
        passed_stock_codes=passed_stock_codes,
        scoring_config=scoring_config,
        as_of_date=parse_as_of_date(as_of_date),
        source_run_id=source_run_id,
        index_code=index_code,
    )
    return computation.scored_candidates_all


def _eligible_configured_factors(
    scoring_config: Mapping[str, object],
    validation_gate: ValidationGateResult,
) -> tuple[list[str], list[str], tuple[str, ...]]:
    eligible = set(validation_gate.eligible_factors)
    positive = enabled_scoring_factors(scoring_config)
    risk = enabled_risk_penalty_factors(scoring_config)
    missing = [name for name in [*positive, *risk] if name not in eligible]
    if missing and is_strict_mode(scoring_config):
        raise ValueError(
            "Validation gate failed for enabled scoring factor(s): " + ", ".join(missing)
        )
    warnings = tuple(f"Skipping factor that did not pass validation gate: {name}" for name in missing)
    return (
        [name for name in positive if name in eligible],
        [name for name in risk if name in eligible],
        warnings,
    )


def _decorate_normalized_scores(
    normalized: pd.DataFrame,
    scoring_config: Mapping[str, object],
    positive_factors: list[str],
    risk_factors: list[str],
    as_of_date: date,
    source_run_id: str,
    index_code: str,
) -> pd.DataFrame:
    if normalized.empty:
        return _empty_factor_normalized_scores()
    role_by_factor = {name: "positive" for name in positive_factors}
    role_by_factor.update({name: "risk_penalty" for name in risk_factors})
    group_by_factor = _group_by_factor(scoring_config)
    weight_by_factor = _factor_weight_by_factor(scoring_config)

    result = normalized.copy()
    result["as_of_date"] = as_of_date
    result["source_run_id"] = source_run_id
    result["index_code"] = index_code
    result["score_role"] = result["factor_name"].map(role_by_factor)
    result["score_group"] = result["factor_name"].map(group_by_factor)
    result["factor_weight"] = result["factor_name"].map(weight_by_factor).astype(float)
    result["weighted_contribution"] = result["normalized_score"] * result["factor_weight"]
    result["validation_status"] = "PASS"
    return result.loc[:, FACTOR_NORMALIZED_COLUMNS]


def _compute_scores_from_normalized(
    normalized: pd.DataFrame,
    passed_stock_codes: tuple[str, ...],
    scoring_config: Mapping[str, object],
    as_of_date: date,
    source_run_id: str,
    index_code: str,
) -> _ScoreComputation:
    min_available = float(
        _mapping(scoring_config.get("score", {}), "score").get("min_available_factor_weight", 0.5)
    )
    groups = _all_groups(scoring_config)
    group_factor_weights = _group_factor_weights(scoring_config)
    group_weights = _group_weights(scoring_config)
    group_required = _group_required(scoring_config)
    risk_factor_weights = _risk_factor_weights(scoring_config)
    risk_max_penalty = float(
        _mapping(scoring_config.get("risk_penalty", {}), "risk_penalty").get("max_penalty", 0.0)
    )
    risk_enabled = bool(
        _mapping(scoring_config.get("risk_penalty", {}), "risk_penalty").get("enabled", True)
    )

    normalized_lookup = {
        (str(row.stock_code), str(row.factor_name)): row
        for row in normalized.itertuples(index=False)
    }
    score_rows: list[dict[str, object]] = []
    breakdown_rows: list[dict[str, object]] = []
    contribution_by_key: dict[tuple[str, str], float] = {}
    warnings: list[str] = []
    no_risk_warning_added = False

    for stock_code in passed_stock_codes:
        group_scores: dict[str, float] = {}
        group_available_weights: dict[str, float] = {}
        required_group_failed = False
        for group_name, group in groups.items():
            group_enabled = bool(group.get("enabled", False))
            required = group_required[group_name]
            group_weight = group_weights[group_name]
            factor_weights = group_factor_weights.get(group_name, {})
            if not group_enabled:
                breakdown_rows.append(
                    _breakdown_row(
                        as_of_date,
                        source_run_id,
                        index_code,
                        stock_code,
                        group_name,
                        group_enabled=False,
                        group_required=required,
                        group_weight=group_weight,
                        group_score=float("nan"),
                        weighted_contribution=0.0,
                        available_factor_weight=0.0,
                        missing_factor_count=0,
                    )
                )
                continue

            available_weight = 0.0
            weighted_sum = 0.0
            missing_count = 0
            for factor_name, factor_weight in factor_weights.items():
                row = normalized_lookup.get((stock_code, factor_name))
                if row is None or pd.isna(row.normalized_score):
                    missing_count += 1
                    continue
                available_weight += factor_weight
                weighted_sum += float(row.normalized_score) * factor_weight

            if available_weight >= min_available and available_weight > 0:
                group_score = _clamp(weighted_sum / available_weight, 0.0, 100.0)
                weighted_contribution = group_score * group_weight
                group_scores[group_name] = group_score
                group_available_weights[group_name] = group_weight
            else:
                group_score = float("nan")
                weighted_contribution = float("nan")
                if required:
                    required_group_failed = True

            breakdown_rows.append(
                _breakdown_row(
                    as_of_date,
                    source_run_id,
                    index_code,
                    stock_code,
                    group_name,
                    group_enabled=group_enabled,
                    group_required=required,
                    group_weight=group_weight,
                    group_score=group_score,
                    weighted_contribution=weighted_contribution,
                    available_factor_weight=available_weight,
                    missing_factor_count=missing_count,
                )
            )

        if required_group_failed:
            warnings.append(
                f"{stock_code}: excluded because a required group lacks enough factor weight."
            )
            continue
        positive_score = _positive_score(group_scores, group_available_weights)
        if pd.isna(positive_score):
            warnings.append(f"{stock_code}: excluded because no enabled score group is available.")
            continue

        risk_penalty, risk_contrib, risk_warning = _risk_penalty(
            stock_code=stock_code,
            normalized_lookup=normalized_lookup,
            risk_factor_weights=risk_factor_weights if risk_enabled else {},
            max_penalty=risk_max_penalty,
            min_available=min_available,
        )
        contribution_by_key.update(risk_contrib)
        if risk_warning:
            if risk_warning == "No eligible soft risk penalty factors.":
                if not no_risk_warning_added:
                    warnings.append(risk_warning + " risk_penalty set to 0.0.")
                    no_risk_warning_added = True
            else:
                warnings.append(f"{stock_code}: {risk_warning}")

        total_score = _clamp(float(positive_score) - risk_penalty, 0.0, 100.0)
        row: dict[str, object] = {
            "rank": 0,
            "stock_code": stock_code,
            "stock_name": pd.NA,
            "industry_l1": pd.NA,
            "industry_l2": pd.NA,
            "as_of_date": as_of_date,
            "source_run_id": source_run_id,
            "index_code": index_code,
            "total_score": total_score,
            "positive_score": _clamp(float(positive_score), 0.0, 100.0),
            "risk_penalty": risk_penalty,
            "hard_filter_passed": True,
            "selection_reason": "",
            "risk_tips": "",
        }
        for group_name, column_name in GROUP_SCORE_COLUMNS.items():
            row[column_name] = group_scores.get(group_name, float("nan"))
        score_rows.append(row)

    factor_scores = normalized.copy()
    if not factor_scores.empty:
        for index, row in factor_scores.iterrows():
            if row["score_role"] == "risk_penalty":
                factor_scores.at[index, "weighted_contribution"] = contribution_by_key.get(
                    (str(row["stock_code"]), str(row["factor_name"])),
                    0.0,
                )
    score_breakdown = pd.DataFrame(breakdown_rows, columns=SCORE_BREAKDOWN_COLUMNS)
    if not score_breakdown.empty:
        score_breakdown = score_breakdown.sort_values(
            ["stock_code", "score_group"],
            kind="mergesort",
        ).reset_index(drop=True)
    scored = pd.DataFrame(score_rows, columns=SCORED_CANDIDATE_COLUMNS)
    if not scored.empty:
        scored = scored.sort_values(
            ["total_score", "stock_code"],
            ascending=[False, True],
            kind="mergesort",
        ).reset_index(drop=True)
        scored["rank"] = range(1, len(scored) + 1)
    factor_scores = factor_scores.loc[:, FACTOR_NORMALIZED_COLUMNS]
    if not factor_scores.empty:
        if scored.empty:
            factor_scores = factor_scores.iloc[0:0].copy()
        else:
            factor_scores = factor_scores[factor_scores["stock_code"].isin(scored["stock_code"])]
        factor_scores = factor_scores.sort_values(
            ["stock_code", "score_group", "factor_name"],
            kind="mergesort",
        ).reset_index(drop=True)
    return _ScoreComputation(
        scored_candidates_all=scored,
        score_breakdown=score_breakdown,
        factor_normalized_scores=factor_scores,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _risk_penalty(
    stock_code: str,
    normalized_lookup: Mapping[tuple[str, str], Any],
    risk_factor_weights: Mapping[str, float],
    max_penalty: float,
    min_available: float,
) -> tuple[float, dict[tuple[str, str], float], str | None]:
    if not risk_factor_weights:
        return 0.0, {}, "No eligible soft risk penalty factors."
    available_weight = 0.0
    available: list[tuple[str, float, float]] = []
    for factor_name, factor_weight in risk_factor_weights.items():
        row = normalized_lookup.get((stock_code, factor_name))
        if row is None or pd.isna(row.normalized_score):
            continue
        available_weight += factor_weight
        available.append((factor_name, float(row.normalized_score), factor_weight))
    if available_weight < min_available or available_weight <= 0:
        return 0.0, {}, "soft risk factors missing or below available-weight threshold"

    contributions: dict[tuple[str, str], float] = {}
    penalty = 0.0
    for factor_name, severity, factor_weight in available:
        renormalized_weight = factor_weight / available_weight
        contribution = severity / 100.0 * max_penalty * renormalized_weight
        contributions[(stock_code, factor_name)] = contribution
        penalty += contribution
    return min(max_penalty, penalty), contributions, None


def _positive_score(
    group_scores: Mapping[str, float],
    available_group_weights: Mapping[str, float],
) -> float:
    available_weight = sum(available_group_weights.values())
    if available_weight <= 0:
        return float("nan")
    weighted_sum = sum(group_scores[name] * available_group_weights[name] for name in group_scores)
    return weighted_sum / available_weight


def _enrich_candidates(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: date,
    candidates: pd.DataFrame,
    data_source: str | None,
) -> pd.DataFrame:
    result = candidates.copy()
    if result.empty:
        return result
    securities = query_securities_as_of(
        connection,
        as_of_date,
        include_delisted=True,
        source=data_source,
    )
    if not securities.empty:
        securities = securities.loc[:, ["stock_code", "stock_name"]].drop_duplicates(
            "stock_code",
            keep="first",
        )
        result = result.drop(columns=["stock_name"], errors="ignore").merge(
            securities,
            on="stock_code",
            how="left",
        )
    industries = query_industry_classifications_as_of(
        connection,
        as_of_date,
        source=data_source,
    )
    if not industries.empty:
        industries = industries.loc[:, ["stock_code", "industry_l1", "industry_l2"]]
        industries = industries.drop_duplicates("stock_code", keep="first")
        result = result.drop(columns=["industry_l1", "industry_l2"], errors="ignore").merge(
            industries,
            on="stock_code",
            how="left",
        )
    for column in ["stock_name", "industry_l1", "industry_l2"]:
        if column not in result.columns:
            result[column] = pd.NA
    return result


def _selection_reason(row: pd.Series) -> str:
    return (
        f"综合评分排名第 {int(row['rank'])}；total_score={float(row['total_score']):.4f}；"
        "硬过滤均通过；仅通过验证门槛的因子进入评分。"
    )


def _risk_tips(risk_penalty: object) -> str:
    try:
        penalty = float(risk_penalty)
    except (TypeError, ValueError):
        penalty = 0.0
    if penalty > 0:
        return f"软风险扣分 {penalty:.4f} 分"
    return NO_RISK_TIPS


def _resolved_top_n(scoring_config: Mapping[str, object], top_n: int | None) -> int | None:
    if top_n is not None:
        if top_n < 0:
            raise ValueError("top_n must be non-negative.")
        return top_n
    score = _mapping(scoring_config.get("score", {}), "score")
    configured = int(score.get("top_n", 20))
    if configured < 0:
        raise ValueError("score.top_n must be non-negative.")
    return configured


def _all_groups(scoring_config: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    groups = scoring_config.get("groups")
    if not isinstance(groups, Mapping):
        raise ValueError("groups must be a mapping.")
    return {
        str(name): _mapping(entry, f"groups.{name}")
        for name, entry in groups.items()
    }


def _group_by_factor(scoring_config: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for group_name, group in _all_groups(scoring_config).items():
        factors = _mapping(group.get("factors", {}), f"groups.{group_name}.factors")
        for factor_name, entry in factors.items():
            factor = _mapping(entry, f"groups.{group_name}.factors.{factor_name}")
            if bool(group.get("enabled", False)) and bool(factor.get("enabled", False)):
                result[str(factor_name)] = group_name
    risk = _mapping(scoring_config.get("risk_penalty", {}), "risk_penalty")
    risk_factors = _mapping(risk.get("factors", {}), "risk_penalty.factors")
    for factor_name, entry in risk_factors.items():
        factor = _mapping(entry, f"risk_penalty.factors.{factor_name}")
        if bool(risk.get("enabled", True)) and bool(factor.get("enabled", True)):
            result[str(factor_name)] = "risk"
    return result


def _factor_weight_by_factor(scoring_config: Mapping[str, object]) -> dict[str, float]:
    result: dict[str, float] = {}
    for group_name, factors in _group_factor_weights(scoring_config).items():
        _ = group_name
        result.update(factors)
    result.update(_risk_factor_weights(scoring_config))
    return result


def _group_factor_weights(scoring_config: Mapping[str, object]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for group_name, group in _all_groups(scoring_config).items():
        factors = _mapping(group.get("factors", {}), f"groups.{group_name}.factors")
        enabled: dict[str, float] = {}
        for factor_name, entry in factors.items():
            factor = _mapping(entry, f"groups.{group_name}.factors.{factor_name}")
            if bool(group.get("enabled", False)) and bool(factor.get("enabled", False)):
                enabled[str(factor_name)] = float(factor.get("weight", 0.0))
        result[group_name] = enabled
    return result


def _risk_factor_weights(scoring_config: Mapping[str, object]) -> dict[str, float]:
    risk = _mapping(scoring_config.get("risk_penalty", {}), "risk_penalty")
    if not bool(risk.get("enabled", True)):
        return {}
    factors = _mapping(risk.get("factors", {}), "risk_penalty.factors")
    result: dict[str, float] = {}
    for factor_name, entry in factors.items():
        factor = _mapping(entry, f"risk_penalty.factors.{factor_name}")
        if bool(factor.get("enabled", True)):
            result[str(factor_name)] = float(factor.get("weight", 0.0))
    return result


def _group_weights(scoring_config: Mapping[str, object]) -> dict[str, float]:
    return {
        name: float(group.get("weight", 0.0)) if bool(group.get("enabled", False)) else 0.0
        for name, group in _all_groups(scoring_config).items()
    }


def _group_required(scoring_config: Mapping[str, object]) -> dict[str, bool]:
    return {
        name: bool(group.get("required", False))
        for name, group in _all_groups(scoring_config).items()
    }


def _breakdown_row(
    as_of_date: date,
    source_run_id: str,
    index_code: str,
    stock_code: str,
    score_group: str,
    group_enabled: bool,
    group_required: bool,
    group_weight: float,
    group_score: float,
    weighted_contribution: float,
    available_factor_weight: float,
    missing_factor_count: int,
) -> dict[str, object]:
    return {
        "as_of_date": as_of_date,
        "source_run_id": source_run_id,
        "index_code": index_code,
        "stock_code": stock_code,
        "score_group": score_group,
        "group_enabled": group_enabled,
        "group_required": group_required,
        "group_weight": group_weight,
        "group_score": group_score,
        "weighted_contribution": weighted_contribution,
        "available_factor_weight": available_factor_weight,
        "missing_factor_count": missing_factor_count,
    }


def _ordered_validation_gate(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in VALIDATION_GATE_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, VALIDATION_GATE_COLUMNS]
    if not result.empty:
        result = result.sort_values(
            ["score_role", "score_group", "factor_name"],
            kind="mergesort",
        )
    return result.reset_index(drop=True)


def _mapping(value: object, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping.")
    return value


def _clamp(value: float, lower: float, upper: float) -> float:
    if pd.isna(value):
        return value
    return min(max(float(value), lower), upper)


def _empty_scored_candidates() -> pd.DataFrame:
    return pd.DataFrame(columns=SCORED_CANDIDATE_COLUMNS)


def _empty_score_breakdown() -> pd.DataFrame:
    return pd.DataFrame(columns=SCORE_BREAKDOWN_COLUMNS)


def _empty_factor_normalized_scores() -> pd.DataFrame:
    return pd.DataFrame(columns=FACTOR_NORMALIZED_COLUMNS)


def _empty_hard_filter_exclusions() -> pd.DataFrame:
    return pd.DataFrame(columns=HARD_FILTER_EXCLUSION_COLUMNS)
