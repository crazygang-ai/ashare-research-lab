from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from ashare.reports.run_summary import ArtifactBundle
from ashare.reports.stock_report import build_stock_report, write_stock_report
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


def test_stock_report_renders_single_stock_review(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.duckdb"
    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            INSERT INTO securities (stock_code, stock_name, exchange, list_date)
            VALUES ('A', 'Alpha', 'SSE', '2020-01-01')
            """
        )
        connection.execute(
            """
            INSERT INTO industry_classifications (
                stock_code, industry_standard, industry_l1, industry_l2,
                in_date, in_effective_date, version, source
            )
            VALUES ('A', 'CSRC', 'Tech', 'Software', '2020-01-01', '2020-01-01', 'v1', 'fixture')
            """
        )
        connection.execute(
            """
            INSERT INTO universe_members (index_code, stock_code, in_date, in_effective_date, source)
            VALUES ('LOCAL', 'A', '2020-01-01', '2020-01-01', 'fixture')
            """
        )
        rows = [
            ("A", date(2026, 1, 2), "return_20d", 0.2, date(2026, 1, 2), "factor-run"),
            ("A", date(2026, 1, 2), "revenue_yoy", 0.1, date(2026, 1, 2), "factor-run"),
            ("A", date(2026, 1, 2), "pe_ttm_percentile", 0.3, date(2026, 1, 2), "factor-run"),
            ("A", date(2026, 1, 2), "is_st", 0.0, date(2026, 1, 2), "factor-run"),
            ("A", date(2026, 1, 2), "is_suspended", 0.0, date(2026, 1, 2), "factor-run"),
            ("A", date(2026, 1, 2), "is_delisted", 0.0, date(2026, 1, 2), "factor-run"),
            ("A", date(2026, 1, 2), "low_liquidity", 0.0, date(2026, 1, 2), "factor-run"),
        ]
        connection.executemany(
            """
            INSERT INTO factor_values (
                stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
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
        score = _bundle(
            "scoring",
            "score-run",
            tmp_path / "score",
            {
                "scored_candidates.csv": (
                    "rank,stock_code,total_score,hard_filter_passed,selection_reason,risk_tips\n"
                    "1,A,88,true,score reason,none\n"
                ),
                "score_breakdown.csv": (
                    "stock_code,score_group,weighted_contribution,group_score,missing_factor_count\n"
                    "A,momentum,45,90,0\n"
                ),
                "factor_normalized_scores.csv": (
                    "stock_code,factor_name,score_group,raw_factor_value,normalized_score,"
                    "weighted_contribution,validation_status\n"
                    "A,return_20d,momentum,0.2,90,45,PASS\n"
                ),
                "hard_filter_exclusions.csv": (
                    "as_of_date,source_run_id,index_code,stock_code,hard_filter_name,"
                    "factor_value,exclusion_reason\n"
                ),
                "score_metadata.json": '{"index_code":"LOCAL"}\n',
            },
        )
        result = build_stock_report(
            connection,
            code="A",
            as_of_date="2026-01-02",
            source_run_id="factor-run",
            score_bundle=score,
            metadata={"run_id": "stock-run", "run_mode": "exploratory", "db_path": str(db_path)},
        )
    finally:
        connection.close()

    assert "Stock Research Report" in result.markdown
    assert "Research Use Only" in result.markdown
    assert result.metadata["stock_name"] == "Alpha"
    assert result.metadata["in_target_universe"] is True
    assert not result.stock_factor_values.empty
    assert not result.stock_score_breakdown.empty

    paths = write_stock_report(result, tmp_path / "stock-output")
    for path in paths.values():
        assert path.exists()
