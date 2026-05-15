"""Configuration helpers for Phase 1b portfolio backtests."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

import yaml


DEFAULT_BACKTEST_CONFIG: dict[str, object] = {
    "scan": {"frequency": "daily"},
    "rebalance": {
        "frequency": "monthly",
        "trigger": "month_end",
        "execution": "next_open",
    },
    "portfolio": {
        "top_n": 20,
        "weighting": "equal_weight",
        "initial_cash": 1_000_000,
    },
    "benchmark": {
        "primary": "synthetic_cap_weight",
        "secondary": "synthetic_equal_weight",
        "rebalance_frequency": "monthly",
        "market_cap_field_priority": ["float_mv", "total_mv"],
    },
    "trading_rules": {
        "skip_buy_if_limit_up": True,
        "block_sell_if_limit_down": True,
        "hold_if_suspended": True,
        "delist_exit_value_ratio": 0.0,
        "price_compare_tolerance": 0.000001,
    },
    "costs": {
        "commission_bps": 2.5,
        "stamp_tax_bps": 10.0,
        "slippage_bps": 5.0,
        "min_commission_yuan": 5.0,
    },
}


def load_backtest_config(config_path: str | Path = "configs/backtest.yaml") -> dict[str, object]:
    """Load backtest YAML and merge it onto the built-in Phase 1b defaults."""
    path = Path(config_path)
    if not path.exists():
        return deepcopy(DEFAULT_BACKTEST_CONFIG)

    with path.open(encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"Backtest config must be a mapping: {path}")
    return merge_backtest_config(loaded)


def merge_backtest_config(
    config: Mapping[str, object] | None = None,
    *,
    top_n: int | None = None,
    initial_cash: float | None = None,
    cost_overrides: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Merge a partial config and CLI overrides onto defaults."""
    merged = deepcopy(DEFAULT_BACKTEST_CONFIG)
    if config:
        _deep_update(merged, config)

    portfolio = _section(merged, "portfolio")
    if top_n is not None:
        portfolio["top_n"] = int(top_n)
    if initial_cash is not None:
        portfolio["initial_cash"] = float(initial_cash)

    if cost_overrides:
        costs = _section(merged, "costs")
        for key, value in cost_overrides.items():
            if value is not None:
                costs[str(key)] = float(value)

    _validate_config(merged)
    return merged


def _section(config: dict[str, object], key: str) -> dict[str, object]:
    value = config.get(key)
    if not isinstance(value, dict):
        value = {}
        config[key] = value
    return value


def _deep_update(target: dict[str, object], source: Mapping[str, object]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)  # type: ignore[arg-type,index]
        else:
            target[str(key)] = deepcopy(value)


def _validate_config(config: Mapping[str, object]) -> None:
    portfolio = config.get("portfolio")
    if not isinstance(portfolio, Mapping):
        raise ValueError("backtest config portfolio section must be a mapping.")
    top_n = int(portfolio.get("top_n", 0))
    initial_cash = float(portfolio.get("initial_cash", 0.0))
    if top_n <= 0:
        raise ValueError("portfolio.top_n must be positive.")
    if initial_cash <= 0:
        raise ValueError("portfolio.initial_cash must be positive.")

    costs = config.get("costs")
    if not isinstance(costs, Mapping):
        raise ValueError("backtest config costs section must be a mapping.")
    for key in ["commission_bps", "stamp_tax_bps", "slippage_bps", "min_commission_yuan"]:
        value = float(costs.get(key, 0.0))
        if value < 0:
            raise ValueError(f"costs.{key} must be non-negative.")
