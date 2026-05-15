"""Factor configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_FACTOR_CONFIG_PATH = Path("configs/factors.yaml")

REQUIRED_FACTORS = (
    "return_20d",
    "return_60d",
    "above_ma60",
    "pe_ttm_percentile",
    "pb_percentile",
    "revenue_yoy",
    "profit_yoy",
)

REQUIRED_HARD_FILTERS = (
    "is_st",
    "is_suspended",
    "is_delisted",
    "low_liquidity",
)


def load_factor_config(config_path: str | Path = DEFAULT_FACTOR_CONFIG_PATH) -> dict[str, object]:
    """Load and validate the Phase 1a-4 factor configuration."""
    path = Path(config_path)
    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    if not isinstance(config, dict):
        raise ValueError(f"Factor config must be a mapping: {path}")

    _validate_factor_config(config)
    return config


def factor_params(config: Mapping[str, object], factor_name: str) -> dict[str, Any]:
    """Return a copy of ``factors.<factor_name>.params``."""
    factors = _mapping_at(config, "factors")
    factor_config = _mapping_at(factors, factor_name)
    params = factor_config.get("params", {})
    if not isinstance(params, dict):
        raise ValueError(f"factors.{factor_name}.params must be a mapping.")
    return dict(params)


def hard_filter_params(config: Mapping[str, object], filter_name: str) -> dict[str, Any]:
    """Return a copy of ``hard_filters.<filter_name>.params``."""
    hard_filters = _mapping_at(config, "hard_filters")
    filter_config = _mapping_at(hard_filters, filter_name)
    params = filter_config.get("params", {})
    if not isinstance(params, dict):
        raise ValueError(f"hard_filters.{filter_name}.params must be a mapping.")
    return dict(params)


def _validate_factor_config(config: Mapping[str, object]) -> None:
    factors = _mapping_at(config, "factors")
    hard_filters = _mapping_at(config, "hard_filters")

    missing_factors = [name for name in REQUIRED_FACTORS if name not in factors]
    missing_filters = [name for name in REQUIRED_HARD_FILTERS if name not in hard_filters]
    if missing_factors or missing_filters:
        raise ValueError(
            "Factor config is missing required entries: "
            f"factors={missing_factors}, hard_filters={missing_filters}"
        )

    for name in REQUIRED_FACTORS:
        entry = _mapping_at(factors, name)
        for key in ("direction", "group", "hard_filter", "soft_penalty", "params"):
            if key not in entry:
                raise ValueError(f"factors.{name}.{key} is required.")
        if not isinstance(entry["params"], dict):
            raise ValueError(f"factors.{name}.params must be a mapping.")

    for name in REQUIRED_HARD_FILTERS:
        entry = _mapping_at(hard_filters, name)
        if "enabled" not in entry:
            raise ValueError(f"hard_filters.{name}.enabled is required.")
        if "params" not in entry:
            raise ValueError(f"hard_filters.{name}.params is required.")
        if not isinstance(entry["params"], dict):
            raise ValueError(f"hard_filters.{name}.params must be a mapping.")


def _mapping_at(config: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = config.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping.")
    return value
