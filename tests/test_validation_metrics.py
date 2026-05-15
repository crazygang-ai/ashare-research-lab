from __future__ import annotations

from datetime import date
import math

import pandas as pd
import pytest

from ashare.validation.decay import aggregate_decay_curve
from ashare.validation.ic import calculate_rank_ic, summarize_ic
from ashare.validation.quantile_returns import calculate_group_returns


def test_rank_ic_uses_spearman_average_rank_and_orientation() -> None:
    frame = pd.DataFrame(
        {
            "stock_code": ["A", "B", "C", "D"],
            "factor_name": ["pe_ttm_percentile"] * 4,
            "trade_date": [date(2026, 1, 2)] * 4,
            "horizon": [5] * 4,
            "factor_value": [1.0, 2.0, 2.0, 4.0],
            "forward_return": [0.4, 0.1, 0.3, 0.2],
        }
    )

    result = calculate_rank_ic(
        frame,
        directions={"pe_ttm_percentile": "lower_is_better"},
        min_ic_observations=3,
    )

    expected = frame["factor_value"].rank(method="average").corr(
        frame["forward_return"].rank(method="average"),
        method="pearson",
    )
    assert result.iloc[0]["rank_ic"] == pytest.approx(expected)
    assert result.iloc[0]["oriented_rank_ic"] == pytest.approx(-expected)


def test_rank_ic_is_missing_for_small_or_constant_cross_sections() -> None:
    small = pd.DataFrame(
        {
            "stock_code": ["A", "B"],
            "factor_name": ["return_20d", "return_20d"],
            "trade_date": [date(2026, 1, 2)] * 2,
            "horizon": [5, 5],
            "factor_value": [1.0, 2.0],
            "forward_return": [0.1, 0.2],
        }
    )
    constant_factor = small.assign(stock_code=["C", "D"], factor_value=[1.0, 1.0])
    constant_return = small.assign(
        stock_code=["E", "F"],
        forward_return=[0.2, 0.2],
        trade_date=[date(2026, 1, 3)] * 2,
    )

    too_small = calculate_rank_ic(
        small,
        directions={"return_20d": "higher_is_better"},
        min_ic_observations=3,
    )
    no_factor_variance = calculate_rank_ic(
        constant_factor,
        directions={"return_20d": "higher_is_better"},
        min_ic_observations=2,
    )
    no_return_variance = calculate_rank_ic(
        constant_return,
        directions={"return_20d": "higher_is_better"},
        min_ic_observations=2,
    )

    assert math.isnan(too_small.iloc[0]["rank_ic"])
    assert math.isnan(no_factor_variance.iloc[0]["rank_ic"])
    assert math.isnan(no_return_variance.iloc[0]["rank_ic"])


def test_icir_uses_sample_standard_deviation_and_skips_boolean_orientation() -> None:
    rank_ic = pd.DataFrame(
        {
            "factor_name": ["return_20d", "return_20d", "is_st"],
            "horizon": [5, 5, 5],
            "trade_date": [date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 2)],
            "valid_n": [4, 4, 4],
            "rank_ic": [0.1, 0.3, 0.5],
            "oriented_rank_ic": [0.1, 0.3, float("nan")],
        }
    )

    summary = summarize_ic(rank_ic)
    return_summary = summary[summary["factor_name"] == "return_20d"].iloc[0]
    bool_summary = summary[summary["factor_name"] == "is_st"].iloc[0]

    assert return_summary["rank_ic_std"] == pytest.approx(pd.Series([0.1, 0.3]).std(ddof=1))
    assert return_summary["icir"] == pytest.approx(0.2 / pd.Series([0.1, 0.3]).std(ddof=1))
    assert math.isnan(bool_summary["icir"])
    assert bool_summary["valid_oriented_ic_dates"] == 0
    assert math.isnan(bool_summary["oriented_icir"])

    zero_std = summarize_ic(
        pd.DataFrame(
            {
                "factor_name": ["return_20d", "return_20d"],
                "horizon": [5, 5],
                "trade_date": [date(2026, 1, 2), date(2026, 1, 3)],
                "valid_n": [4, 4],
                "rank_ic": [0.2, 0.2],
                "oriented_rank_ic": [0.2, 0.2],
            }
        )
    ).iloc[0]
    assert math.isnan(zero_std["icir"])


def test_group_returns_follow_direction_and_stable_tie_break() -> None:
    base = pd.DataFrame(
        {
            "stock_code": ["B", "A", "C", "D"],
            "factor_name": ["return_20d"] * 4,
            "trade_date": [date(2026, 1, 2)] * 4,
            "horizon": [5] * 4,
            "factor_value": [1.0, 1.0, 3.0, 4.0],
            "forward_return": [0.2, 0.1, 0.3, 0.4],
        }
    )
    higher = calculate_group_returns(
        base,
        directions={"return_20d": "higher_is_better"},
        n_groups=2,
        min_group_size=1,
    ).iloc[0]
    lower = calculate_group_returns(
        base.assign(factor_name="pe_ttm_percentile"),
        directions={"pe_ttm_percentile": "lower_is_better"},
        n_groups=2,
        min_group_size=1,
    ).iloc[0]

    assert higher["bottom_return"] == pytest.approx(0.15)
    assert higher["top_return"] == pytest.approx(0.35)
    assert higher["long_short_return"] == pytest.approx(higher["top_minus_bottom_return"])
    assert lower["top_return"] == pytest.approx(0.15)
    assert lower["bottom_return"] == pytest.approx(0.35)

    tied = calculate_group_returns(
        base,
        directions={"return_20d": "higher_is_better"},
        n_groups=4,
        min_group_size=1,
    ).iloc[0]
    assert tied["bottom_return"] == pytest.approx(0.1)


def test_group_returns_skip_small_samples_and_boolean_filters() -> None:
    frame = pd.DataFrame(
        {
            "stock_code": ["A", "B", "C", "D"],
            "factor_name": ["is_st"] * 4,
            "trade_date": [date(2026, 1, 2)] * 4,
            "horizon": [5] * 4,
            "factor_value": [0.0, 1.0, 0.0, 1.0],
            "forward_return": [0.1, 0.2, 0.3, 0.4],
        }
    )

    small = calculate_group_returns(
        frame.assign(factor_name="return_20d"),
        directions={"return_20d": "higher_is_better"},
        n_groups=5,
        min_group_size=1,
    )
    boolean = calculate_group_returns(
        frame,
        directions={"is_st": "boolean_filter"},
        n_groups=2,
        min_group_size=1,
    )

    assert small.empty
    assert boolean.empty


def test_decay_curve_separates_valid_ic_and_group_dates() -> None:
    rank_ic = pd.DataFrame(
        {
            "factor_name": ["return_20d", "return_20d"],
            "horizon": [5, 5],
            "trade_date": [date(2026, 1, 2), date(2026, 1, 3)],
            "valid_n": [4, 4],
            "rank_ic": [0.1, 0.3],
            "oriented_rank_ic": [0.1, 0.3],
        }
    )
    group_returns = pd.DataFrame(
        {
            "factor_name": ["return_20d"],
            "horizon": [5],
            "trade_date": [date(2026, 1, 2)],
            "top_return": [0.4],
            "bottom_return": [0.1],
            "top_minus_bottom_return": [0.3],
            "long_short_return": [0.3],
            "valid_group_size": [2],
        }
    )

    decay = aggregate_decay_curve(rank_ic, group_returns).iloc[0]

    assert decay["valid_ic_dates"] == 2
    assert decay["valid_group_dates"] == 1
    assert decay["mean_rank_ic"] == pytest.approx(0.2)
    assert decay["mean_top_minus_bottom_return"] == pytest.approx(0.3)
