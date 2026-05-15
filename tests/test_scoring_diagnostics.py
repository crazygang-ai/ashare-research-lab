from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from ashare.scoring.diagnostics import (
    WEIGHT_SENSITIVITY_COLUMNS,
    YEARLY_STABILITY_COLUMNS,
    run_weight_sensitivity,
    run_yearly_stability,
)
from ashare.scoring.scorer import CompositeScoreResult
from ashare.scoring.validation_gate import VALIDATION_GATE_COLUMNS, ValidationGateResult
from ashare.storage.db import default_schema_path


def _config() -> dict[str, object]:
    return {
        "score": {"top_n": 20, "min_available_factor_weight": 0.5},
        "validation_gate": {"mode": "strict", "required_horizons": [1]},
        "normalization": {"output_min": 0.0, "output_max": 100.0},
        "hard_filters": {"is_st": {"enabled": True, "pass_value": 0.0, "missing": "exclude"}},
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
        },
        "risk_penalty": {"enabled": True, "max_penalty": 15.0, "factors": {}},
        "diagnostics": {
            "sensitivity": {"enabled": True, "perturbation_pct": 0.1, "top_n": 20},
            "yearly_stability": {
                "enabled": True,
                "signal_frequency": "month_end",
                "horizons": [1],
                "min_signal_dates_per_year": 1,
            },
        },
    }


def _dictionary() -> dict[str, object]:
    return {
        "factors": {
            "revenue_yoy": {"type": "factor", "direction": "higher_is_better"},
            "profit_yoy": {"type": "factor", "direction": "higher_is_better"},
            "return_20d": {"type": "factor", "direction": "higher_is_better"},
            "is_st": {"type": "hard_filter", "direction": "boolean_filter"},
        }
    }


def _gate(factors: list[str] | None = None) -> ValidationGateResult:
    names = factors or ["revenue_yoy", "profit_yoy", "return_20d"]
    table = pd.DataFrame(
        {
            "factor_name": names,
            "score_role": ["positive"] * len(names),
            "score_group": ["financial", "financial", "momentum"][: len(names)],
            "configured_enabled": [True] * len(names),
            "validation_status": ["PASS"] * len(names),
            "reason": ["passed"] * len(names),
            "required_horizons": ["1"] * len(names),
            "coverage": [1.0] * len(names),
            "valid_oriented_ic_dates": [1] * len(names),
            "mean_oriented_rank_ic": [0.1] * len(names),
            "oriented_icir": [float("nan")] * len(names),
            "group_return_rows": [1] * len(names),
        },
        columns=VALIDATION_GATE_COLUMNS,
    )
    return ValidationGateResult(eligible_factors=frozenset(names), table=table)


def _base_result() -> CompositeScoreResult:
    normalized = pd.DataFrame(
        [
            ("2026-01-02", "run", "LOCAL_FIXTURE", "A", "revenue_yoy", "positive", "financial", 0.2, "higher_is_better", 100.0, 0.5, 50.0, "PASS"),
            ("2026-01-02", "run", "LOCAL_FIXTURE", "A", "profit_yoy", "positive", "financial", 0.3, "higher_is_better", 100.0, 0.5, 50.0, "PASS"),
            ("2026-01-02", "run", "LOCAL_FIXTURE", "A", "return_20d", "positive", "momentum", 0.1, "higher_is_better", 0.0, 1.0, 0.0, "PASS"),
            ("2026-01-02", "run", "LOCAL_FIXTURE", "B", "revenue_yoy", "positive", "financial", 0.1, "higher_is_better", 0.0, 0.5, 0.0, "PASS"),
            ("2026-01-02", "run", "LOCAL_FIXTURE", "B", "profit_yoy", "positive", "financial", 0.1, "higher_is_better", 0.0, 0.5, 0.0, "PASS"),
            ("2026-01-02", "run", "LOCAL_FIXTURE", "B", "return_20d", "positive", "momentum", 0.4, "higher_is_better", 100.0, 1.0, 100.0, "PASS"),
        ],
        columns=[
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
        ],
    )
    breakdown = pd.DataFrame({"stock_code": ["A", "B"], "as_of_date": ["2026-01-02", "2026-01-02"], "source_run_id": ["run", "run"], "index_code": ["LOCAL_FIXTURE", "LOCAL_FIXTURE"]})
    candidates = pd.DataFrame(
        {
            "rank": [1, 2],
            "stock_code": ["A", "B"],
            "as_of_date": ["2026-01-02", "2026-01-02"],
            "source_run_id": ["run", "run"],
            "index_code": ["LOCAL_FIXTURE", "LOCAL_FIXTURE"],
            "total_score": [50.0, 50.0],
        }
    )
    return CompositeScoreResult(
        scored_candidates=candidates,
        score_breakdown=breakdown,
        factor_normalized_scores=normalized,
        hard_filter_exclusions=pd.DataFrame(),
        validation_gate=pd.DataFrame(),
    )


def test_run_weight_sensitivity_outputs_group_and_factor_scenarios() -> None:
    sensitivity = run_weight_sensitivity(_base_result(), _config(), top_n=2)

    assert list(sensitivity.columns) == WEIGHT_SENSITIVITY_COLUMNS
    assert {"group_weight", "factor_weight"}.issubset(set(sensitivity["scenario_type"]))
    assert set(sensitivity["change_direction"]) == {"up", "down"}
    assert sensitivity["top_n"].eq(2).all()


def test_run_yearly_stability_uses_total_score_as_synthetic_factor() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    try:
        for day in [date(2026, 1, 1), date(2026, 1, 2), date(2026, 2, 1), date(2026, 2, 2)]:
            connection.execute("INSERT INTO trading_calendar VALUES (?, true, NULL, NULL)", [day])
        for stock in ["A", "B"]:
            connection.execute(
                """
                INSERT INTO universe_members (
                    index_code, stock_code, in_date, in_effective_date, source
                )
                VALUES ('LOCAL_FIXTURE', ?, '2020-01-01', '2020-01-01', 'fixture')
                """,
                [stock],
            )
        prices = [
            ("A", date(2026, 1, 1), 10.0), ("B", date(2026, 1, 1), 10.0),
            ("A", date(2026, 1, 2), 10.0), ("B", date(2026, 1, 2), 10.0),
            ("A", date(2026, 2, 1), 12.0), ("B", date(2026, 2, 1), 9.0),
            ("A", date(2026, 2, 2), 13.0), ("B", date(2026, 2, 2), 8.0),
        ]
        connection.executemany(
            "INSERT INTO daily_prices (stock_code, trade_date, close, adj_factor) VALUES (?, ?, ?, 1.0)",
            prices,
        )
        factor_rows = []
        for trade_date in [date(2026, 1, 2), date(2026, 2, 1)]:
            factor_rows.extend(
                [
                    ("A", trade_date, "is_st", 0.0, trade_date, "run"),
                    ("B", trade_date, "is_st", 0.0, trade_date, "run"),
                    ("A", trade_date, "revenue_yoy", 1.0, trade_date, "run"),
                    ("B", trade_date, "revenue_yoy", 0.0, trade_date, "run"),
                    ("A", trade_date, "profit_yoy", 1.0, trade_date, "run"),
                    ("B", trade_date, "profit_yoy", 0.0, trade_date, "run"),
                    ("A", trade_date, "return_20d", 1.0, trade_date, "run"),
                    ("B", trade_date, "return_20d", 0.0, trade_date, "run"),
                ]
            )
        connection.executemany(
            """
            INSERT INTO factor_values (
                stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            factor_rows,
        )

        stability = run_yearly_stability(
            connection=connection,
            start_date="2026-01-01",
            end_date="2026-02-01",
            source_run_id="run",
            index_code="LOCAL_FIXTURE",
            scoring_config=_config(),
            data_dictionary=_dictionary(),
            validation_gate=_gate(),
            horizons=[1],
        )
    finally:
        connection.close()

    assert list(stability.columns) == YEARLY_STABILITY_COLUMNS
    assert stability.loc[0, "year"] == 2026
    assert stability.loc[0, "horizon"] == 1
    assert stability.loc[0, "status"] == "ok"
    assert stability.loc[0, "stock_observation_count"] > 0
