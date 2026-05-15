from __future__ import annotations

from datetime import date

import duckdb
import pytest

from ashare.backtest.benchmark import BENCHMARK_COLUMNS, calculate_synthetic_benchmarks
from ashare.storage.db import default_schema_path


def _connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    connection.executemany(
        "INSERT INTO trading_calendar (trade_date, is_open) VALUES (?, true)",
        [(date(2026, 1, 31),), (date(2026, 2, 2),), (date(2026, 2, 3),)],
    )
    connection.executemany(
        """
        INSERT INTO universe_members (
            index_code, stock_code, in_date, in_effective_date, source
        )
        VALUES ('LOCAL', ?, ?, ?, 'fixture')
        """,
        [
            ("A", date(2020, 1, 1), date(2020, 1, 1)),
            ("B", date(2020, 1, 1), date(2020, 1, 1)),
            ("C", date(2026, 2, 3), date(2026, 2, 3)),
        ],
    )
    connection.executemany(
        """
        INSERT INTO valuation_daily (stock_code, trade_date, total_mv, float_mv, source)
        VALUES (?, '2026-01-31', ?, ?, 'fixture')
        """,
        [("A", 100.0, 80.0), ("B", 300.0, None)],
    )
    prices = [
        ("A", date(2026, 1, 31), 10.0, 1.0, False),
        ("B", date(2026, 1, 31), 10.0, None, False),
        ("C", date(2026, 1, 31), 30.0, 1.0, False),
        ("A", date(2026, 2, 2), 11.0, 1.0, False),
        ("B", date(2026, 2, 2), 20.0, None, False),
        ("C", date(2026, 2, 2), 30.0, 1.0, False),
        ("A", date(2026, 2, 3), 12.1, 1.0, False),
        ("B", date(2026, 2, 3), 20.0, None, True),
        ("C", date(2026, 2, 3), 33.0, 1.0, False),
    ]
    connection.executemany(
        """
        INSERT INTO daily_prices (
            stock_code, trade_date, open, high, low, close, volume, amount,
            adj_factor, is_suspended, limit_up, limit_down
        )
        VALUES (?, ?, ?, ?, ?, ?, 1000, 10000, ?, ?, NULL, NULL)
        """,
        [(code, day, close, close, close, close, adj, suspended) for code, day, close, adj, suspended in prices],
    )
    return connection


def test_synthetic_benchmarks_use_pit_static_universe_market_cap_fallback_and_coverage() -> None:
    connection = _connection()
    try:
        benchmark, warnings = calculate_synthetic_benchmarks(
            connection,
            start_date="2026-01-31",
            end_date="2026-02-03",
            index_code="LOCAL",
            signal_dates=[date(2026, 1, 31)],
            initial_nav=1.0,
        )

        assert benchmark.columns.tolist() == BENCHMARK_COLUMNS
        assert benchmark["equal_weight_member_count"].tolist() == [2, 2, 2]
        feb2 = benchmark[benchmark["trade_date"].eq(date(2026, 2, 2))].iloc[0]
        feb3 = benchmark[benchmark["trade_date"].eq(date(2026, 2, 3))].iloc[0]
        cap_weight_a = 80.0 / (80.0 + 300.0)
        cap_weight_b = 300.0 / (80.0 + 300.0)
        assert feb2["cap_weight_return"] == pytest.approx(cap_weight_a * 0.1 + cap_weight_b * 1.0)
        assert feb2["equal_weight_return"] == pytest.approx(0.5 * 0.1 + 0.5 * 1.0)
        assert feb3["cap_weight_coverage"] == pytest.approx(0.5)
        assert feb3["equal_weight_coverage"] == pytest.approx(0.5)
        assert any("close fallback" in warning for warning in warnings)
    finally:
        connection.close()
