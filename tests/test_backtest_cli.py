from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess

import duckdb
import pandas as pd
import pytest

from ashare.backtest.engine import run_topn_equal_weight_backtest
from ashare.reports.backtest_report import BACKTEST_REPORT_FILES, write_backtest_report
from ashare.storage.db import default_schema_path
from ashare.storage.universe_snapshots import write_factor_run_universe
from ashare.validation.runner import load_data_dictionary


def _build_backtest_db(db_path: Path) -> None:
    connection = duckdb.connect(str(db_path))
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    connection.executemany(
        "INSERT INTO trading_calendar (trade_date, is_open, source) VALUES (?, true, 'fixture')",
        [
            (date(2026, 1, 30),),
            (date(2026, 2, 2),),
            (date(2026, 2, 27),),
            (date(2026, 3, 2),),
        ],
    )
    for stock_code, name in [("A", "Alpha"), ("B", "Beta")]:
        connection.execute(
            """
            INSERT INTO securities (stock_code, stock_name, exchange, list_date, source)
            VALUES (?, ?, 'SSE', '2020-01-01', 'fixture')
            """,
            [stock_code, name],
        )
        connection.execute(
            """
            INSERT INTO universe_members (
                index_code, stock_code, in_date, in_effective_date, source
            )
            VALUES ('LOCAL', ?, '2020-01-01', '2020-01-01', 'fixture')
            """,
            [stock_code],
        )
    prices = [
        ("A", date(2026, 1, 30), 10.0),
        ("B", date(2026, 1, 30), 20.0),
        ("A", date(2026, 2, 2), 11.0),
        ("B", date(2026, 2, 2), 20.0),
        ("B", date(2026, 2, 27), 21.0),
    ]
    connection.executemany(
        """
        INSERT INTO daily_prices (
            stock_code, trade_date, open, high, low, close, volume, amount,
            adj_factor, is_suspended, limit_up, limit_down, source
        )
        VALUES (?, ?, ?, ?, ?, ?, 1000, 10000, 1, false, ?, ?, 'fixture')
        """,
        [
            (code, trade_date, close, close, close, close, close * 1.1, close * 0.9)
            for code, trade_date, close in prices
        ],
    )
    connection.executemany(
        """
        INSERT INTO valuation_daily (stock_code, trade_date, total_mv, float_mv, source)
        VALUES (?, ?, ?, ?, 'fixture')
        """,
        [
            ("A", date(2026, 1, 30), 100.0, 80.0),
            ("B", date(2026, 1, 30), 200.0, 160.0),
            ("A", date(2026, 2, 27), 120.0, 90.0),
            ("B", date(2026, 2, 27), 210.0, 170.0),
        ],
    )
    factor_rows = []
    for stock_code, return_value in [("A", 0.3), ("B", 0.1)]:
        factor_rows.append((stock_code, date(2026, 1, 30), "return_20d", return_value, date(2026, 1, 30), "run"))
        for factor_name in ["is_st", "is_suspended", "is_delisted", "low_liquidity"]:
            factor_rows.append((stock_code, date(2026, 1, 30), factor_name, 0.0, date(2026, 1, 30), "run"))
    connection.executemany(
        """
        INSERT INTO factor_values (
            stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        factor_rows,
    )
    connection.close()


def _audit_config_without_clean_worktree_gate(tmp_path: Path) -> Path:
    path = tmp_path / "audit.yaml"
    artifact_root = tmp_path / "reports"
    path.write_text(
        f"""
version: phase5.v1
run_tracking:
  formal_requires_clean_worktree: false
artifacts:
  default_root: {artifact_root.as_posix()}
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_backtest_cli_runs_writes_reports_and_does_not_write_duckdb(tmp_path: Path) -> None:
    db_path = tmp_path / "ashare.duckdb"
    output_dir = tmp_path / "reports"
    _build_backtest_db(db_path)
    before = _table_counts(db_path, ["factor_values", "research_runs"])

    result = subprocess.run(
        [
            "ashare",
            "backtest",
            "--strategy",
            "topn-equal",
            "--from",
            "2026-01-01",
            "--to",
            "2026-02-28",
            "--db-path",
            str(db_path),
            "--index-code",
            "LOCAL",
            "--source-run-id",
            "run",
            "--sort-factor",
            "return_20d",
            "--top",
            "1",
            "--output-dir",
            str(output_dir),
            "--overwrite",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "backtest report is for research only" in result.stdout
    assert "回测报告仅供研究复盘" in result.stdout
    assert set(path.name for path in output_dir.iterdir()) == {
        *set(BACKTEST_REPORT_FILES.values()),
        "run_manifest.json",
    }
    metrics = pd.read_csv(output_dir / "metrics.csv")
    trades = pd.read_csv(output_dir / "trade_ledger.csv")
    holdings = pd.read_csv(output_dir / "holdings.csv")
    report_text = (output_dir / "backtest_report.md").read_text(encoding="utf-8")
    assert len(metrics) == 1
    assert not trades.empty
    assert "last_visible_close" in set(holdings["price_source"])
    assert "T+1" in report_text
    assert "开盘" in report_text
    assert "不包含风格归因" in report_text
    after = _table_counts(db_path, ["factor_values", "research_runs"])
    assert after["factor_values"] == before["factor_values"]
    assert after["research_runs"] == before["research_runs"] + 1


def test_backtest_cli_rejects_unsupported_strategy() -> None:
    result = subprocess.run(
        [
            "ashare",
            "backtest",
            "--strategy",
            "other",
            "--from",
            "2026-01-01",
            "--to",
            "2026-02-28",
            "--source-run-id",
            "run",
            "--sort-factor",
            "return_20d",
            "--index-code",
            "LOCAL",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "topn-equal" in result.stderr


def test_formal_backtest_cli_rejects_current_snapshot_universe(tmp_path: Path) -> None:
    db_path = tmp_path / "ashare.duckdb"
    output_dir = tmp_path / "formal-backtest"
    _build_backtest_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        write_factor_run_universe(
            connection,
            source_run_id="run",
            trade_date=date(2026, 1, 30),
            as_of_date=date(2026, 1, 30),
            index_code="LOCAL",
            universe=pd.DataFrame(
                {
                    "index_code": ["LOCAL", "LOCAL"],
                    "stock_code": ["A", "B"],
                    "source": ["fixture", "fixture"],
                    "source_tag": ["fixture", "fixture"],
                    "universe_kind": ["current_snapshot", "current_snapshot"],
                }
            ),
            data_source="fixture",
        )
    finally:
        connection.close()

    result = subprocess.run(
        [
            "ashare",
            "backtest",
            "--strategy",
            "topn-equal",
            "--from",
            "2026-01-01",
            "--to",
            "2026-02-28",
            "--db-path",
            str(db_path),
            "--index-code",
            "LOCAL",
            "--source-run-id",
            "run",
            "--sort-factor",
            "return_20d",
            "--top",
            "1",
            "--data-source",
            "fixture",
            "--run-mode",
            "formal",
            "--audit-config",
            str(_audit_config_without_clean_worktree_gate(tmp_path)),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "historical PIT universe" in result.stderr
    assert "current_snapshot" in result.stderr


def test_formal_backtest_cli_requires_snapshot_for_each_signal_date(tmp_path: Path) -> None:
    db_path = tmp_path / "ashare.duckdb"
    output_dir = tmp_path / "formal-backtest-missing-snapshot"
    _build_backtest_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        write_factor_run_universe(
            connection,
            source_run_id="run",
            trade_date=date(2026, 2, 27),
            as_of_date=date(2026, 2, 27),
            index_code="LOCAL",
            universe=pd.DataFrame(
                {
                    "index_code": ["LOCAL", "LOCAL"],
                    "stock_code": ["A", "B"],
                    "source": ["fixture", "fixture"],
                    "source_tag": ["fixture", "fixture"],
                    "universe_kind": ["historical_pit", "historical_pit"],
                }
            ),
            data_source="fixture",
        )
    finally:
        connection.close()

    result = subprocess.run(
        [
            "ashare",
            "backtest",
            "--strategy",
            "topn-equal",
            "--from",
            "2026-01-01",
            "--to",
            "2026-02-28",
            "--db-path",
            str(db_path),
            "--index-code",
            "LOCAL",
            "--source-run-id",
            "run",
            "--sort-factor",
            "return_20d",
            "--top",
            "1",
            "--data-source",
            "fixture",
            "--run-mode",
            "formal",
            "--audit-config",
            str(_audit_config_without_clean_worktree_gate(tmp_path)),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires factor_run_universe rows" in result.stderr
    assert "2026-01-30" in result.stderr


def test_formal_backtest_cli_rejects_snapshot_source_tag_mismatch(tmp_path: Path) -> None:
    db_path = tmp_path / "ashare_mixed_source.duckdb"
    output_dir = tmp_path / "formal-backtest-mixed-source"
    _build_backtest_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            UPDATE universe_members
            SET source_tag = 'fixture',
                universe_kind = 'historical_pit'
            """
        )
        write_factor_run_universe(
            connection,
            source_run_id="run",
            trade_date=date(2026, 1, 30),
            as_of_date=date(2026, 1, 30),
            index_code="LOCAL",
            universe=pd.DataFrame(
                {
                    "index_code": ["LOCAL", "LOCAL"],
                    "stock_code": ["A", "B"],
                    "source": ["universe-vendor", "universe-vendor"],
                    "source_tag": ["universe-vendor", "universe-vendor"],
                    "universe_kind": ["historical_pit", "historical_pit"],
                }
            ),
            data_source="universe-vendor",
        )
    finally:
        connection.close()

    result = subprocess.run(
        [
            "ashare",
            "backtest",
            "--strategy",
            "topn-equal",
            "--from",
            "2026-01-01",
            "--to",
            "2026-02-28",
            "--db-path",
            str(db_path),
            "--index-code",
            "LOCAL",
            "--source-run-id",
            "run",
            "--sort-factor",
            "return_20d",
            "--top",
            "1",
            "--data-source",
            "fixture",
            "--run-mode",
            "formal",
            "--audit-config",
            str(_audit_config_without_clean_worktree_gate(tmp_path)),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "source_tag" in result.stderr
    assert "fixture" in result.stderr
    assert "universe-vendor" in result.stderr


def test_write_backtest_report_outputs_one_markdown_and_eight_csvs_and_fails_without_overwrite(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ashare.duckdb"
    output_dir = tmp_path / "reports"
    _build_backtest_db(db_path)
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        result = run_topn_equal_weight_backtest(
            connection,
            start_date="2026-01-01",
            end_date="2026-02-28",
            source_run_id="run",
            sort_factor="return_20d",
            index_code="LOCAL",
            top_n=1,
            data_dictionary=load_data_dictionary(),
        )
    finally:
        connection.close()

    metadata = {
        "generated_at": "2026-01-01T00:00:00+08:00",
        "db_path": str(db_path),
        "start_date": "2026-01-01",
        "end_date": "2026-02-28",
        "source_run_id": "run",
        "sort_factor": "return_20d",
        "index_code": "LOCAL",
        "top_n": 1,
        "initial_cash": 1_000_000,
        "backtest_config_path": "configs/backtest.yaml",
        "data_dictionary_path": "configs/data_dictionary.yaml",
    }
    paths = write_backtest_report(result, output_dir, metadata, overwrite=False)

    assert len(paths) == 9
    assert sum(1 for path in paths.values() if path.suffix == ".md") == 1
    assert sum(1 for path in paths.values() if path.suffix == ".csv") == 8
    with pytest.raises(FileExistsError):
        write_backtest_report(result, output_dir, metadata, overwrite=False)


def _table_counts(db_path: Path, table_names: list[str]) -> dict[str, int]:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return {
            table_name: int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
            for table_name in table_names
        }
    finally:
        connection.close()
