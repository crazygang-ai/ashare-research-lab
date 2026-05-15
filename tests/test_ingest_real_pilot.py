from collections import Counter
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ashare.fixtures.builder import build_fixtures
from ashare.ingest.csv_fallback import CsvFallbackProvider
from ashare.ingest.providers import ProviderError
from ashare.ingest.real_pilot import ingest_real_pilot
from ashare.pit.asof import load_as_of_snapshot


class FakeProvider:
    name = "akshare"
    provider_version_or_unknown = "fake-akshare"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: Counter[str] = Counter()

    def _called(self, dataset: str) -> None:
        self.calls[dataset] += 1
        if self.fail:
            raise ProviderError("fake provider failure")

    def fetch_trading_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        self._called("trading_calendar")
        return pd.DataFrame(
            {
                "trade_date": [date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1)],
                "is_open": [True, True, True],
            }
        )

    def fetch_index_members(self, index_code: str, as_of_date: date) -> pd.DataFrame:
        self._called("universe_members")
        return pd.DataFrame(
            {
                "index_code": [index_code, index_code, index_code],
                "stock_code": ["000003.SZ", "000001.SZ", "000002.SZ"],
                "stock_name": ["Gamma", "Alpha", "Beta"],
            }
        )

    def fetch_securities(self, stock_codes: list[str], as_of_date: date) -> pd.DataFrame:
        self._called("securities")
        return pd.DataFrame(
            {
                "stock_code": stock_codes,
                "stock_name": [f"Name {code}" for code in stock_codes],
            }
        )

    def fetch_daily_prices(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        self._called("daily_prices")
        rows = []
        for stock_code in stock_codes:
            for trade_date in [date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1)]:
                rows.append(
                    {
                        "stock_code": stock_code,
                        "trade_date": trade_date,
                        "open": 10.0,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10.1,
                        "volume": 1000,
                        "amount": 10100.0,
                    }
                )
        return pd.DataFrame(rows)

    def fetch_valuation_daily(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        self._called("valuation_daily")
        rows = []
        for stock_code in stock_codes:
            for trade_date in [date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1)]:
                rows.append(
                    {
                        "stock_code": stock_code,
                        "trade_date": trade_date,
                        "pe_ttm": 11.0,
                        "pb": 1.2,
                    }
                )
        return pd.DataFrame(rows)


def test_fake_provider_drives_real_pilot_and_source_tag_is_written(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.duckdb"
    result = ingest_real_pilot(
        db_path=db_path,
        provider=FakeProvider(),
        universe="hs300",
        index_code="000300.SH",
        start_date="2026-03-30",
        end_date="2026-04-01",
        universe_as_of_date="2026-03-30",
        cache_dir=tmp_path / "cache",
        max_symbols=2,
        source_tag="phase1a7-test",
        quality_report_dir=tmp_path / "reports",
    )

    connection = duckdb.connect(str(db_path))
    try:
        valuation_sources = {
            row[0]
            for row in connection.execute("SELECT DISTINCT source FROM valuation_daily").fetchall()
        }
        universe_sources = {
            row[0]
            for row in connection.execute("SELECT DISTINCT source FROM universe_members").fetchall()
        }
        factor_rows = connection.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0]
        run_rows = connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0]
    finally:
        connection.close()

    assert result.effective_source == "akshare"
    assert result.row_counts["daily_prices"] == 6
    assert valuation_sources == {"phase1a7-test"}
    assert universe_sources == {"phase1a7-test"}
    assert factor_rows == 0
    assert run_rows == 0


def test_real_pilot_cache_use_hits_on_second_run(tmp_path: Path) -> None:
    first_provider = FakeProvider()
    db_path = tmp_path / "pilot.duckdb"
    kwargs = {
        "db_path": db_path,
        "universe": "hs300",
        "index_code": "000300.SH",
        "start_date": "2026-03-30",
        "end_date": "2026-04-01",
        "universe_as_of_date": "2026-03-30",
        "cache_dir": tmp_path / "cache",
        "source_tag": "phase1a7-cache",
        "quality_report_dir": tmp_path / "reports",
        "overwrite_report": True,
    }
    ingest_real_pilot(provider=first_provider, **kwargs)
    second_provider = FakeProvider()
    result = ingest_real_pilot(provider=second_provider, **kwargs)
    cache_summary = pd.read_csv(result.quality_report_paths["cache_summary"])

    assert sum(first_provider.calls.values()) == 5
    assert sum(second_provider.calls.values()) == 0
    assert set(cache_summary["status"]) == {"hit"}


def test_real_pilot_cache_refresh_calls_provider_again(tmp_path: Path) -> None:
    provider = FakeProvider()
    kwargs = {
        "db_path": tmp_path / "pilot.duckdb",
        "provider": provider,
        "universe": "hs300",
        "index_code": "000300.SH",
        "start_date": "2026-03-30",
        "end_date": "2026-04-01",
        "universe_as_of_date": "2026-03-30",
        "cache_dir": tmp_path / "cache",
        "source_tag": "phase1a7-refresh",
        "quality_report_dir": tmp_path / "reports",
        "overwrite_report": True,
    }
    ingest_real_pilot(**kwargs)
    ingest_real_pilot(cache_mode="refresh", **kwargs)

    assert provider.calls["daily_prices"] == 2


def test_real_pilot_offline_without_cache_fails(tmp_path: Path) -> None:
    with pytest.raises(ProviderError):
        ingest_real_pilot(
            db_path=tmp_path / "pilot.duckdb",
            provider=FakeProvider(),
            universe="hs300",
            index_code="000300.SH",
            start_date="2026-03-30",
            end_date="2026-04-01",
            universe_as_of_date="2026-03-30",
            cache_dir=tmp_path / "cache",
            cache_mode="offline",
            quality_report_dir=tmp_path / "reports",
        )


def test_real_pilot_auto_fallback_uses_csv_fallback(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    build_fixtures(fixture_dir)

    result = ingest_real_pilot(
        db_path=tmp_path / "fallback.duckdb",
        provider=FakeProvider(fail=True),
        universe="hs300",
        index_code="LOCAL_FIXTURE",
        start_date="2026-03-30",
        end_date="2026-05-14",
        universe_as_of_date="2026-03-30",
        cache_dir=tmp_path / "cache",
        fallback_provider=CsvFallbackProvider(fixture_dir),
        allow_fallback=True,
        requested_source="auto",
        source_tag="phase1a7-fallback",
        quality_report_dir=tmp_path / "reports",
    )

    assert result.source == "auto"
    assert result.effective_source == "csv_fallback"
    assert any("CSV fallback" in warning for warning in result.warnings)


def test_current_snapshot_uses_universe_as_of_without_backdating(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.duckdb"
    ingest_real_pilot(
        db_path=db_path,
        provider=FakeProvider(),
        universe="hs300",
        index_code="000300.SH",
        start_date="2026-03-30",
        end_date="2026-04-01",
        universe_as_of_date="2026-03-31",
        cache_dir=tmp_path / "cache",
        max_symbols=1,
        source_tag="phase1a7-snapshot",
        quality_report_dir=tmp_path / "reports",
    )
    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute(
            """
            SELECT in_date, in_effective_date
            FROM universe_members
            WHERE source = 'phase1a7-snapshot'
            """
        ).fetchone()
    finally:
        connection.close()

    assert row == (date(2026, 3, 31), date(2026, 3, 31))


def test_bounded_replace_is_idempotent_and_asof_reads_new_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.duckdb"
    kwargs = {
        "db_path": db_path,
        "provider": FakeProvider(),
        "universe": "hs300",
        "index_code": "000300.SH",
        "start_date": "2026-03-30",
        "end_date": "2026-04-01",
        "universe_as_of_date": "2026-03-30",
        "cache_dir": tmp_path / "cache",
        "max_symbols": 2,
        "source_tag": "phase1a7-idempotent",
        "quality_report_dir": tmp_path / "reports",
        "overwrite_report": True,
    }
    first = ingest_real_pilot(**kwargs)
    second = ingest_real_pilot(**kwargs)
    snapshot = load_as_of_snapshot(db_path, "2026-04-01", index_code="000300.SH")

    assert first.row_counts == second.row_counts
    assert len(snapshot.daily_prices) == 6
    assert len(snapshot.valuation_daily) == 6
    assert len(snapshot.universe_members) == 2


def test_overlapping_different_source_tag_fails_fast(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.duckdb"
    common = {
        "db_path": db_path,
        "provider": FakeProvider(),
        "universe": "hs300",
        "index_code": "000300.SH",
        "start_date": "2026-03-30",
        "end_date": "2026-04-01",
        "universe_as_of_date": "2026-03-30",
        "cache_dir": tmp_path / "cache",
        "max_symbols": 2,
        "quality_report_dir": tmp_path / "reports",
        "overwrite_report": True,
    }
    ingest_real_pilot(source_tag="source-a", **common)

    with pytest.raises(ValueError, match="different source tags"):
        ingest_real_pilot(source_tag="source-b", **common)
