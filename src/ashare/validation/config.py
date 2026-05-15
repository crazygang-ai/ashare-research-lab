"""Configuration helpers for Phase 1a-5 single-factor validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml


DEFAULT_VALIDATION_CONFIG_PATH = Path("configs/validation.yaml")

DEFAULT_SINGLE_FACTOR_CONFIG: dict[str, object] = {
    "horizons": [5, 20, 60],
    "n_groups": 5,
    "min_ic_observations": 3,
    "min_group_size": 1,
    "require_same_as_of_trade_date": True,
    "universe_factor_names": ["is_st", "is_suspended", "is_delisted", "low_liquidity"],
    "label": {
        "price": "adjusted_close",
        "return_type": "close_to_close",
    },
}


def load_validation_config(
    config_path: str | Path = DEFAULT_VALIDATION_CONFIG_PATH,
) -> dict[str, object]:
    """Load validation YAML without applying CLI overrides."""
    path = Path(config_path)
    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    if not isinstance(config, dict):
        raise ValueError(f"Validation config must be a mapping: {path}")
    return config


def merge_validation_config(
    config: Mapping[str, object] | None,
    horizons: Sequence[int] | None = None,
    n_groups: int | None = None,
) -> dict[str, object]:
    """Return merged single-factor settings using CLI > YAML > built-in defaults."""
    merged = _deep_copy(DEFAULT_SINGLE_FACTOR_CONFIG)
    yaml_config = _single_factor_section(config)
    _deep_update(merged, yaml_config)

    if horizons is not None:
        merged["horizons"] = _positive_int_list(horizons, "horizons")
    else:
        merged["horizons"] = _positive_int_list(merged.get("horizons"), "horizons")

    if n_groups is not None:
        merged["n_groups"] = _positive_int(n_groups, "n_groups")
    else:
        merged["n_groups"] = _positive_int(merged.get("n_groups"), "n_groups")

    merged["min_ic_observations"] = _positive_int(
        merged.get("min_ic_observations"),
        "min_ic_observations",
    )
    merged["min_group_size"] = _positive_int(merged.get("min_group_size"), "min_group_size")
    merged["require_same_as_of_trade_date"] = bool(
        merged.get("require_same_as_of_trade_date", True)
    )

    universe_factor_names = merged.get("universe_factor_names")
    if not isinstance(universe_factor_names, Sequence) or isinstance(
        universe_factor_names, str
    ):
        raise ValueError("single_factor.universe_factor_names must be a list of strings.")
    merged["universe_factor_names"] = [str(name) for name in universe_factor_names]

    label_config = merged.get("label")
    if not isinstance(label_config, Mapping):
        raise ValueError("single_factor.label must be a mapping.")
    merged["label"] = dict(label_config)

    return merged


def _single_factor_section(config: Mapping[str, object] | None) -> Mapping[str, object]:
    if config is None:
        return {}
    if "single_factor" in config:
        section = config["single_factor"]
        if section is None:
            return {}
        if not isinstance(section, Mapping):
            raise ValueError("single_factor must be a mapping.")
        return section

    # Accept already-merged single-factor settings when called from lower-level APIs.
    known_keys = set(DEFAULT_SINGLE_FACTOR_CONFIG)
    if known_keys.intersection(config):
        return config
    return {}


def _deep_update(base: dict[str, object], overrides: Mapping[str, object]) -> None:
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            nested = dict(base[key])  # type: ignore[index]
            _deep_update(nested, value)
            base[key] = nested
        else:
            base[key] = value


def _deep_copy(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            result[key] = _deep_copy(item)
        elif isinstance(item, list):
            result[key] = list(item)
        else:
            result[key] = item
    return result


def _positive_int_list(value: object, key: str) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError(f"single_factor.{key} must be a list of positive integers.")
    parsed = [_positive_int(item, key) for item in value]
    if not parsed:
        raise ValueError(f"single_factor.{key} cannot be empty.")
    return parsed


def _positive_int(value: object, key: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"single_factor.{key} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"single_factor.{key} must be a positive integer.")
    return parsed
