"""Phase 1b Top N equal-weight portfolio backtest engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from ashare.backtest.benchmark import calculate_synthetic_benchmarks
from ashare.backtest.broker import TRADE_LEDGER_COLUMNS, execute_rebalance, force_delist_exits
from ashare.backtest.config import merge_backtest_config
from ashare.backtest.metrics import calculate_backtest_metrics
from ashare.backtest.schedule import (
    get_month_end_signal_dates,
    next_open_trading_date,
    open_trading_dates_between,
)
from ashare.backtest.signals import build_topn_targets, has_signal_rows
from ashare.pit.asof import DateLike, parse_as_of_date
from ashare.validation.runner import load_data_dictionary


EQUITY_COLUMNS = [
    "trade_date",
    "cash",
    "position_value",
    "nav",
    "gross_return",
    "net_return",
    "daily_cost",
    "cumulative_cost",
    "drawdown",
]
REBALANCE_COLUMNS = [
    "signal_date",
    "execution_date",
    "selected_count",
    "target_count",
    "nav_before_trade",
    "buy_notional",
    "sell_notional",
    "gross_turnover",
    "one_way_turnover",
    "commission",
    "stamp_tax",
    "slippage_cost",
    "total_cost",
    "executed_order_count",
    "rejected_order_count",
    "forced_delist_exit_count",
    "warning_count",
]
TARGET_WEIGHT_COLUMNS = [
    "signal_date",
    "execution_date",
    "stock_code",
    "rank",
    "sort_factor",
    "sort_factor_value",
    "target_weight",
    "target_notional",
]
HOLDING_COLUMNS = [
    "trade_date",
    "stock_code",
    "shares",
    "close",
    "market_value",
    "weight",
    "price_source",
]
ASSUMPTION_COLUMNS = ["key", "value"]


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    benchmark_returns: pd.DataFrame
    rebalance_summary: pd.DataFrame
    target_weights: pd.DataFrame
    holdings: pd.DataFrame
    trade_ledger: pd.DataFrame
    metrics: pd.DataFrame
    assumptions: pd.DataFrame
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ScheduledRebalance:
    signal_date: date
    execution_date: date
    targets: pd.DataFrame


def run_topn_equal_weight_backtest(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
    source_run_id: str,
    sort_factor: str,
    index_code: str,
    top_n: int = 20,
    initial_cash: float = 1_000_000,
    backtest_config: Mapping[str, object] | None = None,
    data_dictionary: Mapping[str, object] | None = None,
    data_source: str | None = None,
    require_historical_pit_universe: bool = False,
) -> BacktestResult:
    """Run a monthly Top N equal-weight backtest from stored factor signals."""
    start = parse_as_of_date(start_date)
    end = parse_as_of_date(end_date)
    if start > end:
        raise ValueError(f"start_date {start.isoformat()} is after end_date {end.isoformat()}.")
    if not source_run_id or not str(source_run_id).strip():
        raise ValueError("source_run_id must be explicitly provided.")
    if not sort_factor or not str(sort_factor).strip():
        raise ValueError("sort_factor must be explicitly provided.")
    if not index_code or not str(index_code).strip():
        raise ValueError("index_code must be explicitly provided.")
    if top_n <= 0:
        raise ValueError("top_n must be positive.")
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive.")

    config = merge_backtest_config(
        backtest_config or {},
        top_n=top_n,
        initial_cash=initial_cash,
    )
    dictionary = data_dictionary if data_dictionary is not None else load_data_dictionary()
    cost_config = _section(config, "costs")
    trading_rules = _section(config, "trading_rules")
    benchmark_config = _section(config, "benchmark")

    warnings: list[str] = []
    trading_dates = open_trading_dates_between(connection, start, end, data_source=data_source)
    if not trading_dates:
        raise ValueError("No open trading dates found in the requested backtest interval.")

    schedules = _build_rebalance_schedule(
        connection=connection,
        start=start,
        end=end,
        source_run_id=source_run_id,
        sort_factor=sort_factor,
        index_code=index_code,
        top_n=top_n,
        data_dictionary=dictionary,
        data_source=data_source,
        require_historical_pit_universe=require_historical_pit_universe,
        warnings=warnings,
    )
    if not schedules:
        raise ValueError(
            "No executable backtest signals found for the requested interval, "
            "source_run_id, sort_factor, and index_code."
        )

    schedule_by_execution = {item.execution_date: item for item in schedules}
    cash = float(initial_cash)
    positions = pd.DataFrame(columns=["stock_code", "shares", "last_close"])
    previous_nav = float(initial_cash)
    peak_nav = float(initial_cash)
    cumulative_cost = 0.0
    last_close: dict[str, float] = {}

    equity_rows: list[dict[str, object]] = []
    holding_rows: list[dict[str, object]] = []
    trade_frames: list[pd.DataFrame] = []
    rebalance_rows: list[dict[str, object]] = []
    target_frames: list[pd.DataFrame] = []

    for trade_date in trading_dates:
        day_trade_frames: list[pd.DataFrame] = []
        scheduled = schedule_by_execution.get(trade_date)
        nav_before_trade = previous_nav

        if scheduled is not None:
            target_frame = scheduled.targets.copy()
            if not target_frame.empty:
                target_frame["execution_date"] = scheduled.execution_date
                target_frame["target_notional"] = (
                    pd.to_numeric(target_frame["target_weight"], errors="coerce").fillna(0.0)
                    * nav_before_trade
                )
                target_frames.append(target_frame.loc[:, TARGET_WEIGHT_COLUMNS])
            else:
                target_frame = pd.DataFrame(columns=TARGET_WEIGHT_COLUMNS)

            positions, ledger, cash = execute_rebalance(
                connection=connection,
                signal_date=scheduled.signal_date,
                execution_date=scheduled.execution_date,
                current_positions=positions,
                target_weights=target_frame,
                cash=cash,
                nav_before_trade=nav_before_trade,
                cost_config=cost_config,
                trading_rules=trading_rules,
                data_source=data_source,
            )
            day_trade_frames.append(ledger)
            rebalance_rows.append(
                _rebalance_summary_row(
                    signal_date=scheduled.signal_date,
                    execution_date=scheduled.execution_date,
                    targets=scheduled.targets,
                    ledger=ledger,
                    nav_before_trade=nav_before_trade,
                )
            )
        else:
            positions, ledger, cash = force_delist_exits(
                connection=connection,
                execution_date=trade_date,
                current_positions=positions,
                cash=cash,
                data_source=data_source,
            )
            if not ledger.empty:
                day_trade_frames.append(ledger)

        if day_trade_frames:
            day_trades = pd.concat(day_trade_frames, ignore_index=True)
            trade_frames.append(day_trades)
        else:
            day_trades = pd.DataFrame(columns=TRADE_LEDGER_COLUMNS)

        daily_cost = _sum_column(day_trades, "total_cost")
        cumulative_cost += daily_cost
        positions, day_holdings, position_value, price_warnings = _mark_to_market(
            connection=connection,
            trade_date=trade_date,
            positions=positions,
            last_close=last_close,
            data_source=data_source,
        )
        warnings.extend(price_warnings)
        nav = cash + position_value
        gross_return = (nav + daily_cost) / previous_nav - 1.0 if previous_nav else 0.0
        net_return = nav / previous_nav - 1.0 if previous_nav else 0.0
        peak_nav = max(peak_nav, nav)
        drawdown = nav / peak_nav - 1.0 if peak_nav else 0.0

        equity_rows.append(
            {
                "trade_date": trade_date,
                "cash": cash,
                "position_value": position_value,
                "nav": nav,
                "gross_return": gross_return,
                "net_return": net_return,
                "daily_cost": daily_cost,
                "cumulative_cost": cumulative_cost,
                "drawdown": drawdown,
            }
        )
        if day_holdings:
            for row in day_holdings:
                row["weight"] = float(row["market_value"]) / nav if nav else 0.0
                holding_rows.append(row)
        previous_nav = nav

    equity_curve = _ordered_frame(pd.DataFrame(equity_rows), EQUITY_COLUMNS, ["trade_date"])
    trade_ledger = _ordered_frame(
        pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame(),
        TRADE_LEDGER_COLUMNS,
        ["execution_date", "stock_code", "side", "order_status"],
    )
    rebalance_summary = _ordered_frame(
        pd.DataFrame(rebalance_rows),
        REBALANCE_COLUMNS,
        ["signal_date", "execution_date"],
    )
    target_weights = _ordered_frame(
        pd.concat(target_frames, ignore_index=True) if target_frames else pd.DataFrame(),
        TARGET_WEIGHT_COLUMNS,
        ["signal_date", "rank", "stock_code"],
    )
    holdings = _ordered_frame(
        pd.DataFrame(holding_rows),
        HOLDING_COLUMNS,
        ["trade_date", "stock_code"],
    )

    benchmark_returns, benchmark_warnings = calculate_synthetic_benchmarks(
        connection=connection,
        start_date=start,
        end_date=end,
        index_code=index_code,
        signal_dates=[item.signal_date for item in schedules],
        benchmark_config=benchmark_config,
        initial_nav=1.0,
        data_source=data_source,
        require_historical_pit_universe=require_historical_pit_universe,
    )
    warnings.extend(benchmark_warnings)

    metrics = calculate_backtest_metrics(
        equity_curve=equity_curve,
        benchmark_returns=benchmark_returns,
        rebalance_summary=rebalance_summary,
        trade_ledger=trade_ledger,
        initial_cash=initial_cash,
    )
    assumptions = _assumptions(
        start=start,
        end=end,
        source_run_id=source_run_id,
        sort_factor=sort_factor,
        index_code=index_code,
        top_n=top_n,
        initial_cash=initial_cash,
        config=config,
        data_source=data_source,
    )
    return BacktestResult(
        equity_curve=equity_curve,
        benchmark_returns=benchmark_returns,
        rebalance_summary=rebalance_summary,
        target_weights=target_weights,
        holdings=holdings,
        trade_ledger=trade_ledger,
        metrics=metrics,
        assumptions=assumptions,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _build_rebalance_schedule(
    *,
    connection: duckdb.DuckDBPyConnection,
    start: date,
    end: date,
    source_run_id: str,
    sort_factor: str,
    index_code: str,
    top_n: int,
    data_dictionary: Mapping[str, object],
    data_source: str | None,
    require_historical_pit_universe: bool,
    warnings: list[str],
) -> list[_ScheduledRebalance]:
    schedules: list[_ScheduledRebalance] = []
    for signal_date in get_month_end_signal_dates(connection, start, end, data_source=data_source):
        execution_date = next_open_trading_date(connection, signal_date, data_source=data_source)
        if execution_date is None:
            warnings.append(
                f"Signal date {signal_date.isoformat()} skipped: execution_date does not exist."
            )
            continue
        if execution_date > end:
            warnings.append(
                f"Signal date {signal_date.isoformat()} skipped: execution_date "
                f"{execution_date.isoformat()} is after end_date {end.isoformat()}."
            )
            continue
        if not has_signal_rows(connection, signal_date, source_run_id):
            warnings.append(
                f"Signal date {signal_date.isoformat()} skipped: no factor_values rows for "
                f"source_run_id {source_run_id}."
            )
            continue
        targets = build_topn_targets(
            connection=connection,
            signal_date=signal_date,
            source_run_id=source_run_id,
            sort_factor=sort_factor,
            index_code=index_code,
            top_n=top_n,
            data_dictionary=data_dictionary,
            data_source=data_source,
            require_universe_snapshot=require_historical_pit_universe,
            require_historical_pit_universe=require_historical_pit_universe,
        )
        schedules.append(
            _ScheduledRebalance(
                signal_date=signal_date,
                execution_date=execution_date,
                targets=targets,
            )
        )
    return schedules


def _rebalance_summary_row(
    *,
    signal_date: date,
    execution_date: date,
    targets: pd.DataFrame,
    ledger: pd.DataFrame,
    nav_before_trade: float,
) -> dict[str, object]:
    executed = ledger["order_status"].eq("executed") if not ledger.empty else pd.Series(dtype=bool)
    forced = (
        ledger["order_status"].eq("forced_delist_exit") if not ledger.empty else pd.Series(dtype=bool)
    )
    rejected = ledger["order_status"].eq("rejected") if not ledger.empty else pd.Series(dtype=bool)
    buy_mask = ledger["side"].eq("buy") if not ledger.empty else pd.Series(dtype=bool)
    sell_mask = ledger["side"].eq("sell") if not ledger.empty else pd.Series(dtype=bool)
    buy_notional = _sum_column(ledger[executed & buy_mask], "executed_notional") if not ledger.empty else 0.0
    sell_notional = _sum_column(ledger[executed & sell_mask], "executed_notional") if not ledger.empty else 0.0
    gross_turnover = (buy_notional + sell_notional) / nav_before_trade if nav_before_trade else 0.0
    return {
        "signal_date": signal_date,
        "execution_date": execution_date,
        "selected_count": int(len(targets)),
        "target_count": int(len(targets)),
        "nav_before_trade": float(nav_before_trade),
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "gross_turnover": gross_turnover,
        "one_way_turnover": gross_turnover / 2.0,
        "commission": _sum_column(ledger, "commission"),
        "stamp_tax": _sum_column(ledger, "stamp_tax"),
        "slippage_cost": _sum_column(ledger, "slippage_cost"),
        "total_cost": _sum_column(ledger, "total_cost"),
        "executed_order_count": int(executed.sum()) if not ledger.empty else 0,
        "rejected_order_count": int(rejected.sum()) if not ledger.empty else 0,
        "forced_delist_exit_count": int(forced.sum()) if not ledger.empty else 0,
        "warning_count": 0,
    }


def _mark_to_market(
    *,
    connection: duckdb.DuckDBPyConnection,
    trade_date: date,
    positions: pd.DataFrame,
    last_close: dict[str, float],
    data_source: str | None,
) -> tuple[pd.DataFrame, list[dict[str, object]], float, list[str]]:
    if positions.empty:
        return positions, [], 0.0, []

    prices = _close_prices(connection, trade_date, data_source=data_source)
    holding_rows: list[dict[str, object]] = []
    warnings: list[str] = []
    updated = positions.copy()
    position_value = 0.0
    for row in positions.itertuples(index=False):
        stock_code = str(row.stock_code)
        shares = float(row.shares)
        close = prices.get(stock_code)
        price_source = "daily_close"
        if close is None:
            close = last_close.get(stock_code)
            price_source = "last_visible_close"
            warnings.append(
                f"Holding {stock_code} on {trade_date.isoformat()} missing close; "
                "used last visible close."
            )
        if close is None:
            close = 0.0
        else:
            last_close[stock_code] = float(close)
        market_value = shares * float(close)
        position_value += market_value
        updated.loc[updated["stock_code"].eq(stock_code), "last_close"] = float(close)
        holding_rows.append(
            {
                "trade_date": trade_date,
                "stock_code": stock_code,
                "shares": shares,
                "close": float(close),
                "market_value": market_value,
                "weight": 0.0,
                "price_source": price_source,
            }
        )
    return updated, holding_rows, float(position_value), warnings


def _close_prices(
    connection: duckdb.DuckDBPyConnection,
    trade_date: date,
    data_source: str | None,
) -> dict[str, float]:
    sql = """
        SELECT stock_code, close
        FROM daily_prices
        WHERE trade_date = ?
    """
    params: list[object] = [trade_date]
    if data_source is not None:
        sql += " AND source = ?"
        params.append(data_source)
    sql += " ORDER BY stock_code"
    frame = connection.execute(sql, params).df()
    result: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        if pd.notna(row.close) and float(row.close) > 0:
            result[str(row.stock_code)] = float(row.close)
    return result


def _assumptions(
    *,
    start: date,
    end: date,
    source_run_id: str,
    sort_factor: str,
    index_code: str,
    top_n: int,
    initial_cash: float,
    config: Mapping[str, object],
    data_source: str | None,
) -> pd.DataFrame:
    costs = _section(config, "costs")
    trading_rules = _section(config, "trading_rules")
    rows = {
        "benchmark_primary": "synthetic_cap_weight",
        "benchmark_secondary": "synthetic_equal_weight",
        "block_sell_if_limit_down": trading_rules.get("block_sell_if_limit_down", True),
        "commission_bps": costs.get("commission_bps", 2.5),
        "delist_exit_value_ratio": trading_rules.get("delist_exit_value_ratio", 0.0),
        "end_date": end.isoformat(),
        "execution": "T+1 open",
        "index_code": index_code,
        "initial_cash": initial_cash,
        "min_commission_yuan": costs.get("min_commission_yuan", 5.0),
        "portfolio": "topn_equal_weight",
        "rebalance_frequency": "monthly",
        "research_only": "true",
        "skip_buy_if_limit_up": trading_rules.get("skip_buy_if_limit_up", True),
        "slippage_bps": costs.get("slippage_bps", 5.0),
        "sort_factor": sort_factor,
        "source_run_id": source_run_id,
        "data_source": data_source,
        "stamp_tax_bps": costs.get("stamp_tax_bps", 10.0),
        "start_date": start.isoformat(),
        "top_n": top_n,
    }
    frame = pd.DataFrame([{"key": key, "value": value} for key, value in rows.items()])
    return frame.sort_values("key", kind="mergesort").reset_index(drop=True)


def _section(config: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def _ordered_frame(frame: pd.DataFrame, columns: list[str], sort_columns: list[str]) -> pd.DataFrame:
    result = frame.copy() if not frame.empty else pd.DataFrame(columns=columns)
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, columns]
    if not result.empty:
        result = result.sort_values(sort_columns, kind="mergesort")
    return result.reset_index(drop=True)


def _sum_column(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum())
