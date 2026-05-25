from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ashare.reports.daily import build_daily_report, write_daily_report
from ashare.reports.data_quality_gate import DataQualityGateResult
from ashare.reports.run_summary import ArtifactBundle
from ashare.storage.db import init_db


def _bundle(kind: str, run_id: str, directory: Path, files: dict[str, str]) -> ArtifactBundle:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    display = {}
    for filename, text in files.items():
        path = directory / filename
        path.write_text(text, encoding="utf-8")
        paths[filename] = path
        display[filename] = str(path)
    return ArtifactBundle(
        kind=kind,
        requested_run_id=run_id,
        run_id=run_id,
        files=paths,
        file_display=display,
        artifact_rows=[],
        run_metadata={"status": "succeeded"},
        resolved_via="explicit_run_id",
    )


def test_daily_report_renders_required_sections_and_details(tmp_path: Path) -> None:
    db_path = tmp_path / "daily.duckdb"
    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            INSERT INTO announcements (
                announcement_id, source, source_tag, stock_code, title, announcement_type,
                publish_time, effective_date, url, raw_path, text_hash
            )
            VALUES ('ann-1', 'fixture', 'fixture', 'A', 'Alpha buyback', 'buyback',
                    '2026-01-01 18:00:00', '2026-01-02', '', '', 'hash')
            """
        )
        gate = DataQualityGateResult(
            table=pd.DataFrame(
                [
                    {
                        "check_name": "trading_calendar_open",
                        "status": "PASS",
                        "severity": "info",
                        "observed_value": "open",
                        "threshold": "open",
                        "message": "ok",
                    }
                ]
            ),
            metadata={"as_of_date": "2026-01-02"},
        )
        scan = _bundle(
            "scan",
            "scan-run",
            tmp_path / "scan",
            {
                "candidates.csv": (
                    "rank,stock_code,stock_name,industry_l1,industry_l2,selection_reason,risk_tips\n"
                    "1,A,Alpha,Tech,Software,reason,none\n"
                ),
                "candidate_list.md": "# Candidate List\n",
            },
        )
        score = _bundle(
            "scoring",
            "score-run",
            tmp_path / "score",
            {
                "scored_candidates.csv": (
                    "rank,stock_code,stock_name,industry_l1,industry_l2,total_score,"
                    "financial_score,valuation_score,momentum_score,event_score,risk_penalty,"
                    "hard_filter_passed,selection_reason,risk_tips\n"
                    "1,A,Alpha,Tech,Software,88,40,20,28,0,0,true,score reason,none\n"
                ),
                "factor_normalized_scores.csv": (
                    "stock_code,factor_name,score_role,score_group,raw_factor_value,"
                    "normalized_score,factor_weight,weighted_contribution,validation_status\n"
                    "A,return_20d,positive,momentum,0.2,90,1,90,PASS\n"
                ),
                "hard_filter_exclusions.csv": (
                    "as_of_date,source_run_id,index_code,stock_code,hard_filter_name,"
                    "factor_value,exclusion_reason\n"
                ),
                "validation_gate.csv": "factor_name,validation_status,reason\nreturn_20d,PASS,\n",
                "score_metadata.json": (
                    '{"as_of_date":"2026-01-02","source_run_id":"factor-run",'
                    '"index_code":"LOCAL","top_n":1}\n'
                ),
            },
        )
        backtest = _bundle(
            "backtest",
            "backtest-run",
            tmp_path / "backtest",
            {"metrics.csv": "total_return,max_drawdown,total_cost\n0.1,-0.02,1.0\n"},
        )
        event = _bundle(
            "event_study",
            "event-run",
            tmp_path / "event",
            {
                "event_summary.csv": (
                    "event_source,event_type,horizon,sample_count,mean_event_return,"
                    "median_event_return,mean_excess_return,win_rate,excess_win_rate\n"
                    "risk_events,pledge,5,3,0.01,0.01,0.0,0.6,0.5\n"
                )
            },
        )
        result = build_daily_report(
            connection,
            as_of_date="2026-01-02",
            source_run_id="factor-run",
            scan_bundle=scan,
            score_bundle=score,
            backtest_bundle=backtest,
            event_study_bundle=event,
            data_quality_gate=gate,
            repo_root=tmp_path,
            metadata={"run_id": "daily-run", "run_mode": "exploratory", "db_path": str(db_path)},
            watchlist_codes=["A", "B"],
        )
    finally:
        connection.close()

    assert "Daily Research Report" in result.markdown
    assert "Research Use Only" in result.markdown
    assert "Today Candidate Top N" in result.markdown
    assert "Validation Gate Summary" in result.markdown
    assert "Watchlist Summary" in result.markdown
    assert not result.daily_candidates.empty
    assert not result.daily_factor_contributions.empty
    assert not result.daily_validation_gate_summary.empty
    assert list(result.daily_watchlist_summary["stock_code"]) == ["A", "B"]
    assert bool(result.daily_watchlist_summary.iloc[0]["in_candidate_top_n"]) is True
    assert bool(result.daily_watchlist_summary.iloc[1]["in_candidate_top_n"]) is False

    paths = write_daily_report(result, tmp_path / "daily-output")
    for path in paths.values():
        assert path.exists()
    assert (tmp_path / "daily-output" / "daily_validation_gate_summary.csv").exists()
    assert (tmp_path / "daily-output" / "daily_watchlist_summary.csv").exists()
    metadata = (tmp_path / "daily-output" / "daily_metadata.json").read_text(encoding="utf-8")
    assert "daily-run" in metadata
