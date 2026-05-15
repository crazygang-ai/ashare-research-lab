from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ashare.scoring.validation_gate import (
    VALIDATION_GATE_COLUMNS,
    evaluate_validation_gate,
    load_validation_artifacts,
)


def _config(min_coverage: float = 0.2) -> dict[str, object]:
    return {
        "score": {"top_n": 20, "min_available_factor_weight": 0.5},
        "validation_gate": {
            "mode": "strict",
            "required_horizons": [20],
            "min_coverage": min_coverage,
            "min_valid_oriented_ic_dates": 1,
            "min_mean_oriented_rank_ic": 0.0,
            "min_oriented_icir": -999.0,
            "require_group_return_rows": True,
        },
        "hard_filters": {"is_st": {"enabled": True, "pass_value": 0.0, "missing": "exclude"}},
        "groups": {
            "financial": {
                "enabled": True,
                "required": False,
                "weight": 1.0,
                "factors": {
                    "revenue_yoy": {"enabled": True, "weight": 0.5},
                    "profit_yoy": {"enabled": True, "weight": 0.5},
                },
            }
        },
        "risk_penalty": {"enabled": True, "max_penalty": 15.0, "factors": {}},
        "diagnostics": {"sensitivity": {"enabled": False}, "yearly_stability": {"horizons": [20]}},
    }


def _dictionary() -> dict[str, object]:
    return {
        "factors": {
            "revenue_yoy": {
                "type": "factor",
                "direction": "higher_is_better",
                "score_group": "financial",
            },
            "profit_yoy": {
                "type": "factor",
                "direction": "higher_is_better",
                "score_group": "financial",
            },
            "is_st": {"type": "hard_filter", "direction": "boolean_filter"},
        }
    }


def _artifacts() -> dict[str, pd.DataFrame]:
    factors = ["revenue_yoy", "profit_yoy"]
    return {
        "coverage": pd.DataFrame(
            {"factor_name": factors, "trade_date": ["2026-01-02"] * 2, "coverage": [1.0, 0.8]}
        ),
        "rank_ic": pd.DataFrame({"factor_name": factors, "horizon": [20, 20]}),
        "ic_summary": pd.DataFrame(
            {
                "factor_name": factors,
                "horizon": [20, 20],
                "valid_oriented_ic_dates": [2, 1],
                "mean_oriented_rank_ic": [0.1, 0.0],
                "oriented_icir": [float("nan"), float("nan")],
            }
        ),
        "group_returns": pd.DataFrame({"factor_name": factors, "horizon": [20, 20]}),
        "decay_curve": pd.DataFrame({"factor_name": factors, "horizon": [20, 20]}),
    }


def test_validation_gate_passes_only_enabled_dictionary_factors_with_real_columns() -> None:
    result = evaluate_validation_gate(_artifacts(), _config(), _dictionary())

    assert result.eligible_factors == frozenset({"revenue_yoy", "profit_yoy"})
    assert list(result.table.columns) == VALIDATION_GATE_COLUMNS
    assert set(result.table["validation_status"]) == {"PASS"}
    assert result.table["valid_oriented_ic_dates"].min() == 1
    assert "rank_ic_observations" not in result.table.columns


def test_validation_gate_fails_missing_or_below_threshold_factor() -> None:
    result = evaluate_validation_gate(_artifacts(), _config(min_coverage=0.9), _dictionary())

    failed = result.table[result.table["factor_name"] == "profit_yoy"].iloc[0]
    assert failed["validation_status"] == "FAIL"
    assert "coverage" in failed["reason"]
    assert "profit_yoy" not in result.eligible_factors
    assert result.warnings


def test_validation_gate_rejects_artifacts_with_alias_columns() -> None:
    artifacts = _artifacts()
    artifacts["ic_summary"] = artifacts["ic_summary"].rename(
        columns={"mean_oriented_rank_ic": "oriented_rank_ic_mean"}
    )

    with pytest.raises(ValueError, match="mean_oriented_rank_ic"):
        evaluate_validation_gate(artifacts, _config(), _dictionary())


def test_load_validation_artifacts_requires_phase1a6_files(tmp_path: Path) -> None:
    for name, frame in _artifacts().items():
        filename = {
            "coverage": "coverage.csv",
            "rank_ic": "rank_ic.csv",
            "ic_summary": "ic_summary.csv",
            "group_returns": "group_returns.csv",
            "decay_curve": "decay_curve.csv",
        }[name]
        frame.to_csv(tmp_path / filename, index=False)

    loaded = load_validation_artifacts(tmp_path)
    assert set(loaded) == {"coverage", "rank_ic", "ic_summary", "group_returns", "decay_curve"}

    (tmp_path / "coverage.csv").unlink()
    with pytest.raises(FileNotFoundError, match="coverage.csv"):
        load_validation_artifacts(tmp_path)
