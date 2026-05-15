from __future__ import annotations

from datetime import date

import pandas as pd

from ashare.scoring.filters import HARD_FILTER_EXCLUSION_COLUMNS, apply_hard_filters


CONFIG = {
    "hard_filters": {
        "is_st": {"enabled": True, "pass_value": 0.0, "missing": "exclude"},
        "is_suspended": {"enabled": True, "pass_value": 0.0, "missing": "exclude"},
    }
}


def test_apply_hard_filters_excludes_failed_and_missing_fields() -> None:
    universe = pd.DataFrame({"stock_code": ["A", "B", "C"]})
    values = pd.DataFrame(
        [
            ("A", "is_st", 0.0),
            ("A", "is_suspended", 0.0),
            ("B", "is_st", 1.0),
            ("B", "is_suspended", 0.0),
            ("C", "is_st", 0.0),
        ],
        columns=["stock_code", "factor_name", "factor_value"],
    )

    result = apply_hard_filters(
        factor_values=values,
        universe=universe,
        as_of_date=date(2026, 1, 2),
        source_run_id="run",
        index_code="LOCAL_FIXTURE",
        scoring_config=CONFIG,
    )

    assert result.passed_stock_codes == ("A",)
    assert list(result.exclusions.columns) == HARD_FILTER_EXCLUSION_COLUMNS
    assert result.exclusions["stock_code"].tolist() == ["B", "C"]
    assert result.exclusions["exclusion_reason"].tolist() == [
        "failed_hard_filter",
        "missing_hard_filter",
    ]


def test_apply_hard_filters_outputs_empty_fixed_header() -> None:
    universe = pd.DataFrame({"stock_code": ["A"]})
    values = pd.DataFrame(
        [("A", "is_st", 0.0), ("A", "is_suspended", 0.0)],
        columns=["stock_code", "factor_name", "factor_value"],
    )

    result = apply_hard_filters(
        factor_values=values,
        universe=universe,
        as_of_date=date(2026, 1, 2),
        source_run_id="run",
        index_code="LOCAL_FIXTURE",
        scoring_config=CONFIG,
    )

    assert result.passed_stock_codes == ("A",)
    assert result.exclusions.empty
    assert list(result.exclusions.columns) == HARD_FILTER_EXCLUSION_COLUMNS
