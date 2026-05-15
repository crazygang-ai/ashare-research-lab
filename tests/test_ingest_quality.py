from datetime import date
from pathlib import Path

import pandas as pd

from ashare.ingest.contracts import FieldValidationIssue
from ashare.ingest.quality import build_data_quality_report, write_data_quality_report


def test_quality_report_writes_markdown_and_csvs(tmp_path: Path) -> None:
    frames = {
        "trading_calendar": pd.DataFrame(
            {"trade_date": [date(2026, 3, 30)], "is_open": [True]}
        ),
        "securities": pd.DataFrame(
            {
                "stock_code": ["000001.SZ"],
                "exchange": ["SZSE"],
                "list_date": [date(2026, 3, 30)],
            }
        ),
        "universe_members": pd.DataFrame(
            {
                "index_code": ["000300.SH"],
                "stock_code": ["000001.SZ"],
                "in_date": [date(2026, 3, 30)],
                "in_effective_date": [date(2026, 3, 30)],
                "source": ["phase1a7"],
            }
        ),
        "daily_prices": pd.DataFrame(
            {"stock_code": ["000001.SZ"], "trade_date": [date(2026, 3, 30)]}
        ),
        "valuation_daily": pd.DataFrame(
            {
                "stock_code": ["000001.SZ"],
                "trade_date": [date(2026, 3, 30)],
                "source": ["phase1a7"],
            }
        ),
    }
    report = build_data_quality_report(
        source="akshare",
        effective_source="csv_fallback",
        source_tag="phase1a7",
        universe="hs300",
        index_code="000300.SH",
        start_date=date(2026, 3, 30),
        end_date=date(2026, 3, 30),
        universe_as_of_date=date(2026, 3, 30),
        frames=frames,
        issues=[
            FieldValidationIssue(
                "daily_prices",
                "warning",
                "missing_adj_factor",
                "daily_prices.adj_factor has missing values.",
                1,
            )
        ],
        cache_events=[
            {
                "dataset": "daily_prices",
                "cache_mode": "use",
                "status": "miss",
                "source": "csv",
                "params_hash": "abc",
                "path": "cache.parquet",
            }
        ],
        warnings=["sample_stock_codes: 000001.SZ"],
        sample_stock_codes=["000001.SZ"],
        universe_members_mode="current_snapshot",
    )

    paths = write_data_quality_report(report, tmp_path)
    text = paths["markdown"].read_text(encoding="utf-8")

    assert {"markdown", "dataset_summary", "field_summary", "issues", "cache_summary"} == set(
        paths
    )
    assert "effective_source: csv_fallback" in text
    assert "source_tag: phase1a7" in text
    assert "sample_stock_codes" in text
    assert "current snapshot" in text
