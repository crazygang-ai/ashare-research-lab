from __future__ import annotations

from copy import deepcopy
from datetime import date
import math

import duckdb
import pytest

from ashare.storage.db import default_schema_path
from ashare.validation.runner import validate_factors


DATA_DICTIONARY = {
    "factors": {
        "return_20d": {"type": "factor", "direction": "higher_is_better"},
        "pe_ttm_percentile": {"type": "factor", "direction": "lower_is_better"},
        "is_st": {"type": "hard_filter", "direction": "boolean_filter"},
        "is_suspended": {"type": "hard_filter", "direction": "boolean_filter"},
        "is_delisted": {"type": "hard_filter", "direction": "boolean_filter"},
        "low_liquidity": {"type": "hard_filter", "direction": "boolean_filter"},
    }
}

VALIDATION_CONFIG = {
    "single_factor": {
        "horizons": [1],
        "n_groups": 2,
        "min_ic_observations": 2,
        "min_group_size": 1,
        "require_same_as_of_trade_date": True,
        "universe_factor_names": ["is_st", "is_suspended", "is_delisted", "low_liquidity"],
        "label": {"price": "adjusted_close", "return_type": "close_to_close"},
    }
}


@pytest.fixture()
def runner_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    connection.executemany(
        """
        INSERT INTO trading_calendar (trade_date, is_open, prev_trade_date, next_trade_date)
        VALUES (?, true, NULL, NULL)
        """,
        [(date(2026, 1, day),) for day in range(1, 5)],
    )
    connection.executemany(
        """
        INSERT INTO daily_prices (stock_code, trade_date, close, adj_factor, is_suspended)
        VALUES (?, ?, ?, ?, false)
        """,
        [
            ("A", date(2026, 1, 1), 10.0, 1.0),
            ("A", date(2026, 1, 2), 11.0, 1.0),
            ("A", date(2026, 1, 3), 12.0, 1.0),
            ("B", date(2026, 1, 1), 20.0, 1.0),
            ("B", date(2026, 1, 2), 19.0, 1.0),
            ("B", date(2026, 1, 3), 18.0, 1.0),
            ("C", date(2026, 1, 1), 30.0, 1.0),
            ("C", date(2026, 1, 2), 31.0, 1.0),
            ("C", date(2026, 1, 3), 33.0, 1.0),
        ],
    )
    connection.executemany(
        """
        INSERT INTO factor_values (
            stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("A", date(2026, 1, 1), "return_20d", 1.0, date(2026, 1, 1), "run1"),
            ("B", date(2026, 1, 1), "return_20d", 2.0, date(2026, 1, 1), "run1"),
            ("C", date(2026, 1, 1), "return_20d", 3.0, date(2026, 1, 2), "run1"),
            ("A", date(2026, 1, 1), "pe_ttm_percentile", 2.0, date(2026, 1, 1), "run1"),
            ("B", date(2026, 1, 1), "pe_ttm_percentile", 1.0, date(2026, 1, 1), "run1"),
            ("C", date(2026, 1, 1), "pe_ttm_percentile", 3.0, date(2026, 1, 1), "run1"),
            ("A", date(2026, 1, 1), "is_st", 0.0, date(2026, 1, 1), "run1"),
            ("C", date(2026, 1, 1), "is_st", 1.0, date(2026, 1, 1), "run1"),
            ("B", date(2026, 1, 1), "is_suspended", 0.0, date(2026, 1, 1), "run1"),
            ("A", date(2026, 1, 2), "return_20d", 2.0, date(2026, 1, 2), "run1"),
            ("B", date(2026, 1, 2), "return_20d", 1.0, date(2026, 1, 2), "run1"),
            ("C", date(2026, 1, 2), "return_20d", 3.0, date(2026, 1, 2), "run1"),
            ("A", date(2026, 1, 2), "return_20d", 99.0, date(2026, 1, 2), "other-run"),
        ],
    )
    try:
        yield connection
    finally:
        connection.close()


def test_validate_factors_filters_inputs_and_uses_factor_signal_dates(
    runner_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = validate_factors(
        runner_connection,
        start_date="2026-01-01",
        end_date="2026-01-03",
        source_run_id="run1",
        factor_names=["return_20d"],
        validation_config=VALIDATION_CONFIG,
        data_dictionary=DATA_DICTIONARY,
    )

    assert set(result.coverage["trade_date"]) == {date(2026, 1, 1), date(2026, 1, 2)}
    first_day = result.coverage[result.coverage["trade_date"] == date(2026, 1, 1)].iloc[0]
    second_day = result.coverage[result.coverage["trade_date"] == date(2026, 1, 2)].iloc[0]
    assert first_day["universe_source"] == "hard_filters"
    assert first_day["universe_count"] == 3
    assert first_day["valid_factor_count"] == 2
    assert first_day["missing_count"] == 1
    assert first_day["coverage"] == pytest.approx(2 / 3)
    assert first_day["missing_rate"] == pytest.approx(1 / 3)
    assert second_day["universe_source"] == "factor_values_fallback"
    assert any("fallback" in warning for warning in result.warnings)
    assert result.label_summary.iloc[0]["valid_label_count"] == 6
    assert result.label_summary.iloc[0]["latest_usable_signal_date"] == date(2026, 1, 2)
    assert not result.rank_ic.empty
    assert not result.ic_summary.empty
    assert not result.group_returns.empty
    assert not result.decay_curve.empty


def test_validate_factors_defaults_exclude_hard_filters_and_include_warning_when_requested(
    runner_connection: duckdb.DuckDBPyConnection,
) -> None:
    default = validate_factors(
        runner_connection,
        start_date="2026-01-01",
        end_date="2026-01-01",
        source_run_id="run1",
        validation_config=VALIDATION_CONFIG,
        data_dictionary=DATA_DICTIONARY,
    )
    included = validate_factors(
        runner_connection,
        start_date="2026-01-01",
        end_date="2026-01-01",
        source_run_id="run1",
        factor_names=["is_st"],
        include_hard_filters=True,
        validation_config=VALIDATION_CONFIG,
        data_dictionary=DATA_DICTIONARY,
    )

    assert "is_st" not in set(default.coverage["factor_name"])
    assert "is_st" in set(included.coverage["factor_name"])
    assert math.isnan(included.rank_ic.iloc[0]["oriented_rank_ic"])
    assert included.group_returns.empty
    assert any("Boolean hard filters" in warning for warning in included.warnings)


def test_validate_factors_rejects_hard_filter_without_flag(
    runner_connection: duckdb.DuckDBPyConnection,
) -> None:
    with pytest.raises(ValueError, match="include_hard_filters"):
        validate_factors(
            runner_connection,
            start_date="2026-01-01",
            end_date="2026-01-01",
            source_run_id="run1",
            factor_names=["is_st"],
            validation_config=VALIDATION_CONFIG,
            data_dictionary=DATA_DICTIONARY,
        )


def test_validate_factors_fails_fast_on_duplicate_keys(
    runner_connection: duckdb.DuckDBPyConnection,
) -> None:
    runner_connection.execute("DROP INDEX idx_factor_values_unique_key")
    duplicate_rows = []
    for index in range(6):
        stock_code = f"D{index}"
        duplicate_rows.extend(
            [
                (
                    stock_code,
                    date(2026, 1, 1),
                    "return_20d",
                    1.0,
                    date(2026, 1, 1),
                    "dup-run",
                ),
                (
                    stock_code,
                    date(2026, 1, 1),
                    "return_20d",
                    2.0,
                    date(2026, 1, 1),
                    "dup-run",
                ),
            ]
        )
    runner_connection.executemany(
        """
        INSERT INTO factor_values (
            stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        duplicate_rows,
    )

    with pytest.raises(ValueError) as excinfo:
        validate_factors(
            runner_connection,
            start_date="2026-01-01",
            end_date="2026-01-01",
            source_run_id="dup-run",
            factor_names=["return_20d"],
            validation_config=VALIDATION_CONFIG,
            data_dictionary=DATA_DICTIONARY,
        )

    message = str(excinfo.value)
    assert "Duplicate factor_values rows" in message
    assert message.count("count=") == 5


def test_validate_factors_rejects_unknown_factor_and_missing_direction(
    runner_connection: duckdb.DuckDBPyConnection,
) -> None:
    with pytest.raises(ValueError, match="Unknown factor"):
        validate_factors(
            runner_connection,
            start_date="2026-01-01",
            end_date="2026-01-01",
            source_run_id="run1",
            factor_names=["unknown_factor"],
            validation_config=VALIDATION_CONFIG,
            data_dictionary=DATA_DICTIONARY,
        )

    bad_dictionary = deepcopy(DATA_DICTIONARY)
    bad_dictionary["factors"]["return_20d"].pop("direction")
    with pytest.raises(ValueError, match="direction"):
        validate_factors(
            runner_connection,
            start_date="2026-01-01",
            end_date="2026-01-01",
            source_run_id="run1",
            factor_names=["return_20d"],
            validation_config=VALIDATION_CONFIG,
            data_dictionary=bad_dictionary,
        )


def test_validate_factors_requires_explicit_source_run_id(
    runner_connection: duckdb.DuckDBPyConnection,
) -> None:
    with pytest.raises(ValueError, match="source_run_id"):
        validate_factors(
            runner_connection,
            start_date="2026-01-01",
            end_date="2026-01-01",
            source_run_id="",
            validation_config=VALIDATION_CONFIG,
            data_dictionary=DATA_DICTIONARY,
        )
