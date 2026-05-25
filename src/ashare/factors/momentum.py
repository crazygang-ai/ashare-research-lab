"""Price, momentum, risk, and liquidity factor calculations."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import pandas as pd

from ashare.factors.config import factor_params, hard_filter_params


MOMENTUM_FACTORS = {
    "return_20d",
    "return_60d",
    "above_ma60",
    "volatility_20d",
    "max_drawdown_60d",
    "amount_cv_20d",
    "low_liquidity",
}


def calculate_momentum_factors(
    prices: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    factor_names: Sequence[str],
    factor_config: Mapping[str, object],
) -> pd.DataFrame:
    """Calculate price-observation based factors for the requested universe."""
    selected = set(factor_names) & MOMENTUM_FACTORS
    if not selected or prices.empty:
        return _empty()

    frame = prices[prices["stock_code"].isin(stock_codes)].copy()
    if frame.empty:
        return _empty()

    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame = frame.sort_values(["stock_code", "trade_date"], kind="mergesort")
    adj_factor = frame["adj_factor"].where(pd.notna(frame["adj_factor"]), 1.0)
    frame["adjusted_close"] = frame["close"] * adj_factor

    rows: list[dict[str, object]] = []
    for factor_name in ("return_20d", "return_60d"):
        if factor_name not in selected:
            continue
        window = int(factor_params(factor_config, factor_name)["window_days"])
        rows.extend(_return_rows(frame, stock_codes, as_of_date, factor_name, window))

    if "above_ma60" in selected:
        params = factor_params(factor_config, "above_ma60")
        rows.extend(
            _above_ma_rows(
                frame=frame,
                stock_codes=stock_codes,
                as_of_date=as_of_date,
                window=int(params["window_days"]),
            )
        )

    if "volatility_20d" in selected:
        params = factor_params(factor_config, "volatility_20d")
        rows.extend(
            _volatility_rows(
                frame=frame,
                stock_codes=stock_codes,
                as_of_date=as_of_date,
                window=int(params["window_days"]),
            )
        )

    if "max_drawdown_60d" in selected:
        params = factor_params(factor_config, "max_drawdown_60d")
        rows.extend(
            _max_drawdown_rows(
                frame=frame,
                stock_codes=stock_codes,
                as_of_date=as_of_date,
                window=int(params["window_days"]),
            )
        )

    if "amount_cv_20d" in selected:
        params = factor_params(factor_config, "amount_cv_20d")
        rows.extend(
            _amount_cv_rows(
                frame=frame,
                stock_codes=stock_codes,
                as_of_date=as_of_date,
                window=int(params["window_days"]),
            )
        )

    if "low_liquidity" in selected:
        params = hard_filter_params(factor_config, "low_liquidity")
        rows.extend(
            _low_liquidity_rows(
                frame=frame,
                stock_codes=stock_codes,
                as_of_date=as_of_date,
                window=int(params["window_days"]),
                min_avg_amount=float(params["min_avg_amount"]),
            )
        )

    return pd.DataFrame(rows) if rows else _empty()


def _return_rows(
    frame: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    factor_name: str,
    window: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    working = frame.copy()
    working["shifted_close"] = working.groupby("stock_code", sort=False)["adjusted_close"].shift(
        window
    )
    current = working[working["trade_date"] == as_of_date]
    for stock_code in stock_codes:
        stock_current = current[current["stock_code"] == stock_code]
        if stock_current.empty:
            continue
        row = stock_current.iloc[-1]
        shifted = row["shifted_close"]
        adjusted_close = row["adjusted_close"]
        if pd.isna(shifted) or pd.isna(adjusted_close) or shifted == 0:
            continue
        rows.append(_factor_row(stock_code, as_of_date, factor_name, adjusted_close / shifted - 1))
    return rows


def _above_ma_rows(
    frame: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    window: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    working = frame.copy()
    working["ma"] = (
        working.groupby("stock_code", sort=False)["adjusted_close"]
        .rolling(window=window, min_periods=window)
        .mean()
        .reset_index(level=0, drop=True)
    )
    current = working[working["trade_date"] == as_of_date]
    for stock_code in stock_codes:
        stock_current = current[current["stock_code"] == stock_code]
        if stock_current.empty:
            continue
        row = stock_current.iloc[-1]
        if pd.isna(row["ma"]) or pd.isna(row["adjusted_close"]):
            continue
        value = 1.0 if float(row["adjusted_close"]) > float(row["ma"]) else 0.0
        rows.append(_factor_row(stock_code, as_of_date, "above_ma60", value))
    return rows


def _volatility_rows(
    frame: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    window: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for stock_code in stock_codes:
        stock_rows = frame[frame["stock_code"] == stock_code]
        current = stock_rows[stock_rows["trade_date"] == as_of_date]
        if current.empty:
            continue
        latest = stock_rows[stock_rows["trade_date"] <= as_of_date].tail(window + 1)
        if len(latest) < window + 1:
            continue
        returns = latest["adjusted_close"].pct_change().dropna()
        if len(returns) < window or returns.isna().any():
            continue
        rows.append(_factor_row(stock_code, as_of_date, "volatility_20d", returns.std(ddof=0)))
    return rows


def _max_drawdown_rows(
    frame: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    window: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for stock_code in stock_codes:
        stock_rows = frame[frame["stock_code"] == stock_code]
        current = stock_rows[stock_rows["trade_date"] == as_of_date]
        if current.empty:
            continue
        latest = stock_rows[stock_rows["trade_date"] <= as_of_date].tail(window)
        if len(latest) < window or latest["adjusted_close"].isna().any():
            continue
        adjusted_close = latest["adjusted_close"].astype(float)
        if (adjusted_close <= 0).any():
            continue
        drawdowns = 1.0 - adjusted_close / adjusted_close.cummax()
        rows.append(_factor_row(stock_code, as_of_date, "max_drawdown_60d", drawdowns.max()))
    return rows


def _amount_cv_rows(
    frame: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    window: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for stock_code in stock_codes:
        stock_rows = frame[frame["stock_code"] == stock_code]
        current = stock_rows[stock_rows["trade_date"] == as_of_date]
        if current.empty:
            continue
        latest = stock_rows[stock_rows["trade_date"] <= as_of_date].tail(window)
        if len(latest) < window:
            continue
        amount = pd.to_numeric(latest["amount"], errors="coerce").dropna()
        if len(amount) < window:
            continue
        mean_amount = float(amount.mean())
        if mean_amount <= 0:
            continue
        rows.append(
            _factor_row(stock_code, as_of_date, "amount_cv_20d", amount.std(ddof=0) / mean_amount)
        )
    return rows


def _low_liquidity_rows(
    frame: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    window: int,
    min_avg_amount: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    working = frame.copy()
    working["avg_amount"] = (
        working.groupby("stock_code", sort=False)["amount"]
        .rolling(window=window, min_periods=window)
        .mean()
        .reset_index(level=0, drop=True)
    )
    current = working[working["trade_date"] == as_of_date]
    for stock_code in stock_codes:
        stock_current = current[current["stock_code"] == stock_code]
        if stock_current.empty:
            continue
        avg_amount = stock_current.iloc[-1]["avg_amount"]
        if pd.isna(avg_amount):
            continue
        value = 1.0 if float(avg_amount) < min_avg_amount else 0.0
        rows.append(_factor_row(stock_code, as_of_date, "low_liquidity", value))
    return rows


def _factor_row(
    stock_code: str,
    as_of_date: date,
    factor_name: str,
    factor_value: float,
) -> dict[str, object]:
    return {
        "stock_code": stock_code,
        "trade_date": as_of_date,
        "factor_name": factor_name,
        "factor_value": float(factor_value),
        "as_of_date": as_of_date,
    }


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["stock_code", "trade_date", "factor_name", "factor_value", "as_of_date"]
    )
