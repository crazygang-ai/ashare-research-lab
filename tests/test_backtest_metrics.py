from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from ashare.backtest.metrics import METRIC_COLUMNS, calculate_backtest_metrics


def test_metrics_are_wide_single_row_and_capture_cost_drag_turnover_and_benchmarks() -> None:
    equity = pd.DataFrame(
        [
            {
                "trade_date": date(2026, 1, 1),
                "nav": 1000.0,
                "net_return": 0.0,
                "drawdown": 0.0,
            },
            {
                "trade_date": date(2026, 1, 2),
                "nav": 1100.0,
                "net_return": 0.1,
                "drawdown": 0.0,
            },
            {
                "trade_date": date(2026, 1, 3),
                "nav": 1045.0,
                "net_return": -0.05,
                "drawdown": -0.05,
            },
        ]
    )
    benchmark = pd.DataFrame(
        [
            {"trade_date": date(2026, 1, 1), "cap_weight_nav": 1.0, "equal_weight_nav": 1.0},
            {"trade_date": date(2026, 1, 3), "cap_weight_nav": 1.02, "equal_weight_nav": 1.03},
        ]
    )
    rebalance = pd.DataFrame(
        [{"one_way_turnover": 0.2}, {"one_way_turnover": 0.4}]
    )
    trades = pd.DataFrame(
        [
            {
                "order_status": "executed",
                "commission": 3.0,
                "stamp_tax": 1.0,
                "slippage_cost": 2.0,
                "total_cost": 6.0,
            },
            {
                "order_status": "rejected",
                "commission": 0.0,
                "stamp_tax": 0.0,
                "slippage_cost": 0.0,
                "total_cost": 0.0,
            },
            {
                "order_status": "forced_delist_exit",
                "commission": 0.0,
                "stamp_tax": 0.0,
                "slippage_cost": 0.0,
                "total_cost": 0.0,
            },
        ]
    )

    metrics = calculate_backtest_metrics(
        equity_curve=equity,
        benchmark_returns=benchmark,
        rebalance_summary=rebalance,
        trade_ledger=trades,
        initial_cash=1000.0,
    )

    assert metrics.columns.tolist() == METRIC_COLUMNS
    assert len(metrics) == 1
    row = metrics.iloc[0]
    assert row["net_return"] == pytest.approx(0.045)
    assert row["gross_return"] == pytest.approx(0.051)
    assert row["cost_drag"] == pytest.approx(0.006)
    assert row["average_turnover"] == pytest.approx(0.3)
    assert row["max_turnover"] == pytest.approx(0.4)
    assert row["benchmark_cap_weight_return"] == pytest.approx(0.02)
    assert row["excess_return_vs_equal_weight"] == pytest.approx(0.015)
    assert row["trade_count"] == 2
    assert row["rejected_order_count"] == 1
    assert row["forced_delist_exit_count"] == 1
