from __future__ import annotations

from datetime import date

import duckdb
import pytest

from ashare.backtest.signals import build_topn_targets
from ashare.storage.db import default_schema_path


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


@pytest.fixture()
def signal_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    for stock_code in ["A", "B", "C", "D", "E", "F"]:
        connection.execute(
            """
            INSERT INTO universe_members (
                index_code, stock_code, in_date, in_effective_date, source
            )
            VALUES ('LOCAL', ?, '2020-01-01', '2020-01-01', 'fixture')
            """,
            [stock_code],
        )
    rows: list[tuple[str, date, str, float, date, str]] = []

    def add(stock_code: str, factor_name: str, value: float, as_of: date = date(2026, 1, 31)) -> None:
        rows.append((stock_code, date(2026, 1, 31), factor_name, value, as_of, "run"))

    for stock_code in ["A", "B", "C", "D", "E", "F"]:
        if stock_code not in {"D", "E"}:
            add(stock_code, "is_st", 0.0)
        add(stock_code, "is_suspended", 0.0)
        add(stock_code, "is_delisted", 0.0)
        add(stock_code, "low_liquidity", 0.0)

    add("A", "return_20d", 0.5, date(2026, 1, 30))
    add("A", "return_20d", 0.9, date(2026, 1, 31))
    add("A", "pe_ttm_percentile", 0.4)
    add("B", "return_20d", 0.9)
    add("B", "pe_ttm_percentile", 0.2)
    add("C", "return_20d", 0.1)
    add("C", "pe_ttm_percentile", 0.1)
    add("D", "return_20d", 1.0)
    add("D", "pe_ttm_percentile", 0.0)
    add("E", "return_20d", 0.8)
    add("E", "pe_ttm_percentile", 0.3)
    add("E", "is_st", 1.0)
    add("F", "pe_ttm_percentile", 0.05)

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


def test_topn_targets_use_latest_visible_as_of_higher_sort_tie_and_hard_filters(
    signal_connection: duckdb.DuckDBPyConnection,
) -> None:
    targets = build_topn_targets(
        signal_connection,
        signal_date="2026-01-31",
        source_run_id="run",
        sort_factor="return_20d",
        index_code="LOCAL",
        top_n=4,
        data_dictionary=DATA_DICTIONARY,
    )

    assert targets["stock_code"].tolist() == ["A", "B", "C"]
    assert targets["rank"].tolist() == [1, 2, 3]
    assert targets["sort_factor_value"].tolist() == [0.9, 0.9, 0.1]
    assert targets["target_weight"].tolist() == pytest.approx([1 / 3, 1 / 3, 1 / 3])
    assert "D" not in set(targets["stock_code"])
    assert "E" not in set(targets["stock_code"])
    assert "F" not in set(targets["stock_code"])


def test_topn_targets_lower_is_better_covers_pe_percentile(
    signal_connection: duckdb.DuckDBPyConnection,
) -> None:
    targets = build_topn_targets(
        signal_connection,
        signal_date=date(2026, 1, 31),
        source_run_id="run",
        sort_factor="pe_ttm_percentile",
        index_code="LOCAL",
        top_n=3,
        data_dictionary=DATA_DICTIONARY,
    )

    assert targets["stock_code"].tolist() == ["F", "C", "B"]
    assert targets["sort_factor_value"].tolist() == [0.05, 0.1, 0.2]


def test_topn_targets_fail_fast_for_duplicate_latest_as_of(
    signal_connection: duckdb.DuckDBPyConnection,
) -> None:
    signal_connection.execute("DROP INDEX idx_factor_values_unique_key")
    duplicate_rows = [
        ("A", date(2026, 1, 31), "return_20d", 1.0, date(2026, 1, 31), "dup-run"),
        ("A", date(2026, 1, 31), "return_20d", 2.0, date(2026, 1, 31), "dup-run"),
    ]
    signal_connection.executemany(
        """
        INSERT INTO factor_values (
            stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        duplicate_rows,
    )

    with pytest.raises(ValueError, match="Duplicate factor_values rows"):
        build_topn_targets(
            signal_connection,
            signal_date="2026-01-31",
            source_run_id="dup-run",
            sort_factor="return_20d",
            index_code="LOCAL",
            top_n=1,
            data_dictionary=DATA_DICTIONARY,
        )


def test_boolean_filter_cannot_be_sort_factor(signal_connection: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError, match="boolean_filter"):
        build_topn_targets(
            signal_connection,
            signal_date="2026-01-31",
            source_run_id="run",
            sort_factor="is_st",
            index_code="LOCAL",
            top_n=1,
            data_dictionary=DATA_DICTIONARY,
        )
