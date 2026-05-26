from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from ashare.backtest.broker import execute_rebalance
from ashare.backtest.costs import calculate_trade_costs
from ashare.storage.db import default_schema_path


EXECUTION_DATE = date(2026, 1, 2)
COSTS = {
    "commission_bps": 100.0,
    "stamp_tax_bps": 50.0,
    "slippage_bps": 100.0,
    "min_commission_yuan": 5.0,
}
RULES = {
    "skip_buy_if_limit_up": True,
    "block_sell_if_limit_down": True,
    "hold_if_suspended": True,
    "board_lot_size": 100,
    "allow_odd_lot_sell": True,
    "price_compare_tolerance": 0.000001,
}


def _connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    for stock_code in ["A", "B", "C", "D", "E", "F"]:
        connection.execute(
            """
            INSERT INTO securities (stock_code, stock_name, exchange, list_date)
            VALUES (?, ?, 'SSE', '2020-01-01')
            """,
            [stock_code, stock_code],
        )
    connection.execute(
        """
        UPDATE securities
        SET delist_date = ?, delist_effective_date = ?
        WHERE stock_code = 'F'
        """,
        [EXECUTION_DATE, EXECUTION_DATE],
    )
    prices = [
        ("A", 10.0, False, 11.0, 9.0),
        ("B", 20.0, False, 22.0, 18.0),
        ("C", 11.0, False, 11.0, 9.0),
        ("D", 12.0, True, 13.2, 10.8),
        ("E", 9.0, False, 11.0, 9.0),
        ("F", 5.0, False, 5.5, 4.5),
    ]
    connection.executemany(
        """
        INSERT INTO daily_prices (
            stock_code, trade_date, open, high, low, close, volume, amount,
            adj_factor, is_suspended, limit_up, limit_down
        )
        VALUES (?, ?, ?, ?, ?, ?, 1000, 10000, 1, ?, ?, ?)
        """,
        [
            (code, EXECUTION_DATE, open_, open_, open_, open_, suspended, limit_up, limit_down)
            for code, open_, suspended, limit_up, limit_down in prices
        ],
    )
    return connection


def test_costs_apply_commission_minimum_stamp_tax_and_side_rules() -> None:
    small_buy = calculate_trade_costs(
        side="buy",
        notional=100.0,
        commission_bps=2.5,
        stamp_tax_bps=10.0,
        min_commission_yuan=5.0,
    )
    sell = calculate_trade_costs(
        side="sell",
        notional=10_000.0,
        commission_bps=2.5,
        stamp_tax_bps=10.0,
        min_commission_yuan=5.0,
    )

    assert small_buy["commission"] == pytest.approx(5.0)
    assert small_buy["stamp_tax"] == 0.0
    assert sell["commission"] == pytest.approx(5.0)
    assert sell["stamp_tax"] == pytest.approx(10.0)


def test_execute_rebalance_uses_t1_open_sells_first_and_records_costs() -> None:
    connection = _connection()
    try:
        positions = pd.DataFrame([{"stock_code": "A", "shares": 300.0, "last_close": 10.0}])
        targets = pd.DataFrame([{"stock_code": "B", "target_weight": 0.5}])

        new_positions, ledger, cash_after = execute_rebalance(
            connection,
            signal_date="2026-01-01",
            execution_date=EXECUTION_DATE,
            current_positions=positions,
            target_weights=targets,
            cash=7000.0,
            nav_before_trade=12000.0,
            cost_config=COSTS,
            trading_rules=RULES,
        )

        assert ledger["side"].tolist() == ["sell", "buy"]
        sell = ledger.iloc[0]
        buy = ledger.iloc[1]
        assert sell["stock_code"] == "A"
        assert sell["executed_price"] == pytest.approx(9.9)
        assert sell["stamp_tax"] > 0
        assert buy["stock_code"] == "B"
        assert buy["executed_price"] == pytest.approx(20.2)
        assert buy["slippage_cost"] > 0
        assert cash_after < 7000.0
        assert set(new_positions["stock_code"]) == {"B"}
    finally:
        connection.close()


def test_execute_rebalance_blocks_suspension_limits_and_preserves_positions_or_cash() -> None:
    connection = _connection()
    try:
        positions = pd.DataFrame([{"stock_code": "E", "shares": 10.0, "last_close": 9.0}])
        targets = pd.DataFrame(
            [
                {"stock_code": "C", "target_weight": 0.2},
                {"stock_code": "D", "target_weight": 0.2},
            ]
        )

        new_positions, ledger, cash_after = execute_rebalance(
            connection,
            signal_date="2026-01-01",
            execution_date=EXECUTION_DATE,
            current_positions=positions,
            target_weights=targets,
            cash=1000.0,
            nav_before_trade=1000.0,
            cost_config=COSTS,
            trading_rules=RULES,
        )

        reasons = dict(zip(ledger["stock_code"], ledger["reject_reason"], strict=False))
        assert reasons["E"] == "limit_down"
        assert reasons["C"] == "limit_up"
        assert reasons["D"] == "suspended"
        assert new_positions.loc[new_positions["stock_code"].eq("E"), "shares"].iloc[0] == 10.0
        assert cash_after == pytest.approx(1000.0)
    finally:
        connection.close()


def test_execute_rebalance_forces_visible_delist_exit_and_rejects_delisted_buy() -> None:
    connection = _connection()
    try:
        positions = pd.DataFrame([{"stock_code": "F", "shares": 20.0, "last_close": 5.0}])
        targets = pd.DataFrame([{"stock_code": "F", "target_weight": 1.0}])

        new_positions, ledger, cash_after = execute_rebalance(
            connection,
            signal_date="2026-01-01",
            execution_date=EXECUTION_DATE,
            current_positions=positions,
            target_weights=targets,
            cash=500.0,
            nav_before_trade=500.0,
            cost_config=COSTS,
            trading_rules=RULES,
        )

        forced = ledger[ledger["order_status"].eq("forced_delist_exit")].iloc[0]
        rejected = ledger[ledger["order_status"].eq("rejected")].iloc[0]
        assert forced["executed_price"] == 0.0
        assert forced["executed_notional"] == 0.0
        assert rejected["reject_reason"] == "delisted"
        assert new_positions.empty
        assert cash_after == pytest.approx(500.0)
    finally:
        connection.close()


def test_execute_rebalance_rounds_buys_to_board_lots_and_allows_odd_lot_exit() -> None:
    connection = _connection()
    try:
        positions = pd.DataFrame([{"stock_code": "A", "shares": 50.0, "last_close": 10.0}])
        targets = pd.DataFrame([{"stock_code": "B", "target_weight": 1.0}])

        new_positions, ledger, _cash_after = execute_rebalance(
            connection,
            signal_date="2026-01-01",
            execution_date=EXECUTION_DATE,
            current_positions=positions,
            target_weights=targets,
            cash=6_000.0,
            nav_before_trade=5_000.0,
            cost_config=COSTS,
            trading_rules=RULES,
        )

        sell = ledger[ledger["stock_code"].eq("A")].iloc[0]
        buy = ledger[ledger["stock_code"].eq("B")].iloc[0]
        assert sell["order_status"] == "executed"
        assert sell["shares_delta"] == pytest.approx(-50.0)
        assert buy["order_status"] == "executed"
        assert buy["shares_delta"] == pytest.approx(200.0)
        assert buy["executed_notional"] == pytest.approx(4_040.0)
        assert set(new_positions["stock_code"]) == {"B"}
        assert new_positions.loc[new_positions["stock_code"].eq("B"), "shares"].iloc[0] == 200.0
    finally:
        connection.close()


def test_execute_rebalance_sells_existing_odd_lot_residual_as_one_block() -> None:
    connection = _connection()
    try:
        positions = pd.DataFrame([{"stock_code": "A", "shares": 150.0, "last_close": 10.0}])
        targets = pd.DataFrame([{"stock_code": "A", "target_weight": 0.5}])

        new_positions, ledger, _cash_after = execute_rebalance(
            connection,
            signal_date="2026-01-01",
            execution_date=EXECUTION_DATE,
            current_positions=positions,
            target_weights=targets,
            cash=500.0,
            nav_before_trade=2_000.0,
            cost_config=COSTS,
            trading_rules=RULES,
        )

        sell = ledger.iloc[0]
        assert sell["stock_code"] == "A"
        assert sell["order_status"] == "executed"
        assert sell["shares_delta"] == pytest.approx(-50.0)
        assert new_positions.loc[new_positions["stock_code"].eq("A"), "shares"].iloc[0] == 100.0
    finally:
        connection.close()


def test_execute_rebalance_rejects_buy_below_board_lot() -> None:
    connection = _connection()
    try:
        positions = pd.DataFrame(columns=["stock_code", "shares", "last_close"])
        targets = pd.DataFrame([{"stock_code": "B", "target_weight": 0.1}])

        new_positions, ledger, cash_after = execute_rebalance(
            connection,
            signal_date="2026-01-01",
            execution_date=EXECUTION_DATE,
            current_positions=positions,
            target_weights=targets,
            cash=1_000.0,
            nav_before_trade=1_000.0,
            cost_config=COSTS,
            trading_rules=RULES,
        )

        buy = ledger.iloc[0]
        assert buy["stock_code"] == "B"
        assert buy["order_status"] == "rejected"
        assert buy["reject_reason"] == "below_board_lot"
        assert new_positions.empty
        assert cash_after == pytest.approx(1_000.0)
    finally:
        connection.close()


def test_execute_rebalance_rejects_buy_when_cash_cannot_afford_one_board_lot_after_costs() -> None:
    connection = _connection()
    try:
        positions = pd.DataFrame(columns=["stock_code", "shares", "last_close"])
        targets = pd.DataFrame([{"stock_code": "B", "target_weight": 1.0}])

        new_positions, ledger, cash_after = execute_rebalance(
            connection,
            signal_date="2026-01-01",
            execution_date=EXECUTION_DATE,
            current_positions=positions,
            target_weights=targets,
            cash=2_000.0,
            nav_before_trade=5_000.0,
            cost_config=COSTS,
            trading_rules=RULES,
        )

        buy = ledger.iloc[0]
        assert buy["stock_code"] == "B"
        assert buy["order_status"] == "rejected"
        assert buy["reject_reason"] == "insufficient_cash"
        assert new_positions.empty
        assert cash_after == pytest.approx(2_000.0)
    finally:
        connection.close()


def test_execute_rebalance_rejects_partial_odd_lot_sell_when_odd_lot_sells_disabled() -> None:
    connection = _connection()
    try:
        positions = pd.DataFrame([{"stock_code": "A", "shares": 150.0, "last_close": 10.0}])
        targets = pd.DataFrame([{"stock_code": "A", "target_weight": 0.5}])
        rules = {**RULES, "allow_odd_lot_sell": False}

        new_positions, ledger, cash_after = execute_rebalance(
            connection,
            signal_date="2026-01-01",
            execution_date=EXECUTION_DATE,
            current_positions=positions,
            target_weights=targets,
            cash=500.0,
            nav_before_trade=2_000.0,
            cost_config=COSTS,
            trading_rules=rules,
        )

        sell = ledger.iloc[0]
        assert sell["stock_code"] == "A"
        assert sell["order_status"] == "rejected"
        assert sell["reject_reason"] == "below_board_lot"
        assert new_positions.loc[new_positions["stock_code"].eq("A"), "shares"].iloc[0] == 150.0
        assert cash_after == pytest.approx(500.0)
    finally:
        connection.close()
