from __future__ import annotations

from datetime import date

import duckdb
import pytest

from ashare.storage.db import default_schema_path
from ashare.validation.labels import build_forward_return_labels


@pytest.fixture()
def label_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    connection.executemany(
        """
        INSERT INTO trading_calendar (trade_date, is_open, prev_trade_date, next_trade_date)
        VALUES (?, ?, NULL, NULL)
        """,
        [
            (date(2026, 1, 2), True),
            (date(2026, 1, 3), False),
            (date(2026, 1, 4), False),
            (date(2026, 1, 5), True),
            (date(2026, 1, 6), True),
        ],
    )
    connection.executemany(
        """
        INSERT INTO daily_prices (
            stock_code, trade_date, close, adj_factor, is_suspended
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("000001.SZ", date(2026, 1, 2), 10.0, 2.0, False),
            ("000001.SZ", date(2026, 1, 5), 12.0, 2.0, False),
            ("000001.SZ", date(2026, 1, 6), 15.0, 2.0, False),
            ("000002.SZ", date(2026, 1, 2), 10.0, None, False),
            ("000002.SZ", date(2026, 1, 5), 11.0, None, False),
            ("000003.SZ", date(2026, 1, 2), 20.0, 1.0, False),
            ("000004.SZ", date(2026, 1, 2), 30.0, 1.0, True),
            ("000004.SZ", date(2026, 1, 5), 33.0, 1.0, True),
        ],
    )
    try:
        yield connection
    finally:
        connection.close()


def test_forward_return_uses_hth_subsequent_open_trading_day(
    label_connection: duckdb.DuckDBPyConnection,
) -> None:
    labels = build_forward_return_labels(
        label_connection,
        signal_dates=[date(2026, 1, 2)],
        horizons=[1, 2],
    )

    alpha_h1 = labels[
        (labels["stock_code"] == "000001.SZ") & (labels["horizon"] == 1)
    ].iloc[0]
    alpha_h2 = labels[
        (labels["stock_code"] == "000001.SZ") & (labels["horizon"] == 2)
    ].iloc[0]

    assert alpha_h1["target_trade_date"] == date(2026, 1, 5)
    assert alpha_h2["target_trade_date"] == date(2026, 1, 6)
    assert alpha_h1["forward_return"] == pytest.approx(0.2)
    assert alpha_h2["forward_return"] == pytest.approx(0.5)


def test_h1_uses_next_open_day_and_adjusted_close_fallback(
    label_connection: duckdb.DuckDBPyConnection,
) -> None:
    labels = build_forward_return_labels(
        label_connection,
        signal_dates=[date(2026, 1, 2)],
        horizons=[1],
    )

    beta = labels[labels["stock_code"] == "000002.SZ"].iloc[0]

    assert beta["target_trade_date"] == date(2026, 1, 5)
    assert beta["forward_return"] == pytest.approx(0.1)


def test_missing_start_or_target_price_omits_label(
    label_connection: duckdb.DuckDBPyConnection,
) -> None:
    labels = build_forward_return_labels(
        label_connection,
        signal_dates=[date(2026, 1, 2)],
        horizons=[1],
    )

    assert "000003.SZ" not in set(labels["stock_code"])
    assert "000004.SZ" in set(labels["stock_code"])
