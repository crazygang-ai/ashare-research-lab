from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from ashare.storage.db import default_schema_path
from ashare.storage.universe_snapshots import (
    factor_run_universe_fingerprint,
    load_factor_run_universe,
    write_factor_run_universe,
)
from ashare.validation.runner import validate_factors


DATA_DICTIONARY = {
    "factors": {
        "return_20d": {"type": "factor", "direction": "higher_is_better"},
        "is_st": {"type": "hard_filter", "direction": "boolean_filter"},
    }
}

VALIDATION_CONFIG = {
    "single_factor": {
        "horizons": [1],
        "n_groups": 2,
        "min_ic_observations": 2,
        "min_group_size": 1,
        "require_same_as_of_trade_date": True,
        "universe_factor_names": ["is_st"],
        "label": {"price": "adjusted_close", "return_type": "close_to_close"},
    }
}


def test_factor_validation_uses_explicit_universe_snapshot() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    try:
        connection.executemany(
            """
            INSERT INTO trading_calendar (trade_date, is_open, source)
            VALUES (?, true, 'fixture')
            """,
            [(date(2026, 1, 1),), (date(2026, 1, 2),), (date(2026, 1, 3),)],
        )
        connection.executemany(
            """
            INSERT INTO daily_prices (stock_code, trade_date, close, adj_factor, source)
            VALUES (?, ?, ?, 1.0, 'fixture')
            """,
            [
                ("A", date(2026, 1, 1), 10.0),
                ("A", date(2026, 1, 2), 11.0),
                ("B", date(2026, 1, 1), 20.0),
                ("B", date(2026, 1, 2), 19.0),
                ("C", date(2026, 1, 1), 30.0),
                ("C", date(2026, 1, 2), 30.0),
            ],
        )
        connection.executemany(
            """
            INSERT INTO factor_values
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("A", date(2026, 1, 1), "return_20d", 1.0, date(2026, 1, 1), "run"),
                ("B", date(2026, 1, 1), "return_20d", 2.0, date(2026, 1, 1), "run"),
            ],
        )
        universe = pd.DataFrame(
            {
                "index_code": ["LOCAL", "LOCAL", "LOCAL"],
                "stock_code": ["A", "B", "C"],
                "source": ["fixture", "fixture", "fixture"],
                "source_tag": ["fixture", "fixture", "fixture"],
                "universe_kind": ["historical_pit", "historical_pit", "historical_pit"],
            }
        )
        write_factor_run_universe(
            connection,
            source_run_id="run",
            trade_date=date(2026, 1, 1),
            as_of_date=date(2026, 1, 1),
            index_code="LOCAL",
            universe=universe,
            data_source="fixture",
        )

        result = validate_factors(
            connection,
            start_date="2026-01-01",
            end_date="2026-01-01",
            source_run_id="run",
            factor_names=["return_20d"],
            validation_config=VALIDATION_CONFIG,
            data_dictionary=DATA_DICTIONARY,
            index_code="LOCAL",
            data_source="fixture",
            require_universe_snapshot=True,
            require_historical_pit_universe=True,
        )
        snapshot = load_factor_run_universe(
            connection,
            source_run_id="run",
            trade_date=date(2026, 1, 1),
            index_code="LOCAL",
        )
        fingerprint = factor_run_universe_fingerprint(
            connection,
            source_run_id="run",
            index_code="LOCAL",
        )
    finally:
        connection.close()

    first = result.coverage.iloc[0]
    assert first["universe_source"] == "factor_run_universe:historical_pit"
    assert first["universe_count"] == 3
    assert first["valid_factor_count"] == 2
    assert len(snapshot) == 3
    assert fingerprint and fingerprint.startswith("universe:")


def test_formal_validation_rejects_current_snapshot_universe() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    try:
        write_factor_run_universe(
            connection,
            source_run_id="run",
            trade_date=date(2026, 1, 1),
            as_of_date=date(2026, 1, 1),
            index_code="LOCAL",
            universe=pd.DataFrame(
                {
                    "index_code": ["LOCAL"],
                    "stock_code": ["A"],
                    "source": ["akshare"],
                    "source_tag": ["akshare"],
                    "universe_kind": ["current_snapshot"],
                }
            ),
            data_source="akshare",
        )
        connection.execute(
            """
            INSERT INTO factor_values
            VALUES ('A', DATE '2026-01-01', 'return_20d', 1.0, DATE '2026-01-01', 'run')
            """
        )
        with pytest.raises(ValueError, match="historical PIT universe"):
            validate_factors(
                connection,
                start_date="2026-01-01",
                end_date="2026-01-01",
                source_run_id="run",
                factor_names=["return_20d"],
                validation_config=VALIDATION_CONFIG,
                data_dictionary=DATA_DICTIONARY,
                index_code="LOCAL",
                require_universe_snapshot=True,
                require_historical_pit_universe=True,
            )
    finally:
        connection.close()
