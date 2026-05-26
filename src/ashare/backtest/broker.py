"""Simple amount-book broker for Phase 1b portfolio backtests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from math import floor

import duckdb
import pandas as pd

from ashare.backtest.costs import calculate_trade_costs
from ashare.pit.asof import DateLike, parse_as_of_date, query_securities_as_of


TRADE_LEDGER_COLUMNS = [
    "execution_date",
    "signal_date",
    "stock_code",
    "side",
    "order_status",
    "reject_reason",
    "intended_notional",
    "executed_notional",
    "executed_price",
    "shares_delta",
    "commission",
    "stamp_tax",
    "slippage_cost",
    "total_cost",
    "cash_after",
]
POSITION_COLUMNS = ["stock_code", "shares", "last_close"]


def execute_rebalance(
    connection: duckdb.DuckDBPyConnection,
    signal_date: DateLike,
    execution_date: DateLike,
    current_positions: pd.DataFrame,
    target_weights: pd.DataFrame,
    cash: float,
    nav_before_trade: float,
    cost_config: Mapping[str, object],
    trading_rules: Mapping[str, object],
    data_source: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Execute one rebalance at the T+1 open, selling before buying."""
    parsed_signal_date = parse_as_of_date(signal_date)
    parsed_execution_date = parse_as_of_date(execution_date)
    positions = _normalize_positions(current_positions)
    target_map = _target_notional_map(target_weights, nav_before_trade)
    prices = _execution_prices(connection, parsed_execution_date, data_source=data_source)
    delisted = _delisted_status(connection, parsed_execution_date, data_source=data_source)

    slippage_bps = _float(cost_config, "slippage_bps", 5.0)
    tolerance = _float(trading_rules, "price_compare_tolerance", 0.000001)
    ledger_rows: list[dict[str, object]] = []
    cash_after = float(cash)

    positions, forced_rows, cash_after = _force_delist_exits(
        positions=positions,
        signal_date=parsed_signal_date,
        execution_date=parsed_execution_date,
        cash=cash_after,
        delisted=delisted,
    )
    ledger_rows.extend(forced_rows)

    current_codes = set(positions["stock_code"].tolist())
    target_codes = set(target_map)
    all_codes = sorted(current_codes | target_codes)

    sell_orders: list[tuple[str, float]] = []
    buy_orders: list[tuple[str, float]] = []
    for stock_code in all_codes:
        current_value = _current_raw_notional(positions, prices, stock_code)
        target_value = float(target_map.get(stock_code, 0.0))
        delta = target_value - current_value
        if delta < -1e-8:
            sell_orders.append((stock_code, abs(delta)))
        elif delta > 1e-8:
            buy_orders.append((stock_code, delta))

    for stock_code, intended_notional in sell_orders:
        row = _execute_order(
            stock_code=stock_code,
            side="sell",
            intended_notional=intended_notional,
            positions=positions,
            prices=prices,
            delisted=delisted,
            cash=cash_after,
            signal_date=parsed_signal_date,
            execution_date=parsed_execution_date,
            cost_config=cost_config,
            slippage_bps=slippage_bps,
            tolerance=tolerance,
            trading_rules=trading_rules,
        )
        positions = row.pop("_positions")
        cash_after = float(row["cash_after"])
        ledger_rows.append(row)

    for stock_code, intended_notional in buy_orders:
        row = _execute_order(
            stock_code=stock_code,
            side="buy",
            intended_notional=intended_notional,
            positions=positions,
            prices=prices,
            delisted=delisted,
            cash=cash_after,
            signal_date=parsed_signal_date,
            execution_date=parsed_execution_date,
            cost_config=cost_config,
            slippage_bps=slippage_bps,
            tolerance=tolerance,
            trading_rules=trading_rules,
        )
        positions = row.pop("_positions")
        cash_after = float(row["cash_after"])
        ledger_rows.append(row)

    ledger = pd.DataFrame(ledger_rows, columns=[*TRADE_LEDGER_COLUMNS, "_positions"])
    if "_positions" in ledger.columns:
        ledger = ledger.drop(columns=["_positions"])
    if ledger.empty:
        ledger = pd.DataFrame(columns=TRADE_LEDGER_COLUMNS)
    else:
        ledger = ledger.loc[:, TRADE_LEDGER_COLUMNS]

    positions = _normalize_positions(positions)
    return positions, ledger, float(cash_after)


def force_delist_exits(
    connection: duckdb.DuckDBPyConnection,
    execution_date: DateLike,
    current_positions: pd.DataFrame,
    cash: float,
    data_source: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Force out positions whose delist state is PIT-visible on a daily mark date."""
    parsed_execution_date = parse_as_of_date(execution_date)
    positions = _normalize_positions(current_positions)
    delisted = _delisted_status(connection, parsed_execution_date, data_source=data_source)
    positions, rows, cash_after = _force_delist_exits(
        positions=positions,
        signal_date=parsed_execution_date,
        execution_date=parsed_execution_date,
        cash=float(cash),
        delisted=delisted,
    )
    ledger = pd.DataFrame(rows, columns=TRADE_LEDGER_COLUMNS)
    return positions, ledger, cash_after


def _execute_order(
    *,
    stock_code: str,
    side: str,
    intended_notional: float,
    positions: pd.DataFrame,
    prices: Mapping[str, Mapping[str, object]],
    delisted: Mapping[str, bool],
    cash: float,
    signal_date: date,
    execution_date: date,
    cost_config: Mapping[str, object],
    slippage_bps: float,
    tolerance: float,
    trading_rules: Mapping[str, object],
) -> dict[str, object]:
    reject_reason = _reject_reason(
        stock_code=stock_code,
        side=side,
        prices=prices,
        delisted=delisted,
        tolerance=tolerance,
        trading_rules=trading_rules,
    )

    price_row = prices.get(stock_code)
    raw_open = _price_value(price_row, "open")
    if reject_reason is not None or raw_open is None:
        return _ledger_row(
            execution_date=execution_date,
            signal_date=signal_date,
            stock_code=stock_code,
            side=side,
            order_status="rejected",
            reject_reason=reject_reason or "missing_or_invalid_open",
            intended_notional=intended_notional,
            executed_notional=0.0,
            executed_price=0.0,
            shares_delta=0.0,
            commission=0.0,
            stamp_tax=0.0,
            slippage_cost=0.0,
            total_cost=0.0,
            cash_after=cash,
            positions=positions,
        )

    if side == "buy":
        executed_price = raw_open * (1.0 + slippage_bps / 10_000.0)
        requested_shares = intended_notional / executed_price
        shares_delta, rounded_reject_reason = _rounded_buy_shares(
            requested_shares=requested_shares,
            executed_price=executed_price,
            cash=cash,
            cost_config=cost_config,
            trading_rules=trading_rules,
        )
        if shares_delta <= 1e-12:
            return _ledger_row(
                execution_date=execution_date,
                signal_date=signal_date,
                stock_code=stock_code,
                side=side,
                order_status="rejected",
                reject_reason=rounded_reject_reason,
                intended_notional=intended_notional,
                executed_notional=0.0,
                executed_price=0.0,
                shares_delta=0.0,
                commission=0.0,
                stamp_tax=0.0,
                slippage_cost=0.0,
                total_cost=0.0,
                cash_after=cash,
                positions=positions,
            )
        executed_notional = shares_delta * executed_price
        base_notional = shares_delta * raw_open
        slippage_cost = max(executed_notional - base_notional, 0.0)
        costs = calculate_trade_costs(
            side="buy",
            notional=executed_notional,
            commission_bps=_float(cost_config, "commission_bps", 2.5),
            stamp_tax_bps=_float(cost_config, "stamp_tax_bps", 10.0),
            min_commission_yuan=_float(cost_config, "min_commission_yuan", 5.0),
        )
        cash_after = cash - executed_notional - costs["total_cost"]
        positions = _add_shares(positions, stock_code, shares_delta)
    else:
        held_shares = _held_shares(positions, stock_code)
        requested_shares = min(held_shares, intended_notional / raw_open)
        requested_shares = _rounded_sell_shares(
            requested_shares=requested_shares,
            held_shares=held_shares,
            trading_rules=trading_rules,
        )
        if requested_shares <= 1e-12:
            return _ledger_row(
                execution_date=execution_date,
                signal_date=signal_date,
                stock_code=stock_code,
                side=side,
                order_status="rejected",
                reject_reason="below_board_lot",
                intended_notional=intended_notional,
                executed_notional=0.0,
                executed_price=0.0,
                shares_delta=0.0,
                commission=0.0,
                stamp_tax=0.0,
                slippage_cost=0.0,
                total_cost=0.0,
                cash_after=cash,
                positions=positions,
            )
        executed_price = raw_open * (1.0 - slippage_bps / 10_000.0)
        shares_delta = -requested_shares
        executed_notional = requested_shares * executed_price
        base_notional = requested_shares * raw_open
        slippage_cost = max(base_notional - executed_notional, 0.0)
        costs = calculate_trade_costs(
            side="sell",
            notional=executed_notional,
            commission_bps=_float(cost_config, "commission_bps", 2.5),
            stamp_tax_bps=_float(cost_config, "stamp_tax_bps", 10.0),
            min_commission_yuan=_float(cost_config, "min_commission_yuan", 5.0),
        )
        cash_after = cash + executed_notional - costs["total_cost"]
        positions = _add_shares(positions, stock_code, shares_delta)

    total_cost = float(costs["total_cost"] + slippage_cost)
    return _ledger_row(
        execution_date=execution_date,
        signal_date=signal_date,
        stock_code=stock_code,
        side=side,
        order_status="executed",
        reject_reason=None,
        intended_notional=intended_notional,
        executed_notional=executed_notional,
        executed_price=executed_price,
        shares_delta=shares_delta,
        commission=costs["commission"],
        stamp_tax=costs["stamp_tax"],
        slippage_cost=slippage_cost,
        total_cost=total_cost,
        cash_after=cash_after,
        positions=positions,
    )


def _reject_reason(
    *,
    stock_code: str,
    side: str,
    prices: Mapping[str, Mapping[str, object]],
    delisted: Mapping[str, bool],
    tolerance: float,
    trading_rules: Mapping[str, object],
) -> str | None:
    if side == "buy" and delisted.get(stock_code, False):
        return "delisted"

    price_row = prices.get(stock_code)
    if price_row is None:
        return "missing_daily_price"
    raw_open = _price_value(price_row, "open")
    if raw_open is None:
        return "missing_or_invalid_open"
    if bool(price_row.get("is_suspended", False)) and bool(
        trading_rules.get("hold_if_suspended", True)
    ):
        return "suspended"

    if side == "buy" and bool(trading_rules.get("skip_buy_if_limit_up", True)):
        limit_up = _price_value(price_row, "limit_up")
        if limit_up is not None and raw_open >= limit_up - tolerance:
            return "limit_up"
    if side == "sell" and bool(trading_rules.get("block_sell_if_limit_down", True)):
        limit_down = _price_value(price_row, "limit_down")
        if limit_down is not None and raw_open <= limit_down + tolerance:
            return "limit_down"
    return None


def _force_delist_exits(
    *,
    positions: pd.DataFrame,
    signal_date: date,
    execution_date: date,
    cash: float,
    delisted: Mapping[str, bool],
) -> tuple[pd.DataFrame, list[dict[str, object]], float]:
    rows: list[dict[str, object]] = []
    result = _normalize_positions(positions)
    for row in list(result.itertuples(index=False)):
        stock_code = str(row.stock_code)
        shares = float(row.shares)
        if shares <= 1e-12 or not delisted.get(stock_code, False):
            continue
        result = _add_shares(result, stock_code, -shares)
        rows.append(
            _ledger_row(
                execution_date=execution_date,
                signal_date=signal_date,
                stock_code=stock_code,
                side="sell",
                order_status="forced_delist_exit",
                reject_reason=None,
                intended_notional=0.0,
                executed_notional=0.0,
                executed_price=0.0,
                shares_delta=-shares,
                commission=0.0,
                stamp_tax=0.0,
                slippage_cost=0.0,
                total_cost=0.0,
                cash_after=cash,
                positions=result,
            )
        )
    return _normalize_positions(result), rows, float(cash)


def _execution_prices(
    connection: duckdb.DuckDBPyConnection,
    execution_date: date,
    data_source: str | None = None,
) -> dict[str, dict[str, object]]:
    sql = """
        SELECT stock_code, open, is_suspended, limit_up, limit_down
        FROM daily_prices
        WHERE trade_date = ?
    """
    params: list[object] = [execution_date]
    if data_source is not None:
        sql += " AND source = ?"
        params.append(data_source)
    sql += " ORDER BY stock_code"
    frame = connection.execute(sql, params).df()
    if frame.empty:
        return {}
    result: dict[str, dict[str, object]] = {}
    for row in frame.itertuples(index=False):
        result[str(row.stock_code)] = {
            "open": row.open,
            "is_suspended": bool(row.is_suspended) if pd.notna(row.is_suspended) else False,
            "limit_up": row.limit_up,
            "limit_down": row.limit_down,
        }
    return result


def _delisted_status(
    connection: duckdb.DuckDBPyConnection,
    execution_date: date,
    data_source: str | None = None,
) -> dict[str, bool]:
    securities = query_securities_as_of(
        connection,
        execution_date,
        include_delisted=True,
        source=data_source,
    )
    if securities.empty or "is_delisted_as_of" not in securities.columns:
        return {}
    return {
        str(row.stock_code): bool(row.is_delisted_as_of)
        for row in securities.itertuples(index=False)
    }


def _target_notional_map(target_weights: pd.DataFrame, nav_before_trade: float) -> dict[str, float]:
    if target_weights.empty:
        return {}
    result: dict[str, float] = {}
    for row in target_weights.itertuples(index=False):
        stock_code = str(getattr(row, "stock_code"))
        if "target_notional" in target_weights.columns and pd.notna(getattr(row, "target_notional")):
            target = float(getattr(row, "target_notional"))
        else:
            target = float(getattr(row, "target_weight")) * float(nav_before_trade)
        result[stock_code] = max(target, 0.0)
    return result


def _normalize_positions(positions: pd.DataFrame) -> pd.DataFrame:
    result = positions.copy() if not positions.empty else pd.DataFrame(columns=POSITION_COLUMNS)
    for column in POSITION_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA if column == "last_close" else 0.0
    result = result.loc[:, POSITION_COLUMNS].copy()
    result["stock_code"] = result["stock_code"].astype(str)
    result["shares"] = pd.to_numeric(result["shares"], errors="coerce").fillna(0.0)
    result["last_close"] = pd.to_numeric(result["last_close"], errors="coerce")
    result = result[result["shares"].abs() > 1e-12]
    return result.sort_values("stock_code", kind="mergesort").reset_index(drop=True)


def _current_raw_notional(
    positions: pd.DataFrame,
    prices: Mapping[str, Mapping[str, object]],
    stock_code: str,
) -> float:
    shares = _held_shares(positions, stock_code)
    if shares <= 0:
        return 0.0
    raw_open = _price_value(prices.get(stock_code), "open")
    if raw_open is not None:
        return shares * raw_open
    row = positions[positions["stock_code"].eq(stock_code)]
    if row.empty:
        return 0.0
    last_close = row.iloc[0].get("last_close")
    if pd.notna(last_close) and float(last_close) > 0:
        return shares * float(last_close)
    return 0.0


def _held_shares(positions: pd.DataFrame, stock_code: str) -> float:
    row = positions[positions["stock_code"].eq(stock_code)]
    if row.empty:
        return 0.0
    return float(row.iloc[0]["shares"])


def _add_shares(positions: pd.DataFrame, stock_code: str, shares_delta: float) -> pd.DataFrame:
    result = _normalize_positions(positions)
    mask = result["stock_code"].eq(stock_code)
    if mask.any():
        result.loc[mask, "shares"] = result.loc[mask, "shares"].astype(float) + float(shares_delta)
    else:
        result = pd.concat(
            [
                result,
                pd.DataFrame(
                    [{"stock_code": stock_code, "shares": float(shares_delta), "last_close": pd.NA}]
                ),
            ],
            ignore_index=True,
        )
    return _normalize_positions(result)


def _rounded_buy_shares(
    *,
    requested_shares: float,
    executed_price: float,
    cash: float,
    cost_config: Mapping[str, object],
    trading_rules: Mapping[str, object],
) -> tuple[float, str | None]:
    lot_size = _lot_size(trading_rules)
    shares = _round_down_to_lot(requested_shares, lot_size)
    if shares <= 1e-12:
        return 0.0, "below_board_lot" if requested_shares > 0 else "insufficient_cash"
    while shares > 1e-12:
        executed_notional = shares * executed_price
        costs = calculate_trade_costs(
            side="buy",
            notional=executed_notional,
            commission_bps=_float(cost_config, "commission_bps", 2.5),
            stamp_tax_bps=_float(cost_config, "stamp_tax_bps", 10.0),
            min_commission_yuan=_float(cost_config, "min_commission_yuan", 5.0),
        )
        if executed_notional + costs["total_cost"] <= cash + 1e-6:
            return float(shares), None
        shares -= lot_size
    return 0.0, "insufficient_cash"


def _rounded_sell_shares(
    *,
    requested_shares: float,
    held_shares: float,
    trading_rules: Mapping[str, object],
) -> float:
    if requested_shares >= held_shares - 1e-9:
        return max(held_shares, 0.0)

    lot_size = _lot_size(trading_rules)
    rounded = _round_down_to_lot(requested_shares, lot_size)
    if bool(trading_rules.get("allow_odd_lot_sell", True)):
        residual = held_shares - _round_down_to_lot(held_shares, lot_size)
        if residual > 1e-9 and rounded + residual <= requested_shares + 1e-9:
            rounded += residual
        elif rounded <= 1e-12 and residual <= requested_shares + 1e-9:
            rounded = residual
    return min(rounded, held_shares)


def _round_down_to_lot(shares: float, lot_size: int) -> float:
    if shares <= 0:
        return 0.0
    return float(floor(shares / lot_size) * lot_size)


def _lot_size(trading_rules: Mapping[str, object]) -> int:
    return max(int(trading_rules.get("board_lot_size", 100)), 1)


def _price_value(row: Mapping[str, object] | None, key: str) -> float | None:
    if row is None:
        return None
    value = row.get(key)
    if pd.isna(value):
        return None
    numeric = float(value)
    if key == "open" and numeric <= 0:
        return None
    return numeric


def _ledger_row(
    *,
    execution_date: date,
    signal_date: date,
    stock_code: str,
    side: str,
    order_status: str,
    reject_reason: str | None,
    intended_notional: float,
    executed_notional: float,
    executed_price: float,
    shares_delta: float,
    commission: float,
    stamp_tax: float,
    slippage_cost: float,
    total_cost: float,
    cash_after: float,
    positions: pd.DataFrame,
) -> dict[str, object]:
    return {
        "execution_date": execution_date,
        "signal_date": signal_date,
        "stock_code": stock_code,
        "side": side,
        "order_status": order_status,
        "reject_reason": reject_reason,
        "intended_notional": float(intended_notional),
        "executed_notional": float(executed_notional),
        "executed_price": float(executed_price),
        "shares_delta": float(shares_delta),
        "commission": float(commission),
        "stamp_tax": float(stamp_tax),
        "slippage_cost": float(slippage_cost),
        "total_cost": float(total_cost),
        "cash_after": float(cash_after),
        "_positions": positions,
    }


def _float(mapping: Mapping[str, object], key: str, default: float) -> float:
    value = mapping.get(key, default)
    if value is None:
        return default
    return float(value)
