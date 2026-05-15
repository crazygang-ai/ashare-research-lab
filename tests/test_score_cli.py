from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess

import duckdb
import pandas as pd

from ashare.storage.db import init_db


def _run_ashare(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["ashare", *args], check=check, capture_output=True, text=True)


def _write_score_config(path: Path, min_coverage: float = 0.2) -> None:
    path.write_text(
        f"""
version: phase3.test
score:
  top_n: 2
  min_available_factor_weight: 0.5
validation_gate:
  mode: strict
  required_horizons: [20]
  min_coverage: {min_coverage}
  min_valid_oriented_ic_dates: 1
  min_mean_oriented_rank_ic: 0.0
  min_oriented_icir: -999.0
  require_group_return_rows: true
normalization:
  method: percentile_rank
  output_min: 0.0
  output_max: 100.0
  single_observation_score: 50.0
  all_equal_score: 50.0
hard_filters:
  is_st:
    enabled: true
    pass_value: 0.0
    missing: exclude
  is_suspended:
    enabled: true
    pass_value: 0.0
    missing: exclude
  is_delisted:
    enabled: true
    pass_value: 0.0
    missing: exclude
  low_liquidity:
    enabled: true
    pass_value: 0.0
    missing: exclude
groups:
  financial:
    enabled: true
    required: false
    weight: 0.5
    factors:
      revenue_yoy:
        enabled: true
        weight: 0.5
      profit_yoy:
        enabled: true
        weight: 0.5
  momentum:
    enabled: true
    required: false
    weight: 0.5
    factors:
      return_20d:
        enabled: true
        weight: 1.0
  event:
    enabled: false
    required: false
    weight: 0.0
    factors: {{}}
risk_penalty:
  enabled: true
  max_penalty: 15.0
  factors: {{}}
diagnostics:
  sensitivity:
    enabled: true
    perturbation_pct: 0.10
    top_n: 2
  yearly_stability:
    enabled: true
    signal_frequency: month_end
    horizons: [20]
    min_signal_dates_per_year: 1
""".lstrip(),
        encoding="utf-8",
    )


def _write_dictionary(path: Path) -> None:
    path.write_text(
        """
factors:
  revenue_yoy:
    type: factor
    direction: higher_is_better
    score_group: financial
  profit_yoy:
    type: factor
    direction: higher_is_better
    score_group: financial
  return_20d:
    type: factor
    direction: higher_is_better
    score_group: momentum
  is_st:
    type: hard_filter
    direction: boolean_filter
  is_suspended:
    type: hard_filter
    direction: boolean_filter
  is_delisted:
    type: hard_filter
    direction: boolean_filter
  low_liquidity:
    type: hard_filter
    direction: boolean_filter
""".lstrip(),
        encoding="utf-8",
    )


def _write_validation_dir(path: Path) -> None:
    path.mkdir(parents=True)
    factors = ["revenue_yoy", "profit_yoy", "return_20d"]
    pd.DataFrame({"factor_name": factors, "trade_date": ["2026-01-02"] * 3, "coverage": [1.0, 1.0, 1.0]}).to_csv(path / "coverage.csv", index=False)
    pd.DataFrame({"factor_name": factors, "horizon": [20, 20, 20]}).to_csv(path / "rank_ic.csv", index=False)
    pd.DataFrame(
        {
            "factor_name": factors,
            "horizon": [20, 20, 20],
            "valid_oriented_ic_dates": [1, 1, 1],
            "mean_oriented_rank_ic": [0.1, 0.1, 0.1],
            "oriented_icir": [float("nan"), float("nan"), float("nan")],
        }
    ).to_csv(path / "ic_summary.csv", index=False)
    pd.DataFrame({"factor_name": factors, "horizon": [20, 20, 20]}).to_csv(path / "group_returns.csv", index=False)
    pd.DataFrame({"factor_name": factors, "horizon": [20, 20, 20]}).to_csv(path / "decay_curve.csv", index=False)


def _build_score_db(path: Path) -> None:
    init_db(path)
    connection = duckdb.connect(str(path))
    try:
        connection.executemany(
            """
            INSERT INTO universe_members (
                index_code, stock_code, in_date, in_effective_date, source
            )
            VALUES ('LOCAL_FIXTURE', ?, '2020-01-01', '2020-01-01', 'fixture')
            """,
            [("A",), ("B",)],
        )
        connection.executemany(
            """
            INSERT INTO securities (stock_code, stock_name, exchange, list_date)
            VALUES (?, ?, 'SSE', '2020-01-01')
            """,
            [("A", "Alpha"), ("B", "Beta")],
        )
        rows: list[tuple[str, date, str, float, date, str]] = []
        for stock in ["A", "B"]:
            for hard_filter in ["is_st", "is_suspended", "is_delisted", "low_liquidity"]:
                rows.append((stock, date(2026, 1, 2), hard_filter, 0.0, date(2026, 1, 2), "score-cli"))
        rows.extend(
            [
                ("A", date(2026, 1, 2), "revenue_yoy", 0.2, date(2026, 1, 2), "score-cli"),
                ("A", date(2026, 1, 2), "profit_yoy", 0.2, date(2026, 1, 2), "score-cli"),
                ("A", date(2026, 1, 2), "return_20d", 0.1, date(2026, 1, 2), "score-cli"),
                ("B", date(2026, 1, 2), "revenue_yoy", 0.1, date(2026, 1, 2), "score-cli"),
                ("B", date(2026, 1, 2), "profit_yoy", 0.1, date(2026, 1, 2), "score-cli"),
                ("B", date(2026, 1, 2), "return_20d", 0.4, date(2026, 1, 2), "score-cli"),
            ]
        )
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


def _tables(path: Path) -> set[str]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    finally:
        connection.close()


def _factor_count(path: Path) -> int:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0])
    finally:
        connection.close()


def test_score_cli_writes_reports_and_does_not_write_db(tmp_path: Path) -> None:
    db_path = tmp_path / "ashare.duckdb"
    config_path = tmp_path / "scoring.yaml"
    dictionary_path = tmp_path / "dictionary.yaml"
    validation_dir = tmp_path / "validation"
    output_dir = tmp_path / "score"
    _build_score_db(db_path)
    _write_score_config(config_path)
    _write_dictionary(dictionary_path)
    _write_validation_dir(validation_dir)
    before_tables = _tables(db_path)
    before_count = _factor_count(db_path)

    result = _run_ashare(
        [
            "score",
            "--db-path", str(db_path),
            "--as-of", "2026-01-02",
            "--source-run-id", "score-cli",
            "--index-code", "LOCAL_FIXTURE",
            "--validation-dir", str(validation_dir),
            "--scoring-config", str(config_path),
            "--data-dictionary", str(dictionary_path),
            "--skip-diagnostics",
            "--output-dir", str(output_dir),
        ]
    )

    assert "composite score is for research only" in result.stdout
    assert "综合评分仅供研究复盘" in result.stdout
    for filename in [
        "scoring_report.md",
        "scored_candidates.csv",
        "score_breakdown.csv",
        "factor_normalized_scores.csv",
        "hard_filter_exclusions.csv",
        "validation_gate.csv",
        "weight_sensitivity.csv",
        "yearly_stability.csv",
        "score_metadata.json",
    ]:
        assert (output_dir / filename).exists()
    candidates = pd.read_csv(output_dir / "scored_candidates.csv")
    assert candidates["rank"].tolist() == [1, 2]
    assert candidates["hard_filter_passed"].all()
    gate = pd.read_csv(output_dir / "validation_gate.csv")
    assert (gate["validation_status"] == "PASS").sum() >= 3
    assert _tables(db_path) == before_tables
    assert _factor_count(db_path) == before_count


def test_score_cli_strict_gate_failure_writes_audit_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "ashare.duckdb"
    config_path = tmp_path / "scoring.yaml"
    dictionary_path = tmp_path / "dictionary.yaml"
    validation_dir = tmp_path / "validation"
    output_dir = tmp_path / "score"
    _build_score_db(db_path)
    _write_score_config(config_path, min_coverage=1.1)
    _write_dictionary(dictionary_path)
    _write_validation_dir(validation_dir)

    result = _run_ashare(
        [
            "score",
            "--db-path", str(db_path),
            "--as-of", "2026-01-02",
            "--source-run-id", "score-cli",
            "--index-code", "LOCAL_FIXTURE",
            "--validation-dir", str(validation_dir),
            "--scoring-config", str(config_path),
            "--data-dictionary", str(dictionary_path),
            "--output-dir", str(output_dir),
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "Validation gate failed in strict mode" in result.stderr
    assert (output_dir / "validation_gate.csv").exists()
    assert (output_dir / "score_metadata.json").exists()
    assert not (output_dir / "scored_candidates.csv").exists()


def test_score_cli_help_lists_score_command() -> None:
    result = _run_ashare(["--help"])

    assert "score" in result.stdout
