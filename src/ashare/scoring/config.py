"""Configuration helpers for Phase 3 composite scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml


DEFAULT_SCORING_CONFIG_PATH = Path("configs/scoring.yaml")
GROUP_SCORE_COLUMNS = {
    "financial": "financial_score",
    "valuation": "valuation_score",
    "momentum": "momentum_score",
    "event": "event_score",
}
ALLOWED_GATE_MODES = {"strict", "permissive", "non_strict"}
ALLOWED_SCORE_DIRECTIONS = {"higher_is_better", "lower_is_better"}
ALLOWED_RISK_DIRECTIONS = {"higher_is_worse", "lower_is_worse"}
FLOAT_TOLERANCE = 1e-9


def load_scoring_config(
    config_path: str | Path = DEFAULT_SCORING_CONFIG_PATH,
) -> dict[str, object]:
    """Load and validate the Phase 3 scoring YAML."""
    path = Path(config_path)
    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    if not isinstance(config, dict):
        raise ValueError(f"Scoring config must be a mapping: {path}")
    validate_scoring_config(config)
    return config


def validate_scoring_config(config: Mapping[str, object]) -> None:
    """Validate the scoring config shape and weight invariants."""
    _require_mapping(config, "scoring_config")
    score = _require_mapping(config.get("score"), "score")
    _non_negative_float(score.get("top_n", 20), "score.top_n")
    min_available = _float(score.get("min_available_factor_weight", 0.5), "score.min_available_factor_weight")
    if min_available < 0 or min_available > 1:
        raise ValueError("score.min_available_factor_weight must be between 0 and 1.")

    gate = _require_mapping(config.get("validation_gate"), "validation_gate")
    mode = str(gate.get("mode", "strict"))
    if mode not in ALLOWED_GATE_MODES:
        raise ValueError("validation_gate.mode must be one of strict, permissive, non_strict.")
    _positive_int_list(gate.get("required_horizons", [20]), "validation_gate.required_horizons")
    _float(gate.get("min_coverage", 0.2), "validation_gate.min_coverage")
    _non_negative_float(
        gate.get("min_valid_oriented_ic_dates", 1),
        "validation_gate.min_valid_oriented_ic_dates",
    )
    _float(gate.get("min_mean_oriented_rank_ic", 0.0), "validation_gate.min_mean_oriented_rank_ic")
    _float(gate.get("min_oriented_icir", -999.0), "validation_gate.min_oriented_icir")

    hard_filters = _require_mapping(config.get("hard_filters"), "hard_filters")
    for name, entry in hard_filters.items():
        filter_config = _require_mapping(entry, f"hard_filters.{name}")
        if bool(filter_config.get("enabled", True)):
            if "pass_value" not in filter_config:
                raise ValueError(f"hard_filters.{name}.pass_value is required when enabled.")
            _float(filter_config["pass_value"], f"hard_filters.{name}.pass_value")
            missing = str(filter_config.get("missing", "exclude"))
            if missing != "exclude":
                raise ValueError(f"hard_filters.{name}.missing must be exclude.")

    groups = _require_mapping(config.get("groups"), "groups")
    enabled_group_weights: list[float] = []
    positive_factor_names: set[str] = set()
    for group_name, group_entry in groups.items():
        group = _require_mapping(group_entry, f"groups.{group_name}")
        enabled = bool(group.get("enabled", False))
        weight = _non_negative_float(group.get("weight", 0.0), f"groups.{group_name}.weight")
        factors = _require_mapping(group.get("factors", {}), f"groups.{group_name}.factors")
        if enabled:
            enabled_group_weights.append(weight)
            enabled_factor_weights: list[float] = []
            for factor_name, factor_entry in factors.items():
                factor = _require_mapping(
                    factor_entry,
                    f"groups.{group_name}.factors.{factor_name}",
                )
                if bool(factor.get("enabled", False)):
                    factor_weight = _non_negative_float(
                        factor.get("weight", 0.0),
                        f"groups.{group_name}.factors.{factor_name}.weight",
                    )
                    enabled_factor_weights.append(factor_weight)
                    if str(factor_name) in positive_factor_names:
                        raise ValueError(f"Factor appears in more than one enabled score group: {factor_name}")
                    positive_factor_names.add(str(factor_name))
            if not enabled_factor_weights:
                raise ValueError(f"Enabled group must include at least one enabled factor: {group_name}")
            _require_weight_sum_one(enabled_factor_weights, f"groups.{group_name}.factors")

    if enabled_group_weights:
        _require_weight_sum_one(enabled_group_weights, "groups")
    else:
        raise ValueError("At least one score group must be enabled.")

    risk = _require_mapping(config.get("risk_penalty"), "risk_penalty")
    max_penalty = _non_negative_float(risk.get("max_penalty", 0.0), "risk_penalty.max_penalty")
    if max_penalty > 100:
        raise ValueError("risk_penalty.max_penalty must be at most 100.")
    risk_factors = _require_mapping(risk.get("factors", {}), "risk_penalty.factors")
    enabled_risk_weights: list[float] = []
    for factor_name, factor_entry in risk_factors.items():
        factor = _require_mapping(factor_entry, f"risk_penalty.factors.{factor_name}")
        if not bool(factor.get("enabled", True)):
            continue
        if str(factor_name) in enabled_hard_filter_names(config):
            raise ValueError(f"Risk penalty factor cannot also be a hard filter: {factor_name}")
        if str(factor_name) in positive_factor_names:
            raise ValueError(f"Risk penalty factor cannot also be a positive score factor: {factor_name}")
        risk_direction = str(factor.get("risk_direction", ""))
        if risk_direction not in ALLOWED_RISK_DIRECTIONS:
            raise ValueError(
                f"risk_penalty.factors.{factor_name}.risk_direction must be "
                "higher_is_worse or lower_is_worse."
            )
        enabled_risk_weights.append(
            _non_negative_float(
                factor.get("weight", 0.0),
                f"risk_penalty.factors.{factor_name}.weight",
            )
        )
    if bool(risk.get("enabled", True)) and enabled_risk_weights:
        _require_weight_sum_one(enabled_risk_weights, "risk_penalty.factors")

    diagnostics = _require_mapping(config.get("diagnostics", {}), "diagnostics")
    sensitivity = _require_mapping(diagnostics.get("sensitivity", {}), "diagnostics.sensitivity")
    _non_negative_float(
        sensitivity.get("perturbation_pct", 0.10),
        "diagnostics.sensitivity.perturbation_pct",
    )
    yearly = _require_mapping(diagnostics.get("yearly_stability", {}), "diagnostics.yearly_stability")
    _positive_int_list(yearly.get("horizons", [20]), "diagnostics.yearly_stability.horizons")
    _positive_int(
        yearly.get("min_signal_dates_per_year", 1),
        "diagnostics.yearly_stability.min_signal_dates_per_year",
    )


def enabled_scoring_factors(config: Mapping[str, object]) -> list[str]:
    """Return enabled positive-score factor names in deterministic config order."""
    factors: list[str] = []
    for group_name, group in enabled_groups(config).items():
        _ = group_name
        group_factors = _require_mapping(group.get("factors", {}), "group.factors")
        for factor_name, factor_entry in group_factors.items():
            entry = _require_mapping(factor_entry, f"group.factors.{factor_name}")
            if bool(entry.get("enabled", False)):
                factors.append(str(factor_name))
    return factors


def enabled_risk_penalty_factors(config: Mapping[str, object]) -> list[str]:
    """Return enabled soft-risk factor names in deterministic config order."""
    risk = _require_mapping(config.get("risk_penalty", {}), "risk_penalty")
    if not bool(risk.get("enabled", True)):
        return []
    factors = _require_mapping(risk.get("factors", {}), "risk_penalty.factors")
    return [
        str(factor_name)
        for factor_name, entry in factors.items()
        if bool(_require_mapping(entry, f"risk_penalty.factors.{factor_name}").get("enabled", True))
    ]


def enabled_hard_filter_names(config: Mapping[str, object]) -> list[str]:
    """Return enabled hard filter names in config order."""
    filters = _require_mapping(config.get("hard_filters", {}), "hard_filters")
    return [
        str(name)
        for name, entry in filters.items()
        if bool(_require_mapping(entry, f"hard_filters.{name}").get("enabled", True))
    ]


def enabled_groups(config: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return enabled positive score groups in config order."""
    groups = _require_mapping(config.get("groups", {}), "groups")
    return {
        str(group_name): dict(_require_mapping(group, f"groups.{group_name}"))
        for group_name, group in groups.items()
        if bool(_require_mapping(group, f"groups.{group_name}").get("enabled", False))
    }


def all_configured_score_items(config: Mapping[str, object]) -> list[dict[str, object]]:
    """Return configured positive and risk items for validation-gate reporting."""
    items: list[dict[str, object]] = []
    groups = _require_mapping(config.get("groups", {}), "groups")
    for group_name, group_entry in groups.items():
        group = _require_mapping(group_entry, f"groups.{group_name}")
        group_enabled = bool(group.get("enabled", False))
        factors = _require_mapping(group.get("factors", {}), f"groups.{group_name}.factors")
        for factor_name, factor_entry in factors.items():
            factor = _require_mapping(factor_entry, f"groups.{group_name}.factors.{factor_name}")
            items.append(
                {
                    "factor_name": str(factor_name),
                    "score_role": "positive",
                    "score_group": str(group_name),
                    "configured_enabled": bool(group_enabled and factor.get("enabled", False)),
                }
            )

    risk = _require_mapping(config.get("risk_penalty", {}), "risk_penalty")
    risk_enabled = bool(risk.get("enabled", True))
    risk_factors = _require_mapping(risk.get("factors", {}), "risk_penalty.factors")
    for factor_name, factor_entry in risk_factors.items():
        factor = _require_mapping(factor_entry, f"risk_penalty.factors.{factor_name}")
        items.append(
            {
                "factor_name": str(factor_name),
                "score_role": "risk_penalty",
                "score_group": "risk",
                "configured_enabled": bool(risk_enabled and factor.get("enabled", True)),
            }
        )
    return items


def is_strict_mode(config: Mapping[str, object]) -> bool:
    """Return whether validation gate failures must fail fast."""
    gate = _require_mapping(config.get("validation_gate", {}), "validation_gate")
    return str(gate.get("mode", "strict")) == "strict"


def _require_mapping(value: object, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping.")
    return value


def _float(value: object, key: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number.") from exc


def _non_negative_float(value: object, key: str) -> float:
    parsed = _float(value, key)
    if parsed < 0:
        raise ValueError(f"{key} must be non-negative.")
    return parsed


def _positive_int(value: object, key: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be a positive integer.")
    return parsed


def _positive_int_list(value: object, key: str) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError(f"{key} must be a list of positive integers.")
    parsed = [_positive_int(item, key) for item in value]
    if not parsed:
        raise ValueError(f"{key} cannot be empty.")
    return parsed


def _require_weight_sum_one(weights: Sequence[float], key: str) -> None:
    total = float(sum(weights))
    if abs(total - 1.0) > FLOAT_TOLERANCE:
        raise ValueError(f"Enabled weights for {key} must sum to 1.0; got {total:.12g}.")
