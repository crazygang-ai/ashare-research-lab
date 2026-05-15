from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ashare.reports.candidate_report import render_candidate_markdown, write_candidate_report
from ashare.scan.candidates import (
    HARD_FILTER_NAMES,
    NO_RISK_TEXT,
    CandidateScanResult,
    scan_candidates,
)
from ashare.storage.db import default_schema_path


DATA_DICTIONARY = {
    "factors": {
        "above_ma60": {"type": "factor", "direction": "higher_is_better"},
        "pe_ttm_percentile": {"type": "factor", "direction": "lower_is_better"},
        "pb_percentile": {"type": "factor", "direction": "lower_is_better"},
        "return_20d": {"type": "factor", "direction": "higher_is_better"},
        "return_60d": {"type": "factor", "direction": "higher_is_better"},
        "revenue_yoy": {"type": "factor", "direction": "higher_is_better"},
        "is_st": {"type": "hard_filter", "direction": "boolean_filter"},
        "is_suspended": {"type": "hard_filter", "direction": "boolean_filter"},
        "is_delisted": {"type": "hard_filter", "direction": "boolean_filter"},
        "low_liquidity": {"type": "hard_filter", "direction": "boolean_filter"},
    }
}


@pytest.fixture()
def scan_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    connection.executemany(
        """
        INSERT INTO securities (stock_code, stock_name, exchange, list_date)
        VALUES (?, ?, 'SSE', ?)
        """,
        [
            ("A", "Alpha", date(2020, 1, 1)),
            ("B", "Beta", date(2020, 1, 1)),
            ("C", "Gamma", date(2020, 1, 1)),
            ("D", "Delta", date(2020, 1, 1)),
            ("E", "Epsilon", date(2020, 1, 1)),
            ("G", "NoSort", date(2020, 1, 1)),
        ],
    )
    connection.executemany(
        """
        INSERT INTO industry_classifications (
            stock_code, industry_standard, industry_l1, industry_l2, in_date, version, source
        )
        VALUES (?, 'fixture', ?, ?, ?, 'v1', 'fixture')
        """,
        [
            ("A", "Tech", "Software", date(2020, 1, 1)),
            ("B", "Tech", "Hardware", date(2020, 1, 1)),
            ("C", "Finance", "Broker", date(2020, 1, 1)),
        ],
    )

    rows: list[tuple[str, date, str, float, date, str]] = []

    def add(stock_code: str, factor_name: str, factor_value: float, run_id: str = "scan-run") -> None:
        rows.append((stock_code, date(2026, 1, 2), factor_name, factor_value, date(2026, 1, 2), run_id))

    for stock_code in ["A", "B", "C", "D", "E", "G"]:
        if stock_code != "E":
            add(stock_code, "is_st", 0.0)
        add(stock_code, "is_suspended", 0.0)
        add(stock_code, "is_delisted", 0.0)
        if stock_code != "D":
            add(stock_code, "low_liquidity", 0.0)

    add("A", "return_20d", 0.2)
    add("A", "return_60d", 0.1)
    add("A", "pe_ttm_percentile", 0.7)
    add("A", "pb_percentile", 0.7)
    add("A", "above_ma60", 1.0)
    add("A", "revenue_yoy", 0.2)

    add("B", "return_20d", 0.2)
    add("B", "return_60d", -0.2)
    add("B", "pe_ttm_percentile", 0.9)
    add("B", "pb_percentile", 0.9)
    add("B", "above_ma60", 0.0)
    add("B", "revenue_yoy", 0.1)

    add("C", "return_20d", -0.1)
    add("C", "return_60d", -0.05)
    add("C", "pe_ttm_percentile", 0.5)
    add("C", "pb_percentile", 0.5)

    add("D", "return_20d", 1.0)
    add("E", "return_20d", 0.8)
    rows.append(("E", date(2026, 1, 2), "is_st", 1.0, date(2026, 1, 2), "scan-run"))
    add("G", "pe_ttm_percentile", 0.1)

    rows.extend(
        [
            ("Z", date(2026, 1, 2), "return_20d", 9.0, date(2026, 1, 2), "other-run"),
            ("Y", date(2026, 1, 2), "return_20d", 9.0, date(2026, 1, 1), "scan-run"),
            ("F", date(2026, 1, 2), "return_20d", 0.4, date(2026, 1, 2), "filtered-run"),
            ("F", date(2026, 1, 2), "is_st", 1.0, date(2026, 1, 2), "filtered-run"),
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
    try:
        yield connection
    finally:
        connection.close()


def _candidate_metadata(candidates: pd.DataFrame) -> dict[str, object]:
    factor_names = [
        column.removeprefix("factor__")
        for column in candidates.columns
        if column.startswith("factor__")
    ]
    return {
        "generated_at": "2026-01-02T12:00:00+08:00",
        "db_path": "tmp/ashare.duckdb",
        "source_run_id": "scan-run",
        "as_of_date": "2026-01-02",
        "sort_factor": "return_20d",
        "sort_factor_direction": "higher_is_better",
        "top_n": 3,
        "factor_names": factor_names,
        "hard_filter_names": HARD_FILTER_NAMES,
        "data_dictionary_path": "configs/data_dictionary.yaml",
    }


def test_scan_candidates_filters_inputs_hard_filters_and_sorts_with_tie_breaker(
    scan_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = scan_candidates(
        scan_connection,
        as_of_date="2026-01-02",
        source_run_id="scan-run",
        sort_factor="return_20d",
        factor_names=["return_20d", "pe_ttm_percentile", "above_ma60"],
        top_n=3,
        data_dictionary=DATA_DICTIONARY,
    )

    candidates = result.candidates
    assert candidates["stock_code"].tolist() == ["A", "B", "C"]
    assert candidates["rank"].tolist() == [1, 2, 3]
    assert "D" not in set(candidates["stock_code"])
    assert "E" not in set(candidates["stock_code"])
    assert "G" not in set(candidates["stock_code"])
    assert candidates["selection_reason"].str.contains("return_20d").all()
    assert candidates["selection_reason"].str.contains("higher_is_better").all()
    assert candidates["selection_reason"].str.contains("硬过滤均通过").all()
    assert candidates.loc[0, "risk_tips"] == NO_RISK_TEXT
    assert "估值处于自身历史高位" in candidates.loc[1, "risk_tips"]
    assert "PB 处于自身历史高位" in candidates.loc[1, "risk_tips"]
    assert "20 日动量为负" in candidates.loc[2, "risk_tips"]
    assert "展示因子缺失：above_ma60" in candidates.loc[2, "risk_tips"]
    assert "价格低于 60 日均线" not in candidates.loc[2, "risk_tips"]


def test_scan_candidates_lower_is_better_sort_and_default_factor_order(
    scan_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = scan_candidates(
        scan_connection,
        as_of_date=date(2026, 1, 2),
        source_run_id="scan-run",
        sort_factor="pe_ttm_percentile",
        top_n=3,
        data_dictionary=DATA_DICTIONARY,
    )

    assert result.candidates["stock_code"].tolist() == ["G", "C", "A"]
    factor_columns = [column for column in result.candidates.columns if column.startswith("factor__")]
    assert factor_columns[0] == "factor__pe_ttm_percentile"
    assert "score" not in result.candidates.columns
    assert "total_score" not in result.candidates.columns
    assert "composite_score" not in result.candidates.columns


def test_scan_candidates_rejects_duplicate_keys(scan_connection: duckdb.DuckDBPyConnection) -> None:
    duplicate_rows = []
    for index in range(6):
        duplicate_rows.extend(
            [
                (f"DUP{index}", date(2026, 1, 2), "return_20d", 1.0, date(2026, 1, 2), "dup-run"),
                (f"DUP{index}", date(2026, 1, 2), "return_20d", 2.0, date(2026, 1, 2), "dup-run"),
            ]
        )
    scan_connection.executemany(
        """
        INSERT INTO factor_values (
            stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        duplicate_rows,
    )

    with pytest.raises(ValueError) as excinfo:
        scan_candidates(
            scan_connection,
            as_of_date="2026-01-02",
            source_run_id="dup-run",
            sort_factor="return_20d",
            data_dictionary=DATA_DICTIONARY,
        )

    message = str(excinfo.value)
    assert "Duplicate factor_values rows" in message
    assert "(source_run_id, stock_code, trade_date, as_of_date, factor_name)" in message
    assert message.count("count=") == 5


@pytest.mark.parametrize(
    ("sort_factor", "factor_names", "message"),
    [
        ("is_st", None, "type: factor"),
        ("return_20d", ["is_st"], "type: factor"),
        ("unknown_factor", None, "Unknown factor"),
        ("return_20d", ["unknown_factor"], "Unknown factor"),
    ],
)
def test_scan_candidates_rejects_invalid_factor_names(
    scan_connection: duckdb.DuckDBPyConnection,
    sort_factor: str,
    factor_names: list[str] | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        scan_candidates(
            scan_connection,
            as_of_date="2026-01-02",
            source_run_id="scan-run",
            sort_factor=sort_factor,
            factor_names=factor_names,
            data_dictionary=DATA_DICTIONARY,
        )


def test_scan_candidates_empty_input_and_empty_candidates_semantics(
    scan_connection: duckdb.DuckDBPyConnection,
) -> None:
    with pytest.raises(ValueError, match="No scanable factor_values input"):
        scan_candidates(
            scan_connection,
            as_of_date="2026-01-02",
            source_run_id="missing-run",
            sort_factor="return_20d",
            data_dictionary=DATA_DICTIONARY,
        )

    result = scan_candidates(
        scan_connection,
        as_of_date="2026-01-02",
        source_run_id="filtered-run",
        sort_factor="return_20d",
        factor_names=["return_20d"],
        data_dictionary=DATA_DICTIONARY,
    )
    assert result.candidates.empty
    assert list(result.candidates.columns) == [
        "rank",
        "stock_code",
        "stock_name",
        "industry_l1",
        "industry_l2",
        "as_of_date",
        "source_run_id",
        "sort_factor",
        "sort_factor_value",
        "factor__return_20d",
        "hard_filter__is_st",
        "hard_filter__is_suspended",
        "hard_filter__is_delisted",
        "hard_filter__low_liquidity",
        "selection_reason",
        "risk_tips",
    ]
    assert result.warnings


def test_candidate_markdown_and_csv_report(tmp_path: Path, scan_connection: duckdb.DuckDBPyConnection) -> None:
    result = scan_candidates(
        scan_connection,
        as_of_date="2026-01-02",
        source_run_id="scan-run",
        sort_factor="return_20d",
        factor_names=["return_20d", "pe_ttm_percentile"],
        top_n=2,
        data_dictionary=DATA_DICTIONARY,
    )
    metadata = _candidate_metadata(result.candidates)
    metadata["top_n"] = 2

    markdown = render_candidate_markdown(result, metadata)
    assert "Top" in markdown or "top_n" in markdown
    assert "因子分项" in markdown or "Factor Details" in markdown
    assert "selection_reason" in markdown
    assert "risk_tips" in markdown
    assert "candidate list is for research only" in markdown
    assert "候选清单未做综合评分" in markdown
    assert "候选清单未做组合回测" in markdown

    bad_metadata = dict(metadata)
    bad_metadata.pop("generated_at")
    with pytest.raises(ValueError, match="generated_at"):
        render_candidate_markdown(result, bad_metadata)

    paths = write_candidate_report(result, tmp_path, metadata)
    assert (tmp_path / "candidate_list.md").exists()
    assert (tmp_path / "candidates.csv").exists()
    candidates = pd.read_csv(paths["csv"])
    assert candidates["rank"].tolist() == sorted(candidates["rank"].tolist())
    assert "score" not in candidates.columns

    with pytest.raises(FileExistsError):
        write_candidate_report(result, tmp_path, metadata)


def test_empty_candidate_report_keeps_headers(tmp_path: Path) -> None:
    result = CandidateScanResult(
        candidates=pd.DataFrame(
            columns=[
                "rank",
                "stock_code",
                "stock_name",
                "industry_l1",
                "industry_l2",
                "as_of_date",
                "source_run_id",
                "sort_factor",
                "sort_factor_value",
                "factor__return_20d",
                "hard_filter__is_st",
                "hard_filter__is_suspended",
                "hard_filter__is_delisted",
                "hard_filter__low_liquidity",
                "selection_reason",
                "risk_tips",
            ]
        ),
        warnings=("empty",),
    )
    metadata = _candidate_metadata(result.candidates)
    write_candidate_report(result, tmp_path, metadata)

    text = (tmp_path / "candidate_list.md").read_text(encoding="utf-8")
    csv_header = (tmp_path / "candidates.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "empty" in text
    assert "candidate list is for research only" in text
    assert csv_header.startswith("rank,stock_code,stock_name")
