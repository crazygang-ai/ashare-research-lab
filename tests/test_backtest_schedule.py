from __future__ import annotations

from datetime import date

import duckdb
import pytest

from ashare.backtest.engine import run_topn_equal_weight_backtest
from ashare.backtest.schedule import get_execution_date, get_month_end_signal_dates
from ashare.storage.db import default_schema_path


DATA_DICTIONARY = {
    "factors": {
        "return_20d": {"type": "factor", "direction": "higher_is_better"},
        "is_st": {"type": "hard_filter", "direction": "boolean_filter"},
        "is_suspended": {"type": "hard_filter", "direction": "boolean_filter"},
        "is_delisted": {"type": "hard_filter", "direction": "boolean_filter"},
        "low_liquidity": {"type": "hard_filter", "direction": "boolean_filter"},
    }
}


def _connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    return connection


def test_month_end_signal_dates_use_open_trading_days_and_next_open_execution() -> None:
    connection = _connection()
    try:
        connection.executemany(
            """
            INSERT INTO trading_calendar (trade_date, is_open)
            VALUES (?, ?)
            """,
            [
                (date(2026, 1, 29), True),
                (date(2026, 1, 30), False),
                (date(2026, 2, 2), True),
                (date(2026, 2, 27), True),
                (date(2026, 3, 2), True),
            ],
        )

        assert get_month_end_signal_dates(connection, "2026-01-01", "2026-02-28") == [
            date(2026, 1, 29),
            date(2026, 2, 27),
        ]
        assert get_execution_date(connection, "2026-01-29", "2026-02-28") == date(2026, 2, 2)
        assert get_execution_date(connection, "2026-02-27", "2026-02-28") is None
    finally:
        connection.close()


def test_engine_warns_for_missing_signal_and_execution_after_end() -> None:
    connection = _connection()
    try:
        connection.executemany(
            "INSERT INTO trading_calendar (trade_date, is_open) VALUES (?, true)",
            [
                (date(2026, 1, 29),),
                (date(2026, 2, 2),),
                (date(2026, 2, 27),),
                (date(2026, 3, 2),),
                (date(2026, 3, 13),),
                (date(2026, 3, 16),),
            ],
        )
        connection.execute(
            """
            INSERT INTO universe_members (
                index_code, stock_code, in_date, in_effective_date, source
            )
            VALUES ('LOCAL', 'A', '2020-01-01', '2020-01-01', 'fixture')
            """
        )
        connection.execute(
            """
            INSERT INTO securities (stock_code, stock_name, exchange, list_date)
            VALUES ('A', 'Alpha', 'SSE', '2020-01-01')
            """
        )
        connection.executemany(
            """
            INSERT INTO daily_prices (
                stock_code, trade_date, open, high, low, close, volume, amount,
                adj_factor, is_suspended, limit_up, limit_down
            )
            VALUES ('A', ?, 10, 11, 9, 10, 1000, 10000, 1, false, 11, 9)
            """,
            [
                (date(2026, 1, 29),),
                (date(2026, 2, 2),),
                (date(2026, 2, 27),),
                (date(2026, 3, 2),),
                (date(2026, 3, 13),),
            ],
        )
        connection.execute(
            """
            INSERT INTO valuation_daily (stock_code, trade_date, total_mv, float_mv, source)
            VALUES ('A', '2026-01-29', 100, 80, 'fixture')
            """
        )
        rows = []
        for factor_name, factor_value in [
            ("return_20d", 0.1),
            ("is_st", 0.0),
            ("is_suspended", 0.0),
            ("is_delisted", 0.0),
            ("low_liquidity", 0.0),
        ]:
            rows.append(("A", date(2026, 1, 29), factor_name, factor_value, date(2026, 1, 29), "run"))
        connection.executemany(
            """
            INSERT INTO factor_values (
                stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

        result = run_topn_equal_weight_backtest(
            connection,
            start_date="2026-01-01",
            end_date="2026-03-13",
            source_run_id="run",
            sort_factor="return_20d",
            index_code="LOCAL",
            top_n=1,
            data_dictionary=DATA_DICTIONARY,
        )

        assert result.rebalance_summary["signal_date"].tolist() == [date(2026, 1, 29)]
        assert any("no factor_values rows" in warning for warning in result.warnings)
        assert any("after end_date" in warning for warning in result.warnings)

        with pytest.raises(ValueError, match="No executable backtest signals"):
            run_topn_equal_weight_backtest(
                connection,
                start_date="2026-01-01",
                end_date="2026-03-13",
                source_run_id="missing-run",
                sort_factor="return_20d",
                index_code="LOCAL",
                top_n=1,
                data_dictionary=DATA_DICTIONARY,
            )
    finally:
        connection.close()
