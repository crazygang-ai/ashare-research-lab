"""Build small deterministic CSV fixtures for local development tests."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


FIXTURE_SOURCE = "fixture"
INDEX_CODE = "LOCAL_FIXTURE"
MAIN_SAMPLE_DAYS = 60
BUFFER_DAYS = 3
TOTAL_CALENDAR_DAYS = MAIN_SAMPLE_DAYS + BUFFER_DAYS

CSV_FILES = (
    "trading_calendar.csv",
    "securities.csv",
    "industry_classifications.csv",
    "universe_members.csv",
    "daily_prices.csv",
    "st_status.csv",
    "fundamental_reports.csv",
    "valuation_daily.csv",
    "announcements.csv",
    "risk_events.csv",
)

STOCKS = (
    {
        "stock_code": "000001.SZ",
        "stock_name": "Normal Alpha",
        "exchange": "SZSE",
        "list_date": date(2020, 1, 1),
        "delist_date": None,
        "industry_l1": "Financials",
        "industry_l2": "Banking",
    },
    {
        "stock_code": "000002.SZ",
        "stock_name": "ST Boundary",
        "exchange": "SZSE",
        "list_date": date(2020, 1, 1),
        "delist_date": None,
        "industry_l1": "Industrials",
        "industry_l2": "Construction",
    },
    {
        "stock_code": "000003.SZ",
        "stock_name": "Delist Sample",
        "exchange": "SZSE",
        "list_date": date(2020, 1, 1),
        "delist_date": None,
        "industry_l1": "Consumer",
        "industry_l2": "Retail",
    },
    {
        "stock_code": "000004.SZ",
        "stock_name": "Suspension Sample",
        "exchange": "SZSE",
        "list_date": date(2020, 1, 1),
        "delist_date": None,
        "industry_l1": "Health Care",
        "industry_l2": "Pharma",
    },
    {
        "stock_code": "000005.SZ",
        "stock_name": "Limit Edge",
        "exchange": "SZSE",
        "list_date": date(2020, 1, 1),
        "delist_date": None,
        "industry_l1": "Technology",
        "industry_l2": "Software",
    },
)


def build_fixtures(output_dir: Path) -> None:
    """Build deterministic local CSV fixtures under ``output_dir``."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trading_days = _trading_days(TOTAL_CALENDAR_DAYS)
    main_days = trading_days[:MAIN_SAMPLE_DAYS]
    stocks = _stocks_with_delist(main_days)

    _write_csv(output_dir / "trading_calendar.csv", _trading_calendar_rows(trading_days))
    _write_csv(output_dir / "securities.csv", _securities_rows(stocks))
    _write_csv(output_dir / "industry_classifications.csv", _industry_rows(stocks, main_days))
    _write_csv(output_dir / "universe_members.csv", _universe_rows(stocks, main_days))
    _write_csv(output_dir / "daily_prices.csv", _daily_price_rows(stocks, main_days))
    _write_csv(output_dir / "st_status.csv", _st_status_rows(main_days))
    _write_csv(output_dir / "fundamental_reports.csv", _fundamental_rows(stocks, main_days))
    _write_csv(output_dir / "valuation_daily.csv", _valuation_rows(stocks, main_days))
    _write_csv(output_dir / "announcements.csv", _announcement_rows(main_days))
    _write_csv(output_dir / "risk_events.csv", _risk_event_rows(main_days))


def _trading_days(count: int) -> list[date]:
    days: list[date] = []
    current = date(2026, 1, 5)
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _stocks_with_delist(main_days: list[date]) -> list[dict[str, Any]]:
    stocks = [dict(stock) for stock in STOCKS]
    stocks[2]["delist_date"] = main_days[44]
    return stocks


def _trading_calendar_rows(trading_days: list[date]) -> list[dict[str, Any]]:
    rows = []
    for index, trade_date in enumerate(trading_days):
        rows.append(
            {
                "trade_date": trade_date,
                "is_open": True,
                "prev_trade_date": trading_days[index - 1] if index > 0 else None,
                "next_trade_date": trading_days[index + 1]
                if index + 1 < len(trading_days)
                else None,
            }
        )
    return rows


def _securities_rows(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock["stock_code"],
            "stock_name": stock["stock_name"],
            "exchange": stock["exchange"],
            "list_date": stock["list_date"],
            "delist_date": stock["delist_date"],
        }
        for stock in stocks
    ]


def _industry_rows(stocks: list[dict[str, Any]], main_days: list[date]) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock["stock_code"],
            "industry_standard": "fixture_l1_l2",
            "industry_l1": stock["industry_l1"],
            "industry_l2": stock["industry_l2"],
            "in_date": main_days[0],
            "out_date": None,
            "version": "2026Q1",
            "source": FIXTURE_SOURCE,
        }
        for stock in stocks
    ]


def _universe_rows(stocks: list[dict[str, Any]], main_days: list[date]) -> list[dict[str, Any]]:
    return [
        {
            "index_code": INDEX_CODE,
            "stock_code": stock["stock_code"],
            "in_date": main_days[0],
            "out_date": stock["delist_date"],
            "source": FIXTURE_SOURCE,
        }
        for stock in stocks
    ]


def _daily_price_rows(stocks: list[dict[str, Any]], main_days: list[date]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stock_index, stock in enumerate(stocks, start=1):
        previous_close = round(8.0 + stock_index * 3.0, 2)
        for day_index, trade_date in enumerate(main_days):
            limit_up = round(previous_close * 1.10, 2)
            limit_down = round(previous_close * 0.90, 2)
            is_suspended = stock["stock_code"] == "000004.SZ" and day_index == 15

            if is_suspended:
                open_price = high = low = close = previous_close
                volume = 0
                amount = 0.0
            elif stock["stock_code"] == "000005.SZ" and day_index == 20:
                open_price = previous_close
                high = close = limit_up
                low = round(previous_close * 0.99, 2)
                volume = 180_000 + day_index * 1_000
                amount = round(volume * close, 2)
            elif stock["stock_code"] == "000005.SZ" and day_index == 21:
                open_price = previous_close
                low = close = limit_down
                high = round(previous_close * 1.01, 2)
                volume = 181_000 + day_index * 1_000
                amount = round(volume * close, 2)
            else:
                close = round(previous_close + 0.03 + stock_index * 0.01, 2)
                open_price = round(previous_close + 0.01, 2)
                high = round(max(open_price, close) + 0.05, 2)
                low = round(min(open_price, close) - 0.05, 2)
                volume = 100_000 + stock_index * 10_000 + day_index * 1_000
                amount = round(volume * close, 2)

            rows.append(
                {
                    "stock_code": stock["stock_code"],
                    "trade_date": trade_date,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "adj_factor": 1.0,
                    "is_suspended": is_suspended,
                    "limit_up": limit_up,
                    "limit_down": limit_down,
                }
            )
            previous_close = close
    return rows


def _st_status_rows(main_days: list[date]) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": "000002.SZ",
            "st_type": "ST",
            "in_date": main_days[12],
            "out_date": main_days[32],
            "source": FIXTURE_SOURCE,
        }
    ]


def _fundamental_rows(stocks: list[dict[str, Any]], main_days: list[date]) -> list[dict[str, Any]]:
    publish_days = [0, 4, 19, 29, 39]
    rows: list[dict[str, Any]] = []
    for index, stock in enumerate(stocks):
        rows.append(
            {
                "stock_code": stock["stock_code"],
                "report_period": date(2025, 12, 31),
                "publish_time": _published_at(main_days[publish_days[index]]),
                "revenue": 1000.0 + index * 100.0,
                "net_profit": 120.0 + index * 12.0,
                "roe": 0.08 + index * 0.01,
                "gross_margin": 0.30 + index * 0.02,
                "operating_cashflow": 95.0 + index * 10.0,
                "debt_ratio": 0.35 + index * 0.03,
                "goodwill": 10.0 + index,
                "total_equity": 800.0 + index * 80.0,
                "accounts_receivable": 60.0 + index * 5.0,
                "inventory": 70.0 + index * 6.0,
                "source": FIXTURE_SOURCE,
            }
        )
    return rows


def _valuation_rows(stocks: list[dict[str, Any]], main_days: list[date]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stock_index, stock in enumerate(stocks, start=1):
        for day_index, trade_date in enumerate(main_days):
            rows.append(
                {
                    "stock_code": stock["stock_code"],
                    "trade_date": trade_date,
                    "pe_ttm": round(10.0 + stock_index + day_index * 0.01, 4),
                    "pb": round(1.0 + stock_index * 0.1, 4),
                    "ps": round(2.0 + stock_index * 0.2, 4),
                    "dividend_yield": round(0.01 + stock_index * 0.001, 4),
                    "total_mv": 10_000.0 + stock_index * 1_000.0 + day_index * 10.0,
                    "float_mv": 8_000.0 + stock_index * 800.0 + day_index * 8.0,
                    "source": FIXTURE_SOURCE,
                }
            )
    return rows


def _announcement_rows(main_days: list[date]) -> list[dict[str, Any]]:
    return [
        {
            "announcement_id": "ann-000001-forecast",
            "stock_code": "000001.SZ",
            "title": "2025 earnings forecast",
            "announcement_type": "earnings_forecast",
            "publish_time": _published_at(main_days[0]),
            "url": "https://example.invalid/ann-000001-forecast",
            "raw_path": "raw/ann-000001-forecast.txt",
            "text_hash": "hash-ann-000001-forecast",
        },
        {
            "announcement_id": "ann-000002-buyback",
            "stock_code": "000002.SZ",
            "title": "Share buyback plan",
            "announcement_type": "buyback",
            "publish_time": _published_at(main_days[4]),
            "url": "https://example.invalid/ann-000002-buyback",
            "raw_path": "raw/ann-000002-buyback.txt",
            "text_hash": "hash-ann-000002-buyback",
        },
        {
            "announcement_id": "ann-000005-inquiry",
            "stock_code": "000005.SZ",
            "title": "Exchange inquiry letter",
            "announcement_type": "inquiry_letter",
            "publish_time": _published_at(main_days[19]),
            "url": "https://example.invalid/ann-000005-inquiry",
            "raw_path": "raw/ann-000005-inquiry.txt",
            "text_hash": "hash-ann-000005-inquiry",
        },
    ]


def _risk_event_rows(main_days: list[date]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": "risk-000001-pledge",
            "stock_code": "000001.SZ",
            "event_type": "pledge",
            "event_date": main_days[0],
            "publish_time": _published_at(main_days[0]),
            "payload_json": {"pledged_ratio": 0.18, "holder": "controlling_shareholder"},
            "source": FIXTURE_SOURCE,
        },
        {
            "event_id": "risk-000002-reduce",
            "stock_code": "000002.SZ",
            "event_type": "shareholder_reduce",
            "event_date": main_days[4],
            "publish_time": _published_at(main_days[4]),
            "payload_json": {"reduction_ratio": 0.02, "window_days": 90},
            "source": FIXTURE_SOURCE,
        },
        {
            "event_id": "risk-000005-inquiry",
            "stock_code": "000005.SZ",
            "event_type": "inquiry_letter",
            "event_date": main_days[19],
            "publish_time": _published_at(main_days[19]),
            "payload_json": {"topic": "revenue_recognition", "requires_reply": True},
            "source": FIXTURE_SOURCE,
        },
        {
            "event_id": "risk-000003-audit",
            "stock_code": "000003.SZ",
            "event_type": "non_standard_audit",
            "event_date": main_days[29],
            "publish_time": _published_at(main_days[29]),
            "payload_json": {"opinion": "qualified", "audit_year": 2025},
            "source": FIXTURE_SOURCE,
        },
    ]


def _published_at(trade_date: date) -> datetime:
    return datetime.combine(trade_date, time(18, 0))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows generated for {path.name}.")

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)
