"""Financial statement factor calculations."""

from __future__ import annotations

from datetime import date
from typing import Sequence

import pandas as pd


FINANCIAL_FACTORS = {"revenue_yoy", "profit_yoy", "operating_cashflow_to_profit"}


def calculate_financial_factors(
    fundamental_reports: pd.DataFrame,
    stock_codes: Sequence[str],
    as_of_date: date,
    factor_names: Sequence[str],
) -> pd.DataFrame:
    """Calculate strict same-period year-over-year financial factors."""
    selected = set(factor_names) & FINANCIAL_FACTORS
    if not selected or fundamental_reports.empty:
        return _empty()

    frame = fundamental_reports[fundamental_reports["stock_code"].isin(stock_codes)].copy()
    if frame.empty:
        return _empty()

    frame["report_period"] = pd.to_datetime(frame["report_period"]).dt.date
    frame["publish_time"] = pd.to_datetime(frame["publish_time"])
    frame = frame.sort_values(
        ["stock_code", "report_period", "publish_time"],
        kind="mergesort",
    )
    latest_revisions = frame.drop_duplicates(["stock_code", "report_period"], keep="last")

    rows: list[dict[str, object]] = []
    for stock_code in stock_codes:
        stock_reports = latest_revisions[latest_revisions["stock_code"] == stock_code]
        if stock_reports.empty:
            continue
        current_period = max(stock_reports["report_period"])
        current = stock_reports[stock_reports["report_period"] == current_period].iloc[-1]
        if "operating_cashflow_to_profit" in selected:
            value = _cashflow_to_profit(current["operating_cashflow"], current["net_profit"])
            if value is not None:
                rows.append(
                    _factor_row(stock_code, as_of_date, "operating_cashflow_to_profit", value)
                )

        if not {"revenue_yoy", "profit_yoy"} & selected:
            continue
        previous_period = _previous_year_same_period(current_period)
        previous = stock_reports[stock_reports["report_period"] == previous_period]
        if previous.empty:
            continue
        previous_row = previous.iloc[-1]

        if "revenue_yoy" in selected:
            value = _yoy(current["revenue"], previous_row["revenue"])
            if value is not None:
                rows.append(_factor_row(stock_code, as_of_date, "revenue_yoy", value))

        if "profit_yoy" in selected:
            value = _yoy(current["net_profit"], previous_row["net_profit"])
            if value is not None:
                rows.append(_factor_row(stock_code, as_of_date, "profit_yoy", value))

    return pd.DataFrame(rows) if rows else _empty()


def _previous_year_same_period(period: date) -> date:
    return date(period.year - 1, period.month, period.day)


def _yoy(current_value: object, previous_value: object) -> float | None:
    if pd.isna(current_value) or pd.isna(previous_value):
        return None
    previous = float(previous_value)
    if previous <= 0:
        return None
    return float(current_value) / previous - 1.0


def _cashflow_to_profit(operating_cashflow: object, net_profit: object) -> float | None:
    if pd.isna(operating_cashflow) or pd.isna(net_profit):
        return None
    profit = float(net_profit)
    if profit <= 0:
        return None
    return float(operating_cashflow) / profit


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
