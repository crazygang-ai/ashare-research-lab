from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ashare.reports.factor_report import (
    render_factor_validation_markdown,
    write_factor_validation_report,
)
from ashare.validation.runner import FactorValidationResult


def _sample_result() -> FactorValidationResult:
    return FactorValidationResult(
        coverage=pd.DataFrame(
            [
                {
                    "factor_name": "return_20d",
                    "trade_date": "2026-01-02",
                    "universe_count": 2,
                    "valid_factor_count": 2,
                    "missing_count": 0,
                    "coverage": 1.0,
                    "missing_rate": 0.0,
                    "universe_source": "hard_filters",
                },
                {
                    "factor_name": "pe_ttm_percentile",
                    "trade_date": "2026-01-01",
                    "universe_count": 2,
                    "valid_factor_count": 1,
                    "missing_count": 1,
                    "coverage": 0.5,
                    "missing_rate": 0.5,
                    "universe_source": "hard_filters",
                },
            ]
        ),
        label_summary=pd.DataFrame(
            [
                {"horizon": 20, "valid_label_count": 6, "latest_usable_signal_date": "2026-01-02"},
                {"horizon": 5, "valid_label_count": 8, "latest_usable_signal_date": "2026-01-03"},
            ]
        ),
        rank_ic=pd.DataFrame(
            [
                {
                    "factor_name": "return_20d",
                    "trade_date": "2026-01-02",
                    "horizon": 20,
                    "valid_n": 3,
                    "rank_ic": 0.2,
                    "oriented_rank_ic": 0.2,
                },
                {
                    "factor_name": "return_20d",
                    "trade_date": "2026-01-01",
                    "horizon": 5,
                    "valid_n": 3,
                    "rank_ic": 0.3,
                    "oriented_rank_ic": 0.3,
                },
            ]
        ),
        ic_summary=pd.DataFrame(
            [
                {
                    "factor_name": "return_20d",
                    "horizon": 20,
                    "valid_ic_dates": 1,
                    "mean_rank_ic": 0.2,
                    "rank_ic_std": 0.0,
                    "icir": 0.0,
                    "valid_oriented_ic_dates": 1,
                    "mean_oriented_rank_ic": 0.2,
                    "oriented_rank_ic_std": 0.0,
                    "oriented_icir": 0.0,
                }
            ]
        ),
        group_returns=pd.DataFrame(
            [
                {
                    "factor_name": "return_20d",
                    "trade_date": "2026-01-02",
                    "horizon": 20,
                    "top_return": 0.1,
                    "bottom_return": -0.1,
                    "top_minus_bottom_return": 0.2,
                    "long_short_return": 0.2,
                    "valid_group_size": 1,
                }
            ]
        ),
        decay_curve=pd.DataFrame(
            [
                {
                    "factor_name": "return_20d",
                    "horizon": 20,
                    "valid_ic_dates": 1,
                    "valid_group_dates": 1,
                    "mean_rank_ic": 0.2,
                    "icir": 0.0,
                    "mean_oriented_rank_ic": 0.2,
                    "oriented_icir": 0.0,
                    "mean_top_return": 0.1,
                    "mean_bottom_return": -0.1,
                    "mean_top_minus_bottom_return": 0.2,
                    "mean_long_short_return": 0.2,
                }
            ]
        ),
        yearly_ic_summary=pd.DataFrame(
            [
                {
                    "factor_name": "return_20d",
                    "year": 2026,
                    "horizon": 20,
                    "valid_ic_dates": 1,
                    "valid_oriented_ic_dates": 1,
                    "mean_rank_ic": 0.2,
                    "mean_oriented_rank_ic": 0.2,
                    "oriented_icir": 0.0,
                    "positive_oriented_ic_ratio": 1.0,
                    "valid_group_dates": 1,
                    "mean_top_minus_bottom_label_return": 0.2,
                }
            ]
        ),
        warnings=("coverage fallback used", "Boolean hard filters are included"),
    )


def _metadata() -> dict[str, object]:
    return {
        "generated_at": "2026-01-03T12:00:00+08:00",
        "db_path": "tmp/ashare.duckdb",
        "source_run_id": "run1",
        "validation_from": "2026-01-01",
        "validation_to": "2026-01-03",
        "factors": ["return_20d", "pe_ttm_percentile"],
        "horizons": [5, 20],
        "n_groups": 5,
        "include_hard_filters": True,
        "validation_config_path": "configs/validation.yaml",
        "data_dictionary_path": "configs/data_dictionary.yaml",
    }


def test_render_factor_validation_markdown_contains_required_sections() -> None:
    text = render_factor_validation_markdown(_sample_result(), _metadata())

    assert "# Factor Validation Report" in text
    assert "2026-01-03T12:00:00+08:00" in text
    assert "tmp/ashare.duckdb" in text
    assert "source_run_id: run1" in text
    assert "Coverage And Missing Rate" in text
    assert "Rank IC And ICIR Summary" in text
    assert "Top And Bottom Group Returns" in text
    assert "Decay Curve" in text
    assert "Yearly IC Stability" in text
    assert "coverage fallback used" in text
    assert "forward return 是验证标签，不是交易收益" in text
    assert "本报告不包含综合评分" in text


def test_render_factor_validation_markdown_missing_metadata_fails_fast() -> None:
    metadata = _metadata()
    metadata.pop("generated_at")

    with pytest.raises(ValueError, match="generated_at"):
        render_factor_validation_markdown(_sample_result(), metadata)


def test_write_factor_validation_report_outputs_markdown_and_full_sorted_csvs(
    tmp_path: Path,
) -> None:
    paths = write_factor_validation_report(
        _sample_result(),
        tmp_path,
        _metadata(),
    )

    assert {path.name for path in paths.values()} == {
        "factor_validation_report.md",
        "coverage.csv",
        "label_summary.csv",
        "rank_ic.csv",
        "ic_summary.csv",
        "group_returns.csv",
        "decay_curve.csv",
        "yearly_ic_summary.csv",
    }
    coverage = pd.read_csv(tmp_path / "coverage.csv")
    assert list(coverage.columns) == [
        "factor_name",
        "trade_date",
        "universe_count",
        "valid_factor_count",
        "missing_count",
        "coverage",
        "missing_rate",
        "universe_source",
    ]
    assert len(coverage) == 2
    expected_coverage = coverage.sort_values(["factor_name", "trade_date"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(coverage.reset_index(drop=True), expected_coverage)

    rank_ic = pd.read_csv(tmp_path / "rank_ic.csv")
    expected_rank_ic = rank_ic.sort_values(["factor_name", "horizon", "trade_date"]).reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(rank_ic.reset_index(drop=True), expected_rank_ic)

    with pytest.raises(FileExistsError):
        write_factor_validation_report(_sample_result(), tmp_path, _metadata())
