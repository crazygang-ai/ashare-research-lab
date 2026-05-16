from __future__ import annotations

from datetime import date, datetime
import json

import duckdb
import pytest

from ashare.storage.db import default_schema_path
from ashare.validation.event_study import run_event_study


INDEX_CODE = "LOCAL"


@pytest.fixture()
def event_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    _build_event_study_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_announcements_use_effective_date_type_filter_adjusted_close_and_benchmark(
    event_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = run_event_study(
        event_connection,
        event_source="announcements",
        event_types=["earnings_forecast"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        horizons=[1, 2],
        index_code=INDEX_CODE,
        benchmark="synthetic_equal_weight",
    )

    sample_ids = set(result.event_samples["event_id"])
    assert {"ann-a", "ann-a-dup", "ann-b", "ann-c-missing"}.issubset(sample_ids)
    assert "ann-before" not in sample_ids
    assert "ann-after" not in sample_ids
    assert "ann-buyback" not in sample_ids

    alpha_h1 = result.event_window_returns[
        (result.event_window_returns["event_id"] == "ann-a")
        & (result.event_window_returns["horizon"] == 1)
    ].iloc[0]
    beta_h1 = result.event_window_returns[
        (result.event_window_returns["event_id"] == "ann-b")
        & (result.event_window_returns["horizon"] == 1)
    ].iloc[0]
    skipped = result.event_samples[result.event_samples["event_id"] == "ann-c-missing"].iloc[0]

    assert alpha_h1["event_return"] == pytest.approx(0.1)
    assert alpha_h1["benchmark_return"] == pytest.approx(0.1)
    assert alpha_h1["excess_return"] == pytest.approx(0.0)
    assert beta_h1["event_return"] == pytest.approx(0.1)
    assert not bool(skipped["included"])
    assert skipped["skip_reason"] == "missing_event_date_price"


def test_risk_events_filter_by_effective_event_type(
    event_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = run_event_study(
        event_connection,
        event_source="risk_events",
        event_types=["pledge"],
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        horizons=[1],
        index_code=INDEX_CODE,
    )

    assert result.event_samples["event_id"].tolist() == ["risk-a"]
    assert len(result.event_window_returns) == 1


def test_synthetic_cap_weight_benchmark_is_supported(
    event_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = run_event_study(
        event_connection,
        event_source="announcements",
        event_types=["earnings_forecast"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        horizons=[1],
        index_code=INDEX_CODE,
        benchmark="synthetic_cap_weight",
    )

    assert result.event_window_returns["benchmark_return"].notna().all()


def test_duplicate_events_default_keep_all_and_deduplicate_option_keeps_first(
    event_connection: duckdb.DuckDBPyConnection,
) -> None:
    kept_all = run_event_study(
        event_connection,
        event_source="announcements",
        event_types=["earnings_forecast"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        horizons=[1],
        index_code=INDEX_CODE,
        deduplicate="none",
    )
    deduped = run_event_study(
        event_connection,
        event_source="announcements",
        event_types=["earnings_forecast"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        horizons=[1],
        index_code=INDEX_CODE,
        deduplicate="same-stock-date-type",
    )

    assert (
        len(
            kept_all.event_window_returns[
                kept_all.event_window_returns["stock_code"] == "000001.SZ"
            ]
        )
        == 2
    )
    alpha_samples = deduped.event_samples[deduped.event_samples["stock_code"] == "000001.SZ"]
    assert int(alpha_samples["included"].sum()) == 1
    assert "duplicate_same_stock_date_type" in set(alpha_samples["skip_reason"])
    assert (
        len(
            deduped.event_window_returns[
                deduped.event_window_returns["stock_code"] == "000001.SZ"
            ]
        )
        == 1
    )


def test_future_window_insufficient_skips_event(
    event_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = run_event_study(
        event_connection,
        event_source="announcements",
        event_types=["earnings_forecast"],
        start_date="2026-01-09",
        end_date="2026-01-09",
        horizons=[1, 5],
        index_code=INDEX_CODE,
    )

    sample = result.event_samples.iloc[0]
    assert sample["event_id"] == "ann-short"
    assert not bool(sample["included"])
    assert sample["skip_reason"] == "insufficient_future_window"
    assert sample["available_max_horizon"] == 0
    assert result.event_window_returns.empty


def test_empty_samples_return_empty_report_frames(
    event_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = run_event_study(
        event_connection,
        event_source="announcements",
        event_types=["not_a_fixture_type"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        horizons=[1],
        index_code=INDEX_CODE,
    )

    assert result.event_samples.empty
    assert result.event_window_returns.empty
    assert result.event_summary.empty
    assert "No PIT-visible event samples" in result.warnings[0]


def test_announcement_llm_results_construct_validation_events(
    event_connection: duckdb.DuckDBPyConnection,
) -> None:
    result = run_event_study(
        event_connection,
        event_source="announcement_llm_results",
        event_types=["llm_sentiment_positive", "llm_risk_detected"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        horizons=[1],
        index_code=INDEX_CODE,
        min_confidence=0.8,
    )

    assert set(result.event_samples["event_type"]) == {
        "llm_sentiment_positive",
        "llm_risk_detected",
    }
    assert len(result.event_window_returns) == 2


def _build_event_study_db(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(default_schema_path().read_text(encoding="utf-8"))
    open_dates = [
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    ]
    connection.executemany(
        "INSERT INTO trading_calendar (trade_date, is_open) VALUES (?, true)",
        [(value,) for value in open_dates],
    )
    connection.executemany(
        """
        INSERT INTO universe_members (
            index_code, stock_code, in_date, in_effective_date, source
        )
        VALUES (?, ?, '2020-01-01', '2020-01-01', 'fixture')
        """,
        [(INDEX_CODE, "000001.SZ"), (INDEX_CODE, "000002.SZ")],
    )
    connection.executemany(
        """
        INSERT INTO daily_prices (stock_code, trade_date, close, adj_factor, is_suspended)
        VALUES (?, ?, ?, ?, false)
        """,
        [
            ("000001.SZ", date(2026, 1, 2), 10.0, 2.0),
            ("000001.SZ", date(2026, 1, 5), 11.0, 2.0),
            ("000001.SZ", date(2026, 1, 6), 12.0, 2.0),
            ("000001.SZ", date(2026, 1, 7), 13.0, 2.0),
            ("000001.SZ", date(2026, 1, 8), 14.0, 2.0),
            ("000001.SZ", date(2026, 1, 9), 15.0, 2.0),
            ("000002.SZ", date(2026, 1, 2), 20.0, None),
            ("000002.SZ", date(2026, 1, 5), 22.0, None),
            ("000002.SZ", date(2026, 1, 6), 24.0, None),
            ("000002.SZ", date(2026, 1, 7), 26.0, None),
            ("000002.SZ", date(2026, 1, 8), 28.0, None),
            ("000002.SZ", date(2026, 1, 9), 30.0, None),
            ("000003.SZ", date(2026, 1, 5), 30.0, 1.0),
        ],
    )
    connection.executemany(
        """
        INSERT INTO valuation_daily (stock_code, trade_date, float_mv, total_mv, source)
        VALUES (?, ?, ?, ?, 'fixture')
        """,
        [
            ("000001.SZ", date(2026, 1, 2), 100.0, 120.0),
            ("000002.SZ", date(2026, 1, 2), 100.0, 120.0),
        ],
    )
    connection.executemany(
        """
        INSERT INTO announcements (
            announcement_id, source, source_tag, stock_code, title,
            announcement_type, publish_time, effective_date, url, raw_path, text_hash
        )
        VALUES (?, 'fixture', 'fixture', ?, ?, ?, ?, ?, NULL, NULL, NULL)
        """,
        [
            (
                "ann-before",
                "000001.SZ",
                "before",
                "earnings_forecast",
                datetime(2026, 1, 1, 8),
                date(2026, 1, 1),
            ),
            (
                "ann-a",
                "000001.SZ",
                "alpha forecast",
                "earnings_forecast",
                datetime(2026, 1, 1, 18),
                date(2026, 1, 2),
            ),
            (
                "ann-a-dup",
                "000001.SZ",
                "alpha forecast duplicate",
                "earnings_forecast",
                datetime(2026, 1, 1, 19),
                date(2026, 1, 2),
            ),
            (
                "ann-b",
                "000002.SZ",
                "beta forecast",
                "earnings_forecast",
                datetime(2026, 1, 1, 18),
                date(2026, 1, 2),
            ),
            (
                "ann-c-missing",
                "000003.SZ",
                "missing price",
                "earnings_forecast",
                datetime(2026, 1, 1, 18),
                date(2026, 1, 2),
            ),
            (
                "ann-buyback",
                "000001.SZ",
                "buyback",
                "buyback",
                datetime(2026, 1, 1, 18),
                date(2026, 1, 2),
            ),
            (
                "ann-short",
                "000001.SZ",
                "short window",
                "earnings_forecast",
                datetime(2026, 1, 8, 18),
                date(2026, 1, 9),
            ),
            (
                "ann-after",
                "000001.SZ",
                "after",
                "earnings_forecast",
                datetime(2026, 1, 10, 18),
                date(2026, 1, 12),
            ),
        ],
    )
    connection.executemany(
        """
        INSERT INTO risk_events (
            event_id, stock_code, event_type, event_date, publish_time,
            effective_date, payload_json, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?::JSON, 'fixture')
        """,
        [
            (
                "risk-a",
                "000001.SZ",
                "pledge",
                date(2026, 1, 1),
                datetime(2026, 1, 1, 18),
                date(2026, 1, 2),
                "{}",
            ),
            (
                "risk-b",
                "000002.SZ",
                "shareholder_reduce",
                date(2026, 1, 1),
                datetime(2026, 1, 1, 18),
                date(2026, 1, 2),
                "{}",
            ),
        ],
    )
    connection.execute(
        """
        INSERT INTO announcement_llm_results (
            parse_id, parse_run_id, announcement_id, source, source_tag, stock_code,
            announcement_type, schema_version, sentiment, summary, parsed_json,
            raw_response_json, prompt_hash, confidence, confidence_reasons, status,
            error, created_at
        )
        VALUES (
            'parse-b', 'parse-run', 'ann-b', 'fixture', 'fixture', '000002.SZ',
            'earnings_forecast', 'v1', 'positive', 'summary', ?::JSON,
            '{}'::JSON, 'prompt', 0.9, '[]'::JSON, 'success', NULL, '2026-01-02 10:00:00'
        )
        """,
        [json.dumps({"risks": [{"type": "risk"}], "catalysts": []})],
    )
