"""Validation gate for Phase 3 composite scoring factors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ashare.scoring.config import (
    all_configured_score_items,
    enabled_hard_filter_names,
)


VALIDATION_ARTIFACT_FILES = {
    "coverage": "coverage.csv",
    "rank_ic": "rank_ic.csv",
    "ic_summary": "ic_summary.csv",
    "group_returns": "group_returns.csv",
    "decay_curve": "decay_curve.csv",
}

VALIDATION_GATE_COLUMNS = [
    "factor_name",
    "score_role",
    "score_group",
    "configured_enabled",
    "validation_status",
    "reason",
    "required_horizons",
    "coverage",
    "valid_oriented_ic_dates",
    "mean_oriented_rank_ic",
    "oriented_icir",
    "group_return_rows",
]


@dataclass(frozen=True)
class ValidationGateResult:
    eligible_factors: frozenset[str]
    table: pd.DataFrame
    warnings: tuple[str, ...] = ()


def load_validation_artifacts(validation_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load Phase 1a-6 validation report CSV artifacts."""
    path = Path(validation_dir)
    artifacts: dict[str, pd.DataFrame] = {}
    for key, filename in VALIDATION_ARTIFACT_FILES.items():
        artifact_path = path / filename
        if not artifact_path.exists():
            raise FileNotFoundError(f"Missing validation artifact: {artifact_path}")
        artifacts[key] = pd.read_csv(artifact_path)
    return artifacts


def evaluate_validation_gate(
    artifacts: Mapping[str, pd.DataFrame],
    scoring_config: Mapping[str, object],
    data_dictionary: Mapping[str, object],
) -> ValidationGateResult:
    """Evaluate configured scoring factors against validation report thresholds."""
    _validate_artifact_columns(artifacts)
    factors = _factor_metadata(data_dictionary)
    hard_filter_names = set(enabled_hard_filter_names(scoring_config))
    required_horizons = _required_horizons(scoring_config)
    gate = _gate_config(scoring_config)
    min_coverage = float(gate.get("min_coverage", 0.2))
    min_valid_dates = int(gate.get("min_valid_oriented_ic_dates", 1))
    min_mean_ic = float(gate.get("min_mean_oriented_rank_ic", 0.0))
    min_icir = float(gate.get("min_oriented_icir", -999.0))
    require_group_rows = bool(gate.get("require_group_return_rows", True))

    coverage_by_factor = _coverage_by_factor(artifacts["coverage"])
    ic_summary = _normalized_ic_summary(artifacts["ic_summary"])
    group_rows = _group_return_rows_by_factor_horizon(artifacts["group_returns"])

    rows: list[dict[str, object]] = []
    eligible: set[str] = set()
    warnings: list[str] = []
    seen_role_by_factor: dict[str, str] = {}
    items = all_configured_score_items(scoring_config)

    for item in items:
        factor_name = str(item["factor_name"])
        score_role = str(item["score_role"])
        score_group = str(item["score_group"])
        configured_enabled = bool(item["configured_enabled"])

        reason_parts: list[str] = []
        status = "PASS"
        coverage = coverage_by_factor.get(factor_name, float("nan"))
        horizon_metrics = _horizon_metrics(
            ic_summary=ic_summary,
            group_rows=group_rows,
            factor_name=factor_name,
            required_horizons=required_horizons,
        )

        if not configured_enabled:
            status = "SKIP"
            reason_parts.append("configured disabled")
        else:
            previous_role = seen_role_by_factor.get(factor_name)
            if previous_role is not None and previous_role != score_role:
                status = "FAIL"
                reason_parts.append("factor used in multiple score roles")
            seen_role_by_factor[factor_name] = score_role

            entry = factors.get(factor_name)
            if entry is None:
                status = "FAIL"
                reason_parts.append("factor missing from data dictionary")
            else:
                factor_type = str(entry.get("type", ""))
                direction = entry.get("direction")
                if factor_type == "hard_filter":
                    status = "FAIL"
                    reason_parts.append("hard_filter factors cannot be scored")
                if factor_name in hard_filter_names:
                    status = "FAIL"
                    reason_parts.append("factor is configured as a hard filter")
                if not isinstance(direction, str) or not direction:
                    status = "FAIL"
                    reason_parts.append("missing direction")
                if score_role == "positive":
                    group = entry.get("score_group")
                    if not isinstance(group, str) and not score_group:
                        status = "FAIL"
                        reason_parts.append("missing score_group")

            if pd.isna(coverage):
                status = "FAIL"
                reason_parts.append("factor missing from coverage.csv")
            elif float(coverage) < min_coverage:
                status = "FAIL"
                reason_parts.append(
                    f"coverage {float(coverage):.6g} below minimum {min_coverage:.6g}"
                )

            for horizon in required_horizons:
                metrics = horizon_metrics.get(horizon)
                if metrics is None:
                    status = "FAIL"
                    reason_parts.append(f"missing ic_summary horizon {horizon}")
                    continue
                valid_dates = metrics["valid_oriented_ic_dates"]
                mean_ic = metrics["mean_oriented_rank_ic"]
                icir = metrics["oriented_icir"]
                if pd.isna(valid_dates) or int(valid_dates) < min_valid_dates:
                    status = "FAIL"
                    reason_parts.append(
                        f"horizon {horizon} valid_oriented_ic_dates below minimum"
                    )
                if pd.isna(mean_ic) or float(mean_ic) < min_mean_ic:
                    status = "FAIL"
                    reason_parts.append(
                        f"horizon {horizon} mean_oriented_rank_ic below minimum"
                    )
                if pd.isna(icir):
                    if min_icir > -999.0:
                        status = "FAIL"
                        reason_parts.append(f"horizon {horizon} oriented_icir is missing")
                elif float(icir) < min_icir:
                    status = "FAIL"
                    reason_parts.append(f"horizon {horizon} oriented_icir below minimum")

                rows_for_horizon = int(group_rows.get((factor_name, horizon), 0))
                if require_group_rows and rows_for_horizon <= 0:
                    status = "FAIL"
                    reason_parts.append(f"horizon {horizon} missing group_returns rows")

        valid_dates_values = [
            metrics["valid_oriented_ic_dates"]
            for metrics in horizon_metrics.values()
            if not pd.isna(metrics["valid_oriented_ic_dates"])
        ]
        mean_ic_values = [
            metrics["mean_oriented_rank_ic"]
            for metrics in horizon_metrics.values()
            if not pd.isna(metrics["mean_oriented_rank_ic"])
        ]
        icir_values = [
            metrics["oriented_icir"]
            for metrics in horizon_metrics.values()
            if not pd.isna(metrics["oriented_icir"])
        ]
        group_return_total = sum(
            int(group_rows.get((factor_name, horizon), 0)) for horizon in required_horizons
        )

        if configured_enabled and status == "PASS":
            eligible.add(factor_name)
        if configured_enabled and status != "PASS":
            warnings.append(f"{factor_name}: {'; '.join(reason_parts)}")

        rows.append(
            {
                "factor_name": factor_name,
                "score_role": score_role,
                "score_group": score_group,
                "configured_enabled": configured_enabled,
                "validation_status": status,
                "reason": "; ".join(dict.fromkeys(reason_parts)) if reason_parts else "passed",
                "required_horizons": ",".join(str(item) for item in required_horizons),
                "coverage": coverage,
                "valid_oriented_ic_dates": min(valid_dates_values)
                if valid_dates_values
                else float("nan"),
                "mean_oriented_rank_ic": min(mean_ic_values) if mean_ic_values else float("nan"),
                "oriented_icir": min(icir_values) if icir_values else float("nan"),
                "group_return_rows": group_return_total,
            }
        )

    table = pd.DataFrame(rows, columns=VALIDATION_GATE_COLUMNS)
    if not table.empty:
        table = table.sort_values(
            ["score_role", "score_group", "factor_name"],
            kind="mergesort",
        ).reset_index(drop=True)
    return ValidationGateResult(
        eligible_factors=frozenset(eligible),
        table=table,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _validate_artifact_columns(artifacts: Mapping[str, pd.DataFrame]) -> None:
    missing_artifacts = sorted(set(VALIDATION_ARTIFACT_FILES).difference(artifacts))
    if missing_artifacts:
        raise ValueError(f"Missing validation artifact(s): {', '.join(missing_artifacts)}")
    required_columns = {
        "coverage": {"factor_name", "coverage"},
        "rank_ic": {"factor_name", "horizon"},
        "ic_summary": {
            "factor_name",
            "horizon",
            "valid_oriented_ic_dates",
            "mean_oriented_rank_ic",
            "oriented_icir",
        },
        "group_returns": {"factor_name", "horizon"},
        "decay_curve": {"factor_name", "horizon"},
    }
    for key, columns in required_columns.items():
        frame = artifacts[key]
        missing = sorted(columns.difference(frame.columns))
        if missing:
            raise ValueError(f"{key}.csv missing required column(s): {', '.join(missing)}")


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


def _gate_config(scoring_config: Mapping[str, object]) -> Mapping[str, object]:
    gate = scoring_config.get("validation_gate")
    if not isinstance(gate, Mapping):
        raise ValueError("validation_gate must be a mapping.")
    return gate


def _required_horizons(scoring_config: Mapping[str, object]) -> list[int]:
    gate = _gate_config(scoring_config)
    horizons = gate.get("required_horizons", [20])
    if not isinstance(horizons, list):
        raise ValueError("validation_gate.required_horizons must be a list.")
    parsed = [int(value) for value in horizons]
    if not parsed:
        raise ValueError("validation_gate.required_horizons cannot be empty.")
    return parsed


def _coverage_by_factor(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    clean = frame.copy()
    clean["coverage"] = pd.to_numeric(clean["coverage"], errors="coerce")
    grouped = clean.groupby("factor_name", sort=True)["coverage"].mean()
    return {str(key): float(value) for key, value in grouped.items()}


def _normalized_ic_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    result["horizon"] = pd.to_numeric(result["horizon"], errors="coerce").astype("Int64")
    for column in [
        "valid_oriented_ic_dates",
        "mean_oriented_rank_ic",
        "oriented_icir",
    ]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _group_return_rows_by_factor_horizon(frame: pd.DataFrame) -> dict[tuple[str, int], int]:
    if frame.empty:
        return {}
    clean = frame.copy()
    clean["horizon"] = pd.to_numeric(clean["horizon"], errors="coerce").astype("Int64")
    grouped = clean.groupby(["factor_name", "horizon"], dropna=True).size()
    return {(str(factor), int(horizon)): int(count) for (factor, horizon), count in grouped.items()}


def _horizon_metrics(
    ic_summary: pd.DataFrame,
    group_rows: Mapping[tuple[str, int], int],
    factor_name: str,
    required_horizons: list[int],
) -> dict[int, dict[str, Any]]:
    _ = group_rows
    metrics: dict[int, dict[str, Any]] = {}
    if ic_summary.empty:
        return metrics
    factor_rows = ic_summary[ic_summary["factor_name"].astype(str) == factor_name]
    for horizon in required_horizons:
        horizon_rows = factor_rows[factor_rows["horizon"] == horizon]
        if horizon_rows.empty:
            continue
        row = horizon_rows.iloc[0]
        metrics[horizon] = {
            "valid_oriented_ic_dates": row["valid_oriented_ic_dates"],
            "mean_oriented_rank_ic": row["mean_oriented_rank_ic"],
            "oriented_icir": row["oriented_icir"],
        }
    return metrics
