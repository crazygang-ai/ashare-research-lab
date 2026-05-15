from __future__ import annotations

from copy import deepcopy
from datetime import date

import duckdb
import pandas as pd
import pytest

from ashare.scoring.scorer import (
    FACTOR_NORMALIZED_COLUMNS,
    SCORED_CANDIDATE_COLUMNS,
    SCORE_BREAKDOWN_COLUMNS,
    compute_composite_scores,
)
from ashare.scoring.validation_gate import VALIDATION_GATE_COLUMNS, ValidationGateResult
from ashare.storage.db import default_schema_path


DATA_DICTIONARY = {
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
        "return_20d": {
            "type": "factor",
            "direction": "higher_is_better",
            "score_group": "momentum",
        },
        "risk_score": {
            "type": "factor",
            "direction": "higher_is_better",
            "score_group": "risk",
        },
        "is_st": {"type": "hard_filter", "direction": "boolean_filter"},
        "is_suspended": {"type": "hard_filter", "direction": "boolean_filter"},
    }
}


def _config() -> dict[str, object]:
    return {
        "score": {"top_n": 20, "min_available_factor_weight": 0.5},
        "validation_gate": {
            "mode": "strict",
            "required_horizons": [20],
            "min_coverage": 0.2,
            "min_valid_oriented_ic_dates": 1,
            "min_mean_oriented_rank_ic": 0.0,
            "min_oriented_icir": -999.0,
            "require_group_return_rows": True,
        },
        "normalization": {
            "output_min": 0.0,
            "output_max": 100.0,
            "single_observation_score": 50.0,
            "all_equal_score": 50.0,
        },
        "hard_filters": {
            "is_st": {"enabled": True, "pass_value": 0.0, "missing": "exclude"},
            "is_suspended": {"enabled": True, "pass_value": 0.0, "missing": "exclude"},
        },
        "groups": {
            "financial": {
                "enabled": True,
                "required": False,
                "weight": 0.5,
                "factors": {
                    "revenue_yoy": {"enabled": True, "weight": 0.5},
                    "profit_yoy": {"enabled": True, "weight": 0.5},
                },
            },
            "momentum": {
                "enabled": True,
                "required": False,
                "weight": 0.5,
                "factors": {"return_20d": {"enabled": True, "weight": 1.0}},
            },
            "event": {"enabled": False, "required": False, "weight": 0.0, "factors": {}},
        },
        "risk_penalty": {
            "enabled": True,
            "max_penalty": 10.0,
            "factors": {
                "risk_score": {
                    "enabled": True,
                    "weight": 1.0,
                    "risk_direction": "higher_is_worse",
                }
            },
        },
        "diagnostics": {"sensitivity": {"enabled": True}, "yearly_stability": {"horizons": [20]}},
    }


@pytest.fixture()
def scoring_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    connection.executemany(
        """
        INSERT INTO universe_members (index_code, stock_code, in_date, in_effective_date, source)
        VALUES ('LOCAL_FIXTURE', ?, ?, ?, 'fixture')
        """,
        [("A", date(2020, 1, 1), date(2020, 1, 1)),
         ("B", date(2020, 1, 1), date(2020, 1, 1)),
         ("C", date(2020, 1, 1), date(2020, 1, 1))],
    )
    connection.executemany(
        """
        INSERT INTO securities (stock_code, stock_name, exchange, list_date)
        VALUES (?, ?, 'SSE', ?)
        """,
        [("A", "Alpha", date(2020, 1, 1)),
         ("B", "Beta", date(2020, 1, 1)),
         ("C", "Gamma", date(2020, 1, 1))],
    )
    connection.executemany(
        """
        INSERT INTO industry_classifications (
            stock_code, industry_standard, industry_l1, industry_l2, in_date, version, source
        )
        VALUES (?, 'fixture', ?, ?, ?, 'v1', 'fixture')
        """,
        [("A", "Tech", "Software", date(2020, 1, 1)),
         ("B", "Finance", "Broker", date(2020, 1, 1))],
    )
    rows: list[tuple[str, date, str, float, date, str]] = []

    def add(stock: str, factor: str, value: float) -> None:
        rows.append((stock, date(2026, 1, 2), factor, value, date(2026, 1, 2), "score-run"))

    for stock in ["A", "B", "C"]:
        add(stock, "is_st", 0.0 if stock != "C" else 1.0)
        add(stock, "is_suspended", 0.0)
    add("A", "revenue_yoy", 0.2)
    add("A", "profit_yoy", 0.3)
    add("A", "return_20d", 0.1)
    add("A", "risk_score", 0.2)
    add("B", "revenue_yoy", 0.1)
    add("B", "profit_yoy", 0.1)
    add("B", "return_20d", 0.4)
    add("B", "risk_score", 0.8)
    add("C", "revenue_yoy", 9.0)
    add("C", "profit_yoy", 9.0)
    add("C", "return_20d", 9.0)
    connection.executemany(
        """
        INSERT INTO factor_values (
            stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    try:
        yield connection
    finally:
        connection.close()


def _gate() -> ValidationGateResult:
    factors = ["revenue_yoy", "profit_yoy", "return_20d", "risk_score"]
    table = pd.DataFrame(
        {
            "factor_name": factors,
            "score_role": ["positive", "positive", "positive", "risk_penalty"],
            "score_group": ["financial", "financial", "momentum", "risk"],
            "configured_enabled": [True, True, True, True],
            "validation_status": ["PASS", "PASS", "PASS", "PASS"],
            "reason": ["passed", "passed", "passed", "passed"],
            "required_horizons": ["20", "20", "20", "20"],
            "coverage": [1.0, 1.0, 1.0, 1.0],
            "valid_oriented_ic_dates": [1, 1, 1, 1],
            "mean_oriented_rank_ic": [0.1, 0.1, 0.1, 0.1],
            "oriented_icir": [float("nan")] * 4,
            "group_return_rows": [1, 1, 1, 1],
        },
        columns=VALIDATION_GATE_COLUMNS,
    )
    return ValidationGateResult(eligible_factors=frozenset(factors), table=table)


def test_compute_composite_scores_filters_normalizes_scores_and_applies_soft_penalty(
    scoring_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = compute_composite_scores(
        scoring_connection,
        as_of_date="2026-01-02",
        source_run_id="score-run",
        index_code="LOCAL_FIXTURE",
        scoring_config=_config(),
        data_dictionary=DATA_DICTIONARY,
        validation_gate=_gate(),
        top_n=20,
    )

    assert list(result.scored_candidates.columns) == SCORED_CANDIDATE_COLUMNS
    assert list(result.score_breakdown.columns) == SCORE_BREAKDOWN_COLUMNS
    assert list(result.factor_normalized_scores.columns) == FACTOR_NORMALIZED_COLUMNS
    assert result.scored_candidates["stock_code"].tolist() == ["A", "B"]
    assert result.scored_candidates["rank"].tolist() == [1, 2]
    assert result.scored_candidates.loc[0, "total_score"] == pytest.approx(50.0)
    assert result.scored_candidates.loc[1, "risk_penalty"] == pytest.approx(10.0)
    assert result.scored_candidates.loc[1, "total_score"] == pytest.approx(40.0)
    assert result.hard_filter_exclusions["stock_code"].tolist() == ["C"]
    assert "C" not in set(result.factor_normalized_scores["stock_code"])
    assert result.scored_candidates["hard_filter_passed"].all()


def test_compute_composite_scores_excludes_required_group_with_insufficient_factor_weight(
    scoring_connection: duckdb.DuckDBPyConnection,
) -> None:
    config = deepcopy(_config())
    config["score"]["min_available_factor_weight"] = 0.75  # type: ignore[index]
    config["groups"]["financial"]["required"] = True  # type: ignore[index]
    scoring_connection.execute(
        """
        DELETE FROM factor_values
        WHERE stock_code = 'B' AND factor_name = 'profit_yoy'
        """
    )

    result = compute_composite_scores(
        scoring_connection,
        as_of_date=date(2026, 1, 2),
        source_run_id="score-run",
        index_code="LOCAL_FIXTURE",
        scoring_config=config,
        data_dictionary=DATA_DICTIONARY,
        validation_gate=_gate(),
        top_n=20,
    )

    assert result.scored_candidates["stock_code"].tolist() == ["A"]
    assert any("required group" in warning for warning in result.warnings)
