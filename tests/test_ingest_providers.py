import csv
from datetime import date
from pathlib import Path
import sys
import types

import pandas as pd
import pytest

from ashare.fixtures.builder import build_fixtures
from ashare.ingest.akshare_provider import AkShareProvider
from ashare.ingest.contracts import normalize_dataset
from ashare.ingest.csv_fallback import CsvFallbackProvider


def _add_csv_column(path: Path, column: str, value: str) -> None:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = [*(reader.fieldnames or []), column]
        rows = [dict(row, **{column: value}) for row in reader]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _drop_csv_column(path: Path, column: str) -> None:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = [field for field in reader.fieldnames or [] if field != column]
        rows = [{field: row[field] for field in fieldnames} for row in reader]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_csv_provider_reads_target_files_and_ignores_extra_files(tmp_path: Path) -> None:
    build_fixtures(tmp_path)
    (tmp_path / "announcements.csv").write_text("broken", encoding="utf-8")

    provider = CsvFallbackProvider(tmp_path)
    frame = provider.fetch_daily_prices(
        ["000001.SZ"],
        date(2026, 3, 30),
        date(2026, 3, 31),
    )

    assert not frame.empty
    assert set(frame["stock_code"]) == {"000001.SZ"}


def test_csv_provider_missing_required_target_file_fails(tmp_path: Path) -> None:
    build_fixtures(tmp_path)
    (tmp_path / "valuation_daily.csv").unlink()

    with pytest.raises(FileNotFoundError):
        CsvFallbackProvider(tmp_path)


def test_csv_provider_extra_contract_columns_are_ignored_after_normalization(
    tmp_path: Path,
) -> None:
    build_fixtures(tmp_path)
    _add_csv_column(tmp_path / "daily_prices.csv", "extra_vendor_field", "ignored")
    provider = CsvFallbackProvider(tmp_path)

    raw = provider.fetch_daily_prices(
        ["000001.SZ"],
        date(2026, 3, 30),
        date(2026, 3, 31),
    )
    normalized = normalize_dataset("daily_prices", raw)

    assert "extra_vendor_field" not in normalized.columns


def test_csv_provider_backfills_universe_effective_dates(tmp_path: Path) -> None:
    build_fixtures(tmp_path)
    _drop_csv_column(tmp_path / "universe_members.csv", "in_effective_date")
    provider = CsvFallbackProvider(tmp_path)

    frame = provider.fetch_index_members("LOCAL_FIXTURE", date(2026, 3, 30))

    assert "in_effective_date" in frame.columns
    assert frame["in_effective_date"].notna().all()


def test_akshare_provider_uses_mocked_apis_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"
    fake.tool_trade_date_hist_sina = lambda: pd.DataFrame({"trade_date": ["2026-03-30"]})
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame(
        {"成分券代码": ["000001"], "成分券名称": ["平安银行"]}
    )
    fake.stock_info_a_code_name = lambda: pd.DataFrame({"code": ["000001"], "name": ["平安银行"]})
    fake.stock_zh_a_hist = lambda **kwargs: pd.DataFrame(
        {
            "日期": ["2026-03-30"],
            "开盘": [10.0],
            "最高": [10.5],
            "最低": [9.9],
            "收盘": [10.1],
            "成交量": [1000],
            "成交额": [10100.0],
        }
    )
    fake.stock_a_lg_indicator = lambda symbol: pd.DataFrame(
        {"日期": ["2026-03-30"], "市盈率TTM": [11.0], "市净率": [1.2]}
    )
    monkeypatch.setitem(sys.modules, "akshare", fake)

    provider = AkShareProvider()
    members = normalize_dataset(
        "universe_members",
        provider.fetch_index_members("000300.SH", date(2026, 3, 30)),
    )
    prices = normalize_dataset(
        "daily_prices",
        provider.fetch_daily_prices(["000001.SZ"], date(2026, 3, 30), date(2026, 3, 30)),
    )

    assert provider.provider_version_or_unknown == "akshare-test"
    assert members.loc[0, "stock_code"] == "000001.SZ"
    assert prices.loc[0, "close"] == 10.1
