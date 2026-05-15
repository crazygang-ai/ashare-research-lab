from __future__ import annotations

from copy import deepcopy

import pytest

from ashare.scoring.config import (
    enabled_hard_filter_names,
    enabled_risk_penalty_factors,
    enabled_scoring_factors,
    load_scoring_config,
    validate_scoring_config,
)


def test_default_scoring_config_is_phase3_ready() -> None:
    config = load_scoring_config("configs/scoring.yaml")

    assert config["version"] == "phase3.v1"
    assert enabled_scoring_factors(config) == [
        "revenue_yoy",
        "profit_yoy",
        "pe_ttm_percentile",
        "pb_percentile",
        "return_20d",
        "above_ma60",
    ]
    assert enabled_hard_filter_names(config) == [
        "is_st",
        "is_suspended",
        "is_delisted",
        "low_liquidity",
    ]
    assert enabled_risk_penalty_factors(config) == []


def test_scoring_config_rejects_invalid_group_weight_sum() -> None:
    config = load_scoring_config("configs/scoring.yaml")
    bad_config = deepcopy(config)
    bad_config["groups"]["financial"]["weight"] = 0.99  # type: ignore[index]

    with pytest.raises(ValueError, match="groups"):
        validate_scoring_config(bad_config)


def test_scoring_config_rejects_risk_factor_reused_as_positive_factor() -> None:
    config = load_scoring_config("configs/scoring.yaml")
    bad_config = deepcopy(config)
    bad_config["risk_penalty"]["factors"] = {  # type: ignore[index]
        "return_20d": {
            "enabled": True,
            "weight": 1.0,
            "risk_direction": "higher_is_worse",
        }
    }

    with pytest.raises(ValueError, match="positive score factor"):
        validate_scoring_config(bad_config)
