from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ashare.ingest.index_members import import_index_members
from ashare.pit.asof import query_universe_members_as_of


def _member_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "index_code": ["000300.SH", "000300.SH", "000300.SH"],
            "stock_code": ["000001.SZ", "000002.SZ", "000001.SZ"],
            "in_date": ["2026-01-01", "2026-01-01", "2026-02-01"],
            "out_date": ["2026-02-01", "", ""],
            "in_publish_time": ["2025-12-30 18:00:00", "2025-12-30 18:00:00", "2026-01-30 18:00:00"],
            "in_effective_date": ["2026-01-01", "2026-01-01", "2026-02-01"],
            "out_publish_time": ["2026-01-30 18:00:00", "", ""],
            "out_effective_date": ["2026-02-01", "", ""],
            "source": ["fixture_vendor", "fixture_vendor", "fixture_vendor"],
            "source_tag": ["hs300_fixture", "hs300_fixture", "hs300_fixture"],
        }
    )


def test_import_index_members_and_query_as_of(tmp_path: Path) -> None:
    input_path = tmp_path / "members.csv"
    db_path = tmp_path / "members.duckdb"
    _member_frame().to_csv(input_path, index=False)

    result = import_index_members(input_path=input_path, db_path=db_path)

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        jan = query_universe_members_as_of(
            connection,
            "2026-01-15",
            index_code="000300.SH",
            source_tag="hs300_fixture",
        )
        feb = query_universe_members_as_of(
            connection,
            "2026-02-15",
            index_code="000300.SH",
            source_tag="hs300_fixture",
        )
    finally:
        connection.close()

    assert result.row_count == 3
    assert set(jan["stock_code"]) == {"000001.SZ", "000002.SZ"}
    assert set(feb["stock_code"]) == {"000001.SZ", "000002.SZ"}
    assert set(feb["universe_kind"]) == {"historical_pit"}


def test_import_index_members_rejects_overlaps(tmp_path: Path) -> None:
    frame = _member_frame()
    frame.loc[2, "in_effective_date"] = "2026-01-15"
    frame.loc[2, "in_publish_time"] = "2026-01-14 18:00:00"
    input_path = tmp_path / "bad_members.csv"
    frame.to_csv(input_path, index=False)

    with pytest.raises(ValueError, match="Overlapping"):
        import_index_members(input_path=input_path, db_path=tmp_path / "bad.duckdb")


def test_import_index_members_rejects_publish_time_after_effective_date(
    tmp_path: Path,
) -> None:
    frame = _member_frame()
    frame.loc[0, "in_publish_time"] = "2026-01-02 09:30:00"
    frame.loc[0, "in_effective_date"] = "2026-01-01"
    input_path = tmp_path / "bad_publish.csv"
    frame.to_csv(input_path, index=False)

    with pytest.raises(ValueError, match="in_publish_time must be on or before in_effective_date"):
        import_index_members(input_path=input_path, db_path=tmp_path / "bad_publish.duckdb")


def test_import_index_members_rejects_incomplete_historical_exit_visibility(
    tmp_path: Path,
) -> None:
    frame = _member_frame()
    frame.loc[0, "out_publish_time"] = ""
    input_path = tmp_path / "bad_exit.csv"
    frame.to_csv(input_path, index=False)

    with pytest.raises(ValueError, match="historical PIT exit rows require"):
        import_index_members(input_path=input_path, db_path=tmp_path / "bad_exit.duckdb")
