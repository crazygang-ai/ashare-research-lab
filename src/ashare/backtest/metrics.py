"""Performance metrics for Phase 1b simple portfolio backtests."""

from __future__ import annotations

import math

import pandas as pd


METRIC_COLUMNS = [
    "total_return",
    "annualized_return",
    "volatility",
    "max_drawdown",
    "sharpe",
    "calmar",
    "win_rate",
    "gross_return",
    "net_return",
    "cost_drag",
    "total_cost",
    "commission",
    "stamp_tax",
    "slippage_cost",
    "average_turnover",
    "max_turnover",
    "benchmark_cap_weight_return",
    "benchmark_equal_weight_return",
    "excess_return_vs_cap_weight",
    "excess_return_vs_equal_weight",
    "tracking_difference_vs_cap_weight",
    "tracking_difference_vs_equal_weight",
    "rebalance_count",
    "trade_count",
    "rejected_order_count",
    "forced_delist_exit_count",
]


def calculate_backtest_metrics(
    equity_curve: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    rebalance_summary: pd.DataFrame,
    trade_ledger: pd.DataFrame,
    initial_cash: float,
) -> pd.DataFrame:
    """Calculate the stable wide-format Phase 1b metrics row."""
    if equity_curve.empty:
        return pd.DataFrame([{column: 0.0 for column in METRIC_COLUMNS}], columns=METRIC_COLUMNS)

    initial = float(initial_cash)
    final_nav = float(equity_curve.iloc[-1]["nav"])
    total_cost = _sum_column(trade_ledger, "total_cost")
    commission = _sum_column(trade_ledger, "commission")
    stamp_tax = _sum_column(trade_ledger, "stamp_tax")
    slippage_cost = _sum_column(trade_ledger, "slippage_cost")
    net_return = final_nav / initial - 1.0 if initial else 0.0
    gross_return = (final_nav + total_cost) / initial - 1.0 if initial else net_return
    cost_drag = gross_return - net_return

    returns = pd.to_numeric(equity_curve["net_return"], errors="coerce").fillna(0.0)
    returns_for_stats = returns.iloc[1:] if len(returns) > 1 else returns
    trading_days = max(len(equity_curve), 1)
    annualized_return = _annualized_return(net_return, trading_days)
    volatility = float(returns_for_stats.std(ddof=1) * math.sqrt(252.0)) if len(returns_for_stats) > 1 else 0.0
    mean_return = float(returns_for_stats.mean()) if len(returns_for_stats) else 0.0
    sharpe = mean_return / returns_for_stats.std(ddof=1) * math.sqrt(252.0) if volatility > 0 else 0.0
    max_drawdown = float(pd.to_numeric(equity_curve["drawdown"], errors="coerce").min())
    calmar = annualized_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    win_rate = float((returns_for_stats > 0).mean()) if len(returns_for_stats) else 0.0

    cap_return = _last_nav_return(benchmark_returns, "cap_weight_nav")
    equal_return = _last_nav_return(benchmark_returns, "equal_weight_nav")

    metrics = {
        "total_return": net_return,
        "annualized_return": annualized_return,
        "volatility": volatility,
        "max_drawdown": max_drawdown,
        "sharpe": float(sharpe),
        "calmar": float(calmar),
        "win_rate": win_rate,
        "gross_return": gross_return,
        "net_return": net_return,
        "cost_drag": cost_drag,
        "total_cost": total_cost,
        "commission": commission,
        "stamp_tax": stamp_tax,
        "slippage_cost": slippage_cost,
        "average_turnover": _mean_column(rebalance_summary, "one_way_turnover"),
        "max_turnover": _max_column(rebalance_summary, "one_way_turnover"),
        "benchmark_cap_weight_return": cap_return,
        "benchmark_equal_weight_return": equal_return,
        "excess_return_vs_cap_weight": net_return - cap_return,
        "excess_return_vs_equal_weight": net_return - equal_return,
        "tracking_difference_vs_cap_weight": net_return - cap_return,
        "tracking_difference_vs_equal_weight": net_return - equal_return,
        "rebalance_count": float(len(rebalance_summary)),
        "trade_count": float(_trade_count(trade_ledger)),
        "rejected_order_count": float(_status_count(trade_ledger, "rejected")),
        "forced_delist_exit_count": float(_status_count(trade_ledger, "forced_delist_exit")),
    }
    return pd.DataFrame([metrics], columns=METRIC_COLUMNS)


def _annualized_return(total_return: float, trading_days: int) -> float:
    if trading_days <= 0:
        return 0.0
    base = 1.0 + total_return
    if base <= 0:
        return -1.0
    return float(base ** (252.0 / trading_days) - 1.0)


def _sum_column(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum())


def _mean_column(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if len(values) else 0.0


def _max_column(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.max()) if len(values) else 0.0


def _last_nav_return(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    nav = float(frame.iloc[-1][column])
    return nav - 1.0


def _trade_count(frame: pd.DataFrame) -> int:
    if frame.empty or "order_status" not in frame.columns:
        return 0
    return int(frame["order_status"].isin(["executed", "forced_delist_exit"]).sum())


def _status_count(frame: pd.DataFrame, status: str) -> int:
    if frame.empty or "order_status" not in frame.columns:
        return 0
    return int(frame["order_status"].eq(status).sum())
