"""Markdown and CSV reports for Phase 1b backtests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ashare.backtest.benchmark import BENCHMARK_COLUMNS
from ashare.backtest.broker import TRADE_LEDGER_COLUMNS
from ashare.backtest.engine import (
    ASSUMPTION_COLUMNS,
    EQUITY_COLUMNS,
    HOLDING_COLUMNS,
    REBALANCE_COLUMNS,
    TARGET_WEIGHT_COLUMNS,
    BacktestResult,
)


BACKTEST_REPORT_FILES = {
    "markdown": "backtest_report.md",
    "equity_curve": "equity_curve.csv",
    "benchmark_returns": "benchmark_returns.csv",
    "rebalance_summary": "rebalance_summary.csv",
    "target_weights": "target_weights.csv",
    "holdings": "holdings.csv",
    "trade_ledger": "trade_ledger.csv",
    "metrics": "metrics.csv",
    "assumptions": "assumptions.csv",
}
REQUIRED_METADATA = {
    "generated_at",
    "db_path",
    "start_date",
    "end_date",
    "source_run_id",
    "sort_factor",
    "index_code",
    "top_n",
    "initial_cash",
    "backtest_config_path",
    "data_dictionary_path",
}


def render_backtest_markdown(
    result: BacktestResult,
    metadata: Mapping[str, object],
) -> str:
    """Render a deterministic Markdown backtest report."""
    _require_metadata(metadata, REQUIRED_METADATA, "backtest report")
    metrics = result.metrics.iloc[0].to_dict() if not result.metrics.empty else {}
    assumptions = _assumption_map(result.assumptions)
    warnings = result.warnings
    lines = [
        "# Phase 1b Backtest Report",
        "",
        "## Metadata",
        "",
        f"- generated_at: {_stringify(metadata['generated_at'])}",
        f"- db_path: {_stringify(metadata['db_path'])}",
        f"- backtest interval: {_stringify(metadata['start_date'])} to {_stringify(metadata['end_date'])}",
        f"- source_run_id: {_stringify(metadata['source_run_id'])}",
        f"- index_code: {_stringify(metadata['index_code'])}",
        f"- sort_factor: {_stringify(metadata['sort_factor'])}",
        f"- top_n: {_stringify(metadata['top_n'])}",
        f"- initial_cash: {_stringify(metadata['initial_cash'])}",
        "",
        "## Strategy Rules",
        "",
        "- This backtest is a historical simulation for research replay, not a performance promise.",
        "- Strategy: monthly Top N equal-weight portfolio.",
        "- Signal source: stored `factor_values` rows for the explicit `source_run_id`.",
        "- Signal date: each month-end open trading day in the requested interval.",
        "- T+1 开盘成交: orders execute on the next open trading day after the signal date.",
        "- Ranking: the explicit `sort_factor` direction comes from `configs/data_dictionary.yaml`.",
        "- Hard filters: `is_st`, `is_suspended`, `is_delisted`, and `low_liquidity` must be 0.0; missing hard-filter values are excluded.",
        "",
        "## Trading Costs",
        "",
        f"- commission_bps: {_stringify(assumptions.get('commission_bps'))}",
        f"- stamp_tax_bps: {_stringify(assumptions.get('stamp_tax_bps'))}; sell orders only.",
        f"- slippage_bps: {_stringify(assumptions.get('slippage_bps'))}; applied through execution price.",
        f"- min_commission_yuan: {_stringify(assumptions.get('min_commission_yuan'))}; per order.",
        "- Metrics separately report commission, stamp_tax, slippage_cost, total_cost, gross_return, net_return, and cost_drag.",
        "",
        "## Trading Constraints",
        "",
        "- Signal selection uses hard filters from `factor_values`.",
        "- The matching layer uses `daily_prices.is_suspended`, `daily_prices.limit_up`, `daily_prices.limit_down`, and PIT `securities` delisting state.",
        "- Suspended stocks cannot be bought or sold.",
        "- Limit-up stocks cannot be bought; limit-down stocks cannot be sold.",
        f"- A-share board-lot rule: buy orders are rounded down to `board_lot_size` = {_stringify(assumptions.get('board_lot_size'))} shares.",
        f"- A-share odd-lot sell rule: `allow_odd_lot_sell` = {_stringify(assumptions.get('allow_odd_lot_sell'))}; sells may include one complete odd-lot residual block without splitting it.",
        "- Blocked buy notional remains cash; blocked sells continue to be held.",
        "- Delisted holdings are forced out with `order_status = forced_delist_exit` and default value 0.0.",
        "",
        "## Trading Constraint Diagnostics",
        "",
        _markdown_table(_constraint_summary(result.trade_ledger)),
        "",
        "## Benchmarks",
        "",
        "- Benchmark 1: synthetic market-cap-weighted portfolio over the same PIT universe.",
        "- Benchmark 2: synthetic equal-weight portfolio over the same PIT universe.",
        "- Benchmark constituents are locked at monthly signal dates until the next signal date.",
        "- Market-cap weights prefer `valuation_daily.float_mv` and fall back to `total_mv`.",
        "- Benchmark returns use adjusted_close = close * adj_factor; missing adj_factor falls back to close.",
        "",
        "## Key Metrics",
        "",
        _markdown_table(_metrics_summary(metrics)),
        "",
        "## Cost Impact",
        "",
        f"- gross_return: {_format_number(metrics.get('gross_return'))}",
        f"- net_return: {_format_number(metrics.get('net_return'))}",
        f"- cost_drag: {_format_number(metrics.get('cost_drag'))}",
        f"- total_cost: {_format_number(metrics.get('total_cost'))}",
        "",
        "## Rejections And Forced Delist Exits",
        "",
        f"- rejected_order_count: {_format_number(metrics.get('rejected_order_count'))}",
        f"- forced_delist_exit_count: {_format_number(metrics.get('forced_delist_exit_count'))}",
        "",
        "## Warnings",
        "",
    ]
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "## Scope Notes",
            "",
            "- 本报告不是交易建议。",
            "- backtest report is for research only and is not a trading instruction.",
            "- This historical simulation is not a performance promise.",
            "- 本报告是历史模拟，不是收益或表现承诺。",
            "- 本报告不包含风格归因和行业归因。",
            "- 本 phase 不做复杂风格归因。",
            "- This phase does not model cash dividends, bonus shares, rights issues, partial fills, order-book depth, volume constraints, impact costs, leverage, shorting, or parameter optimization.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_backtest_report(
    result: BacktestResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write backtest Markdown and CSV artifacts."""
    _require_metadata(metadata, REQUIRED_METADATA, "backtest report")
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        key: resolved_output_dir / filename for key, filename in BACKTEST_REPORT_FILES.items()
    }
    _fail_if_exists(paths.values(), overwrite=overwrite)

    _ordered(result.equity_curve, EQUITY_COLUMNS, ["trade_date"]).to_csv(
        paths["equity_curve"],
        index=False,
    )
    _ordered(result.benchmark_returns, BENCHMARK_COLUMNS, ["trade_date"]).to_csv(
        paths["benchmark_returns"],
        index=False,
    )
    _ordered(result.rebalance_summary, REBALANCE_COLUMNS, ["signal_date", "execution_date"]).to_csv(
        paths["rebalance_summary"],
        index=False,
    )
    _ordered(result.target_weights, TARGET_WEIGHT_COLUMNS, ["signal_date", "rank", "stock_code"]).to_csv(
        paths["target_weights"],
        index=False,
    )
    _ordered(result.holdings, HOLDING_COLUMNS, ["trade_date", "stock_code"]).to_csv(
        paths["holdings"],
        index=False,
    )
    _ordered(result.trade_ledger, TRADE_LEDGER_COLUMNS, ["execution_date", "stock_code", "side", "order_status"]).to_csv(
        paths["trade_ledger"],
        index=False,
    )
    result.metrics.to_csv(paths["metrics"], index=False)
    _ordered(result.assumptions, ASSUMPTION_COLUMNS, ["key"]).to_csv(
        paths["assumptions"],
        index=False,
    )
    paths["markdown"].write_text(render_backtest_markdown(result, metadata), encoding="utf-8")
    return paths


def _ordered(frame: pd.DataFrame, columns: list[str], sort_columns: list[str]) -> pd.DataFrame:
    result = frame.copy() if not frame.empty else pd.DataFrame(columns=columns)
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, columns]
    if not result.empty:
        result = result.sort_values(sort_columns, kind="mergesort")
    return result.reset_index(drop=True)


def _metrics_summary(metrics: Mapping[str, object]) -> pd.DataFrame:
    keys = [
        "total_return",
        "annualized_return",
        "volatility",
        "max_drawdown",
        "sharpe",
        "benchmark_cap_weight_return",
        "benchmark_equal_weight_return",
        "excess_return_vs_cap_weight",
        "excess_return_vs_equal_weight",
        "total_cost",
        "rejected_order_count",
        "forced_delist_exit_count",
    ]
    return pd.DataFrame(
        [{"metric": key, "value": _format_number(metrics.get(key))} for key in keys]
    )


def _constraint_summary(trade_ledger: pd.DataFrame) -> pd.DataFrame:
    if trade_ledger.empty:
        return pd.DataFrame(
            [
                {"status": "rejected", "reason": "(none)", "order_count": 0},
                {"status": "forced_delist_exit", "reason": "(none)", "order_count": 0},
            ]
        )
    rejected = trade_ledger[trade_ledger["order_status"].eq("rejected")].copy()
    rows: list[dict[str, object]] = []
    if rejected.empty:
        rows.append({"status": "rejected", "reason": "(none)", "order_count": 0})
    else:
        rejected["reject_reason"] = rejected["reject_reason"].fillna("(missing)")
        counts = (
            rejected.groupby("reject_reason", dropna=False)
            .size()
            .reset_index(name="order_count")
            .sort_values(["reject_reason"], kind="mergesort")
        )
        rows.extend(
            {
                "status": "rejected",
                "reason": str(row.reject_reason),
                "order_count": int(row.order_count),
            }
            for row in counts.itertuples(index=False)
        )
    forced_count = int(trade_ledger["order_status"].eq("forced_delist_exit").sum())
    rows.append(
        {
            "status": "forced_delist_exit",
            "reason": "PIT delisting state",
            "order_count": forced_count,
        }
    )
    return pd.DataFrame(rows)


def _assumption_map(assumptions: pd.DataFrame) -> dict[str, object]:
    if assumptions.empty:
        return {}
    return {
        str(row.key): row.value
        for row in assumptions.loc[:, ["key", "value"]].itertuples(index=False)
    }


def _require_metadata(
    metadata: Mapping[str, object],
    required_keys: set[str],
    context: str,
) -> None:
    missing = sorted(required_keys.difference(metadata.keys()))
    if missing:
        raise ValueError(f"Missing required metadata for {context}: {', '.join(missing)}")


def _fail_if_exists(paths: Sequence[Path], overwrite: bool) -> None:
    if overwrite:
        return
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing report file(s): " + ", ".join(existing)
        )


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = [str(column) for column in frame.columns]
    if not columns:
        return "_No columns._"
    header = "| " + " | ".join(_escape_markdown_cell(column) for column in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| "
        + " | ".join(_escape_markdown_cell(_stringify(value)) for value in row)
        + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    if not rows:
        rows = ["| " + " | ".join("" for _ in columns) + " |"]
    return "\n".join([header, separator, *rows])


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _format_number(value: object) -> str:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _stringify(value)
    return f"{numeric:.6f}"


def _stringify(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
