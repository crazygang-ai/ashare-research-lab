from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from ashare.reports.data_quality_gate import build_data_quality_gate, write_data_quality_gate
from ashare.reports.run_summary import ArtifactBundle
from ashare.storage.db import init_db


def _bundle(tmp_path: Path) -> ArtifactBundle:
    path = tmp_path / "candidates.csv"
    path.write_text("stock_code\nA\n", encoding="utf-8")
    return ArtifactBundle(
        kind="scan",
        requested_run_id="scan-run",
        run_id="scan-run",
        files={"candidates.csv": path},
        file_display={"candidates.csv": str(path)},
        artifact_rows=[],
        run_metadata={},
        resolved_via="explicit_run_id",
    )


def _build_gate_db(
    path: Path,
    *,
    include_prices: bool = True,
    calendar_source: str | None = "fixture",
) -> None:
    init_db(path)
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            INSERT INTO trading_calendar (trade_date, is_open, prev_trade_date, next_trade_date, source)
            VALUES ('2026-01-02', true, NULL, NULL, ?)
            """,
            [calendar_source],
        )
        connection.executemany(
            """
            INSERT INTO universe_members (index_code, stock_code, in_date, in_effective_date, source)
            VALUES ('LOCAL', ?, '2020-01-01', '2020-01-01', 'fixture')
            """,
            [("A",), ("B",)],
        )
        connection.executemany(
            """
            INSERT INTO securities (stock_code, stock_name, exchange, list_date, source)
            VALUES (?, ?, 'SSE', '2020-01-01', 'fixture')
            """,
            [("A", "Alpha"), ("B", "Beta")],
        )
        if include_prices:
            connection.executemany(
                """
                INSERT INTO daily_prices (
                    stock_code, trade_date, open, high, low, close, volume, amount,
                    adj_factor, is_suspended, limit_up, limit_down, source
                )
                VALUES (?, '2026-01-02', 1, 1, 1, 1, 1000, 1000, 1, false, NULL, NULL, 'fixture')
                """,
                [("A",), ("B",)],
            )
        connection.executemany(
            """
            INSERT INTO valuation_daily (
                stock_code, trade_date, pe_ttm, pb, ps, dividend_yield, total_mv, float_mv, source
            )
            VALUES (?, '2026-01-02', 10, 1, 1, 0.01, 100, 90, 'fixture')
            """,
            [("A",), ("B",)],
        )
        rows = []
        for stock in ["A", "B"]:
            for factor in ["is_st", "is_suspended", "is_delisted", "low_liquidity", "return_20d"]:
                rows.append((stock, date(2026, 1, 2), factor, 0.0, date(2026, 1, 2), "factor-run"))
        connection.executemany(
            """
            INSERT INTO factor_values (
                stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    finally:
        connection.close()


def _set_universe_kind(path: Path, universe_kind: str) -> None:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            UPDATE universe_members
            SET source_tag = 'fixture',
                universe_kind = ?
            """,
            [universe_kind],
        )
    finally:
        connection.close()


def test_data_quality_gate_passes_without_blocking_failures(tmp_path: Path) -> None:
    db_path = tmp_path / "gate.duckdb"
    config_path = tmp_path / "audit.yaml"
    config_path.write_text("version: phase5.v1\n", encoding="utf-8")
    _build_gate_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        result = build_data_quality_gate(
            connection,
            as_of_date="2026-01-02",
            source_run_id="factor-run",
            input_artifacts=[_bundle(tmp_path)],
            config_paths=[config_path],
            repo_root=tmp_path,
            index_code="LOCAL",
        )
    finally:
        connection.close()

    assert not result.has_blocking_failures
    assert "PASS" in result.table["status"].tolist()
    paths = write_data_quality_gate(result, tmp_path / "gate")
    assert (tmp_path / "gate" / "data_quality_gate.csv").exists()
    assert (tmp_path / "gate" / "data_quality_gate.json").exists()
    assert paths["csv"].name == "data_quality_gate.csv"


def test_data_quality_gate_flags_blocking_price_coverage_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "gate_fail.duckdb"
    config_path = tmp_path / "audit.yaml"
    config_path.write_text("version: phase5.v1\n", encoding="utf-8")
    _build_gate_db(db_path, include_prices=False)
    connection = duckdb.connect(str(db_path))
    try:
        result = build_data_quality_gate(
            connection,
            as_of_date="2026-01-02",
            source_run_id="factor-run",
            input_artifacts=[_bundle(tmp_path)],
            config_paths=[config_path],
            repo_root=tmp_path,
            index_code="LOCAL",
        )
    finally:
        connection.close()

    assert result.has_blocking_failures
    row = result.table[result.table["check_name"] == "daily_prices_coverage"].iloc[0]
    assert row["status"] == "FAIL"
    assert row["severity"] == "blocking"


def test_data_quality_gate_filters_trading_calendar_by_data_source(tmp_path: Path) -> None:
    db_path = tmp_path / "gate_calendar_source.duckdb"
    config_path = tmp_path / "audit.yaml"
    config_path.write_text("version: phase5.v1\n", encoding="utf-8")
    _build_gate_db(db_path, calendar_source="other-source")
    connection = duckdb.connect(str(db_path))
    try:
        result = build_data_quality_gate(
            connection,
            as_of_date="2026-01-02",
            source_run_id="factor-run",
            input_artifacts=[_bundle(tmp_path)],
            config_paths=[config_path],
            repo_root=tmp_path,
            index_code="LOCAL",
            data_source="fixture",
        )
    finally:
        connection.close()

    row = result.table[result.table["check_name"] == "trading_calendar_open"].iloc[0]
    assert row["status"] == "FAIL"
    assert row["severity"] == "blocking"
    assert "rows=0" in row["observed_value"]


def test_data_quality_gate_warns_on_current_snapshot_universe_kind(tmp_path: Path) -> None:
    db_path = tmp_path / "gate_snapshot.duckdb"
    config_path = tmp_path / "audit.yaml"
    config_path.write_text("version: phase5.v1\n", encoding="utf-8")
    _build_gate_db(db_path)
    _set_universe_kind(db_path, "current_snapshot")
    connection = duckdb.connect(str(db_path))
    try:
        result = build_data_quality_gate(
            connection,
            as_of_date="2026-01-02",
            source_run_id="factor-run",
            input_artifacts=[_bundle(tmp_path)],
            config_paths=[config_path],
            repo_root=tmp_path,
            index_code="LOCAL",
            data_source="fixture",
        )
    finally:
        connection.close()

    row = result.table[result.table["check_name"] == "universe_kind_profile"].iloc[0]
    assert row["status"] == "WARN"
    assert row["severity"] == "warning"
    assert row["observed_value"] == "current_snapshot=2"
    assert result.metadata["universe_kind_counts"] == {"current_snapshot": 2}


def test_data_quality_gate_can_require_historical_pit_universe_kind(tmp_path: Path) -> None:
    db_path = tmp_path / "gate_snapshot_required.duckdb"
    config_path = tmp_path / "audit.yaml"
    config_path.write_text("version: phase5.v1\n", encoding="utf-8")
    _build_gate_db(db_path)
    _set_universe_kind(db_path, "current_snapshot")
    connection = duckdb.connect(str(db_path))
    try:
        result = build_data_quality_gate(
            connection,
            as_of_date="2026-01-02",
            source_run_id="factor-run",
            input_artifacts=[_bundle(tmp_path)],
            config_paths=[config_path],
            repo_root=tmp_path,
            index_code="LOCAL",
            data_source="fixture",
            gate_config={"required_universe_kind": "historical_pit"},
        )
    finally:
        connection.close()

    row = result.table[result.table["check_name"] == "universe_kind_profile"].iloc[0]
    assert row["status"] == "FAIL"
    assert row["severity"] == "blocking"
    assert row["threshold"] == "historical_pit"
    assert result.has_blocking_failures
