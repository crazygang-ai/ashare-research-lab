from __future__ import annotations

import pandas as pd
import pytest

from ashare.scoring.normalization import normalize_factor_scores


DATA_DICTIONARY = {
    "factors": {
        "return_20d": {"type": "factor", "direction": "higher_is_better"},
        "pe_ttm_percentile": {"type": "factor", "direction": "lower_is_better"},
        "above_ma60": {"type": "factor", "direction": "higher_is_better"},
        "is_st": {"type": "hard_filter", "direction": "boolean_filter"},
        "risk_score": {"type": "factor", "direction": "higher_is_better"},
    }
}

SCORING_CONFIG = {
    "normalization": {
        "output_min": 0.0,
        "output_max": 100.0,
        "single_observation_score": 50.0,
        "all_equal_score": 50.0,
    },
    "risk_penalty": {
        "enabled": True,
        "factors": {
            "risk_score": {
                "enabled": True,
                "weight": 1.0,
                "risk_direction": "higher_is_worse",
            }
        },
    },
}


def test_normalize_factor_scores_handles_direction_ties_and_missing_values() -> None:
    values = pd.DataFrame(
        [
            ("A", "return_20d", 0.1),
            ("B", "return_20d", 0.2),
            ("C", "return_20d", 0.2),
            ("D", "return_20d", None),
            ("A", "pe_ttm_percentile", 0.9),
            ("B", "pe_ttm_percentile", 0.1),
            ("C", "pe_ttm_percentile", 0.5),
        ],
        columns=["stock_code", "factor_name", "factor_value"],
    )

    normalized = normalize_factor_scores(values, DATA_DICTIONARY, SCORING_CONFIG)
    return_scores = normalized[normalized["factor_name"] == "return_20d"].set_index("stock_code")
    valuation_scores = normalized[
        normalized["factor_name"] == "pe_ttm_percentile"
    ].set_index("stock_code")

    assert return_scores.loc["A", "normalized_score"] == pytest.approx(0.0)
    assert return_scores.loc["B", "normalized_score"] == pytest.approx(75.0)
    assert return_scores.loc["C", "normalized_score"] == pytest.approx(75.0)
    assert "D" not in return_scores.index
    assert valuation_scores.loc["B", "normalized_score"] == pytest.approx(100.0)
    assert valuation_scores.loc["A", "normalized_score"] == pytest.approx(0.0)


def test_normalize_single_and_all_equal_scores_are_50() -> None:
    values = pd.DataFrame(
        [
            ("A", "return_20d", 1.0),
            ("B", "return_20d", 1.0),
            ("C", "above_ma60", 1.0),
        ],
        columns=["stock_code", "factor_name", "factor_value"],
    )

    normalized = normalize_factor_scores(values, DATA_DICTIONARY, SCORING_CONFIG)

    assert set(normalized["normalized_score"]) == {50.0}


def test_normalize_risk_severity_uses_risk_direction() -> None:
    values = pd.DataFrame(
        [
            ("A", "risk_score", 0.1),
            ("B", "risk_score", 0.9),
        ],
        columns=["stock_code", "factor_name", "factor_value"],
    )

    normalized = normalize_factor_scores(values, DATA_DICTIONARY, SCORING_CONFIG)
    scores = normalized.set_index("stock_code")

    assert scores.loc["B", "direction"] == "higher_is_worse"
    assert scores.loc["B", "normalized_score"] == pytest.approx(100.0)
    assert scores.loc["A", "normalized_score"] == pytest.approx(0.0)


def test_normalize_rejects_boolean_filter_as_score_factor() -> None:
    values = pd.DataFrame(
        [("A", "is_st", 0.0)],
        columns=["stock_code", "factor_name", "factor_value"],
    )

    with pytest.raises(ValueError, match="boolean_filter"):
        normalize_factor_scores(values, DATA_DICTIONARY, SCORING_CONFIG)
