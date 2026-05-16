from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from ashare.factors.store import write_factor_values
from ashare.storage.db import init_db


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stock_code": "A",
                "trade_date": date(2026, 1, 2),
                "factor_name": "return_20d",
                "factor_value": 0.1,
                "as_of_date": date(2026, 1, 2),
            }
        ]
    )


def test_factor_store_default_fails_on_duplicate_existing_keys(tmp_path) -> None:
    db_path = tmp_path / "db.duckdb"
    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        assert write_factor_values(connection, _frame(), source_run_id="run") == 1
        with pytest.raises(ValueError, match="Duplicate key sample"):
            write_factor_values(connection, _frame(), source_run_id="run")
    finally:
        connection.close()


def test_factor_store_fails_on_duplicate_incoming_keys(tmp_path) -> None:
    db_path = tmp_path / "db.duckdb"
    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        duplicated = pd.concat([_frame(), _frame()], ignore_index=True)
        with pytest.raises(ValueError, match="Duplicate incoming"):
            write_factor_values(connection, duplicated, source_run_id="run")
    finally:
        connection.close()
