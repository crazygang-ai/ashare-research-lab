from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
import subprocess

import duckdb
import pandas as pd
import pytest

from ashare.fixtures.builder import INDEX_CODE, build_fixtures
from ashare.ingest.local import ingest_local
from ashare.pit import asof as asof_module
from ashare.pit.asof import (
    AsOfSnapshot,
    build_as_of_snapshot,
    load_as_of_snapshot,
    parse_as_of_date,
    query_announcements_as_of,
    query_daily_prices_as_of,
    query_fundamental_reports_as_of,
    query_industry_classifications_as_of,
    query_risk_events_as_of,
    query_securities_as_of,
    query_st_status_as_of,
    query_universe_members_as_of,
    query_valuation_daily_as_of,
)


@pytest.fixture()
def fixture_db_path(tmp_path: Path) -> Path:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)
    ingest_local(input_dir=input_dir, db_path=db_path)
    return db_path


@pytest.fixture()
def connection(fixture_db_path: Path) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect(str(fixture_db_path), read_only=True)
    try:
        yield db
    finally:
        db.close()


def _date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.date


def _table_count(connection: duckdb.DuckDBPyConnection, table: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _assert_sorted(df: pd.DataFrame, columns: list[str]) -> None:
    expected = df.sort_values(columns, kind="mergesort").reset_index(drop=True)
    pd.testing.assert_frame_equal(df.reset_index(drop=True), expected)


def _drop_csv_columns(path: Path, columns: set[str]) -> None:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = [field for field in reader.fieldnames or [] if field not in columns]
        rows = [{field: row[field] for field in fieldnames} for row in reader]

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_daily_prices_only_include_trade_dates_on_or_before_as_of(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    rows = query_daily_prices_as_of(connection, "2026-01-06")

    assert len(rows) == 10
    assert _date_series(rows["trade_date"]).max() <= date(2026, 1, 6)
    assert rows["stock_code"].nunique() == 5


def test_valuation_daily_only_include_trade_dates_on_or_before_as_of(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    rows = query_valuation_daily_as_of(connection, "2026-01-06", stock_code="000001.SZ")

    assert len(rows) == 2
    assert set(rows["stock_code"]) == {"000001.SZ"}
    assert _date_series(rows["trade_date"]).max() <= date(2026, 1, 6)


def test_fundamental_reports_require_publish_date_and_effective_date(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before = query_fundamental_reports_as_of(connection, "2026-01-05", stock_code="000001.SZ")
    after = query_fundamental_reports_as_of(connection, "2026-01-06", stock_code="000001.SZ")
    before_current = before[before["report_period"] == pd.Timestamp("2025-12-31")]
    after_current = after[after["report_period"] == pd.Timestamp("2025-12-31")]

    assert before_current.empty
    assert len(after_current) == 1
    assert after_current.iloc[0]["publish_time"] == pd.Timestamp("2026-01-05 18:00:00")
    assert after_current.iloc[0]["effective_date"] == pd.Timestamp("2026-01-06")


def test_announcements_require_publish_date_and_effective_date(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before = query_announcements_as_of(
        connection,
        "2026-01-09",
        announcement_type="buyback",
    )
    after = query_announcements_as_of(
        connection,
        "2026-01-12",
        announcement_type="buyback",
    )

    assert before.empty
    assert len(after) == 1
    assert after.iloc[0]["announcement_id"] == "ann-000002-buyback"


def test_risk_events_use_effective_date_not_event_date_only(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before = query_risk_events_as_of(
        connection,
        "2026-01-09",
        event_type="shareholder_reduce",
    )
    after = query_risk_events_as_of(
        connection,
        "2026-01-12",
        event_type="shareholder_reduce",
    )

    assert before.empty
    assert len(after) == 1
    assert after.iloc[0]["event_id"] == "risk-000002-reduce"


def test_universe_members_respect_exit_visibility_and_half_open_dates(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before_exit_visible = query_universe_members_as_of(
        connection,
        "2026-03-02",
        index_code=INDEX_CODE,
        stock_code="000003.SZ",
    )
    on_exit_effective = query_universe_members_as_of(
        connection,
        "2026-03-03",
        index_code=INDEX_CODE,
        stock_code="000003.SZ",
    )
    after_exit_visible_before_out_date = query_universe_members_as_of(
        connection,
        "2026-03-05",
        index_code=INDEX_CODE,
        stock_code="000003.SZ",
    )
    on_out_date = query_universe_members_as_of(
        connection,
        "2026-03-06",
        index_code=INDEX_CODE,
        stock_code="000003.SZ",
    )

    assert len(before_exit_visible) == 1
    assert pd.isna(before_exit_visible.iloc[0]["out_date"])
    assert pd.isna(before_exit_visible.iloc[0]["out_publish_time"])
    assert pd.isna(before_exit_visible.iloc[0]["out_effective_date"])

    assert len(on_exit_effective) == 1
    assert on_exit_effective.iloc[0]["out_date"] == pd.Timestamp("2026-03-06")
    assert on_exit_effective.iloc[0]["out_publish_time"] == pd.Timestamp(
        "2026-03-02 18:00:00"
    )
    assert on_exit_effective.iloc[0]["out_effective_date"] == pd.Timestamp("2026-03-03")

    assert len(after_exit_visible_before_out_date) == 1
    assert after_exit_visible_before_out_date.iloc[0]["out_date"] == pd.Timestamp("2026-03-06")
    assert on_out_date.empty


def test_st_status_respects_entry_exit_visibility_and_half_open_dates(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before = query_st_status_as_of(connection, "2026-01-20")
    start = query_st_status_as_of(connection, "2026-01-21")
    exit_visible_before_out_date = query_st_status_as_of(connection, "2026-02-17")
    out_date = query_st_status_as_of(connection, "2026-02-18")

    assert before.empty
    assert len(start) == 1
    assert start.iloc[0]["stock_code"] == "000002.SZ"
    assert pd.isna(start.iloc[0]["out_date"])

    assert len(exit_visible_before_out_date) == 1
    assert exit_visible_before_out_date.iloc[0]["out_date"] == pd.Timestamp("2026-02-18")
    assert exit_visible_before_out_date.iloc[0]["out_publish_time"] == pd.Timestamp(
        "2026-02-16 18:00:00"
    )
    assert exit_visible_before_out_date.iloc[0]["out_effective_date"] == pd.Timestamp(
        "2026-02-17"
    )
    assert out_date.empty


def test_securities_respect_delist_visibility_and_include_delisted_option(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before_delist_visible = query_securities_as_of(
        connection,
        "2026-03-02",
        include_delisted=True,
        stock_code="000003.SZ",
    )
    on_delist_effective = query_securities_as_of(
        connection,
        "2026-03-03",
        include_delisted=True,
        stock_code="000003.SZ",
    )
    default_on_delist = query_securities_as_of(connection, "2026-03-06", stock_code="000003.SZ")
    included_on_delist = query_securities_as_of(
        connection,
        "2026-03-06",
        include_delisted=True,
        stock_code="000003.SZ",
    )

    assert len(before_delist_visible) == 1
    assert not bool(before_delist_visible.iloc[0]["is_delisted_as_of"])
    assert pd.isna(before_delist_visible.iloc[0]["delist_date"])
    assert pd.isna(before_delist_visible.iloc[0]["delist_publish_time"])
    assert pd.isna(before_delist_visible.iloc[0]["delist_effective_date"])

    assert len(on_delist_effective) == 1
    assert not bool(on_delist_effective.iloc[0]["is_delisted_as_of"])
    assert on_delist_effective.iloc[0]["delist_date"] == pd.Timestamp("2026-03-06")
    assert on_delist_effective.iloc[0]["delist_publish_time"] == pd.Timestamp(
        "2026-03-02 18:00:00"
    )
    assert on_delist_effective.iloc[0]["delist_effective_date"] == pd.Timestamp(
        "2026-03-03"
    )

    assert default_on_delist.empty
    assert len(included_on_delist) == 1
    assert bool(included_on_delist.iloc[0]["is_delisted_as_of"])
    assert included_on_delist.iloc[0]["delist_date"] == pd.Timestamp("2026-03-06")


def test_industry_classifications_return_active_industry(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    rows = query_industry_classifications_as_of(
        connection,
        "2026-01-06",
        industry_standard="fixture_l1_l2",
        version="2026Q1",
        stock_code="000001.SZ",
    )

    assert len(rows) == 1
    assert rows.iloc[0]["industry_l1"] == "Financials"
    assert rows.iloc[0]["industry_l2"] == "Banking"


def test_industry_classification_switch_uses_fixture_visibility_fields(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before_switch_visible = query_industry_classifications_as_of(
        connection,
        "2026-02-12",
        industry_standard="fixture_l1_l2",
        version="2026Q1",
        stock_code="000005.SZ",
    )
    switch_visible_before_out_date = query_industry_classifications_as_of(
        connection,
        "2026-02-13",
        industry_standard="fixture_l1_l2",
        version="2026Q1",
        stock_code="000005.SZ",
    )
    new = query_industry_classifications_as_of(
        connection,
        "2026-02-16",
        industry_standard="fixture_l1_l2",
        version="2026Q1",
        stock_code="000005.SZ",
    )

    assert before_switch_visible["industry_l2"].tolist() == ["Software"]
    assert pd.isna(before_switch_visible.iloc[0]["out_date"])
    assert pd.isna(before_switch_visible.iloc[0]["out_publish_time"])
    assert pd.isna(before_switch_visible.iloc[0]["out_effective_date"])

    assert switch_visible_before_out_date["industry_l2"].tolist() == ["Software"]
    assert switch_visible_before_out_date.iloc[0]["out_date"] == pd.Timestamp("2026-02-16")
    assert switch_visible_before_out_date.iloc[0]["out_publish_time"] == pd.Timestamp(
        "2026-02-12 18:00:00"
    )
    assert switch_visible_before_out_date.iloc[0]["out_effective_date"] == pd.Timestamp(
        "2026-02-13"
    )

    assert new["industry_l1"].tolist() == ["Technology"]
    assert new["industry_l2"].tolist() == ["Internet"]
    assert pd.isna(new.iloc[0]["out_date"])


def test_publish_time_and_effective_date_never_exceed_as_of_in_visible_results(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    as_of = date(2026, 1, 12)
    snapshot = build_as_of_snapshot(connection, as_of, index_code=INDEX_CODE)

    for rows in [snapshot.fundamental_reports, snapshot.announcements, snapshot.risk_events]:
        assert (_date_series(rows["publish_time"]) <= as_of).all()
        assert (_date_series(rows["effective_date"]) <= as_of).all()


def test_build_as_of_snapshot_returns_nine_sorted_dataframes(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    snapshot = build_as_of_snapshot(connection, "2026-01-12", index_code=INDEX_CODE)
    frames = {
        "daily_prices": ["stock_code", "trade_date"],
        "valuation_daily": ["stock_code", "trade_date"],
        "universe_members": ["index_code", "stock_code", "in_date"],
        "securities": ["stock_code"],
        "st_status": ["stock_code", "in_date", "st_type"],
        "industry_classifications": ["stock_code", "industry_standard", "version", "in_date"],
        "fundamental_reports": ["stock_code", "report_period", "publish_time"],
        "announcements": ["stock_code", "publish_time", "announcement_id"],
        "risk_events": ["stock_code", "publish_time", "event_id"],
    }

    assert isinstance(snapshot, AsOfSnapshot)
    assert len(frames) == 9
    for name, sort_columns in frames.items():
        rows = getattr(snapshot, name)
        assert isinstance(rows, pd.DataFrame)
        _assert_sorted(rows, sort_columns)


def test_parse_as_of_date_accepts_supported_explicit_date_types() -> None:
    assert parse_as_of_date("2026-01-12") == date(2026, 1, 12)
    assert parse_as_of_date(date(2026, 1, 12)) == date(2026, 1, 12)
    assert parse_as_of_date(datetime(2026, 1, 12, 15, 30)) == date(2026, 1, 12)
    assert parse_as_of_date(pd.Timestamp("2026-01-12 15:30:00")) == date(2026, 1, 12)

    with pytest.raises(ValueError):
        parse_as_of_date("2026-01-12 15:30:00")


def test_as_of_before_fixture_history_returns_empty_results(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    snapshot = build_as_of_snapshot(connection, "2019-12-31", index_code=INDEX_CODE)

    for rows in [
        snapshot.daily_prices,
        snapshot.valuation_daily,
        snapshot.universe_members,
        snapshot.securities,
        snapshot.st_status,
        snapshot.industry_classifications,
        snapshot.fundamental_reports,
        snapshot.announcements,
        snapshot.risk_events,
    ]:
        assert rows.empty


def test_as_of_after_fixture_history_returns_all_already_visible_fixture_rows(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    snapshot = build_as_of_snapshot(
        connection,
        "2026-07-15",
        index_code=INDEX_CODE,
        include_delisted=True,
    )

    assert len(snapshot.daily_prices) == _table_count(connection, "daily_prices")
    assert len(snapshot.valuation_daily) == _table_count(connection, "valuation_daily")
    assert len(snapshot.securities) == _table_count(connection, "securities")
    assert len(snapshot.universe_members) == 4
    assert len(snapshot.st_status) == 0
    assert len(snapshot.industry_classifications) == 5
    assert len(snapshot.fundamental_reports) == _table_count(connection, "fundamental_reports")
    assert len(snapshot.announcements) == _table_count(connection, "announcements")
    assert len(snapshot.risk_events) == _table_count(connection, "risk_events")


def test_load_as_of_snapshot_runs_with_legacy_interval_csvs(tmp_path: Path) -> None:
    input_dir = tmp_path / "legacy"
    db_path = tmp_path / "legacy.duckdb"
    build_fixtures(input_dir)

    _drop_csv_columns(input_dir / "securities.csv", {"delist_publish_time", "delist_effective_date"})
    for filename in ["industry_classifications.csv", "universe_members.csv", "st_status.csv"]:
        _drop_csv_columns(
            input_dir / filename,
            {"in_publish_time", "in_effective_date", "out_publish_time", "out_effective_date"},
        )

    ingest_local(input_dir=input_dir, db_path=db_path)
    snapshot = load_as_of_snapshot(
        db_path,
        "2026-02-17",
        index_code=INDEX_CODE,
        include_delisted=True,
    )

    assert "000003.SZ" in snapshot.universe_members["stock_code"].tolist()
    assert snapshot.securities.loc[
        snapshot.securities["stock_code"] == "000003.SZ", "delist_date"
    ].isna().all()
    assert not snapshot.st_status.empty


def test_load_as_of_snapshot_opens_read_only_connection_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    class DummyConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    dummy = DummyConnection()

    def fake_connect(db_path: str, read_only: bool = False) -> DummyConnection:
        calls.append((db_path, read_only))
        return dummy

    def fake_build_as_of_snapshot(**kwargs: object) -> AsOfSnapshot:
        assert kwargs["connection"] is dummy
        empty_frames = [pd.DataFrame() for _ in range(9)]
        return AsOfSnapshot(date(2026, 1, 12), *empty_frames)

    monkeypatch.setattr(asof_module.duckdb, "connect", fake_connect)
    monkeypatch.setattr(asof_module, "build_as_of_snapshot", fake_build_as_of_snapshot)

    snapshot = load_as_of_snapshot("readonly.duckdb", "2026-01-12")

    assert snapshot.as_of_date == date(2026, 1, 12)
    assert calls == [("readonly.duckdb", True)]
    assert dummy.closed


def test_load_as_of_snapshot_closes_connection_when_build_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    dummy = DummyConnection()

    def fake_connect(db_path: str, read_only: bool = False) -> DummyConnection:
        return dummy

    def fail_build_as_of_snapshot(**kwargs: object) -> AsOfSnapshot:
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(asof_module.duckdb, "connect", fake_connect)
    monkeypatch.setattr(asof_module, "build_as_of_snapshot", fail_build_as_of_snapshot)

    with pytest.raises(RuntimeError, match="snapshot failed"):
        load_as_of_snapshot("readonly.duckdb", "2026-01-12")

    assert dummy.closed


def test_duckdb_read_only_connection_rejects_writes(fixture_db_path: Path) -> None:
    db = duckdb.connect(str(fixture_db_path), read_only=True)
    try:
        with pytest.raises(duckdb.Error):
            db.execute("CREATE TABLE should_fail (id INTEGER)")
    finally:
        db.close()


def test_cli_as_of_runs_and_prints_snapshot_summary(fixture_db_path: Path) -> None:
    result = subprocess.run(
        [
            "ashare",
            "as-of",
            "--as-of",
            "2026-03-02",
            "--db-path",
            str(fixture_db_path),
            "--index-code",
            INDEX_CODE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "as_of_date: 2026-03-02" in result.stdout
    assert "  universe_members: 5" in result.stdout
    assert "  securities: 5" in result.stdout
    assert "universe_stock_codes: 000001.SZ, 000002.SZ, 000003.SZ" in result.stdout
    assert "delisted_stock_codes: (empty)" in result.stdout


def test_cli_as_of_include_delisted_prints_delisted_sample(fixture_db_path: Path) -> None:
    result = subprocess.run(
        [
            "ashare",
            "as-of",
            "--as-of",
            "2026-03-06",
            "--db-path",
            str(fixture_db_path),
            "--index-code",
            INDEX_CODE,
            "--include-delisted",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "delisted_stock_codes: 000003.SZ" in result.stdout
    assert "  universe_members: 4" in result.stdout
    assert "  securities: 5" in result.stdout


def test_cli_help_lists_as_of_and_existing_commands() -> None:
    result = subprocess.run(
        ["ashare", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    for command in [
        "as-of",
        "db-init",
        "ingest-local",
        "ingest",
        "validate-factors",
        "event-study",
        "daily-report",
        "scan",
        "backtest",
        "report",
        "stock-report",
    ]:
        assert command in result.stdout
