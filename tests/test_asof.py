from __future__ import annotations

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

    assert before.empty
    assert len(after) == 1
    assert after.iloc[0]["publish_time"] == pd.Timestamp("2026-01-05 18:00:00")
    assert after.iloc[0]["effective_date"] == pd.Timestamp("2026-01-06")


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


def test_universe_members_use_half_open_dates_and_mask_future_out_date(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before_delist = query_universe_members_as_of(
        connection,
        "2026-03-05",
        index_code=INDEX_CODE,
        stock_code="000003.SZ",
    )
    on_delist = query_universe_members_as_of(
        connection,
        "2026-03-06",
        index_code=INDEX_CODE,
        stock_code="000003.SZ",
    )

    assert len(before_delist) == 1
    assert pd.isna(before_delist.iloc[0]["out_date"])
    assert on_delist.empty


def test_st_status_uses_half_open_dates_and_masks_future_out_date(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before = query_st_status_as_of(connection, "2026-01-20")
    start = query_st_status_as_of(connection, "2026-01-21")
    out_date = query_st_status_as_of(connection, "2026-02-18")

    assert before.empty
    assert len(start) == 1
    assert start.iloc[0]["stock_code"] == "000002.SZ"
    assert pd.isna(start.iloc[0]["out_date"])
    assert out_date.empty


def test_securities_mask_future_delist_date_and_optionally_include_delisted(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before_delist = query_securities_as_of(
        connection,
        "2026-03-05",
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

    assert len(before_delist) == 1
    assert not bool(before_delist.iloc[0]["is_delisted_as_of"])
    assert pd.isna(before_delist.iloc[0]["delist_date"])
    assert default_on_delist.empty
    assert len(included_on_delist) == 1
    assert bool(included_on_delist.iloc[0]["is_delisted_as_of"])
    assert included_on_delist.iloc[0]["delist_date"] == pd.Timestamp("2026-03-06")


def test_industry_classifications_return_active_industry(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    rows = query_industry_classifications_as_of(
        connection,
        "2026-01-05",
        industry_standard="fixture_l1_l2",
        version="2026Q1",
        stock_code="000001.SZ",
    )

    assert len(rows) == 1
    assert rows.iloc[0]["industry_l1"] == "Financials"
    assert rows.iloc[0]["industry_l2"] == "Banking"


def test_industry_classification_switch_uses_half_open_interval(
    fixture_db_path: Path,
) -> None:
    writable = duckdb.connect(str(fixture_db_path))
    try:
        writable.executemany(
            """
            INSERT INTO industry_classifications (
                stock_code,
                industry_standard,
                industry_l1,
                industry_l2,
                in_date,
                out_date,
                version,
                source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "000001.SZ",
                    "switch_test",
                    "Old",
                    "Old L2",
                    date(2026, 1, 5),
                    date(2026, 2, 2),
                    "v1",
                    "test",
                ),
                (
                    "000001.SZ",
                    "switch_test",
                    "New",
                    "New L2",
                    date(2026, 2, 2),
                    None,
                    "v1",
                    "test",
                ),
            ],
        )

        old = query_industry_classifications_as_of(
            writable,
            "2026-02-01",
            industry_standard="switch_test",
        )
        new = query_industry_classifications_as_of(
            writable,
            "2026-02-02",
            industry_standard="switch_test",
        )
    finally:
        writable.close()

    assert old["industry_l1"].tolist() == ["Old"]
    assert pd.isna(old.iloc[0]["out_date"])
    assert new["industry_l1"].tolist() == ["New"]


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
        "2026-04-01",
        index_code=INDEX_CODE,
        include_delisted=True,
    )

    assert len(snapshot.daily_prices) == _table_count(connection, "daily_prices")
    assert len(snapshot.valuation_daily) == _table_count(connection, "valuation_daily")
    assert len(snapshot.securities) == _table_count(connection, "securities")
    assert len(snapshot.industry_classifications) == _table_count(
        connection,
        "industry_classifications",
    )
    assert len(snapshot.fundamental_reports) == _table_count(connection, "fundamental_reports")
    assert len(snapshot.announcements) == _table_count(connection, "announcements")
    assert len(snapshot.risk_events) == _table_count(connection, "risk_events")


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
            "2026-01-12",
            "--db-path",
            str(fixture_db_path),
            "--index-code",
            INDEX_CODE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "as_of_date: 2026-01-12" in result.stdout
    assert "daily_prices:" in result.stdout
    assert "universe_stock_codes:" in result.stdout


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
        "scan",
        "backtest",
        "report",
        "stock-report",
    ]:
        assert command in result.stdout
