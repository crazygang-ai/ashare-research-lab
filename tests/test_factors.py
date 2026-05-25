from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ashare.factors.calculator import SUPPORTED_FACTORS, calculate_factors_for_date
from ashare.factors.config import load_factor_config
from ashare.factors.store import write_factor_values
from ashare.fixtures.builder import INDEX_CODE, build_fixtures
from ashare.ingest.local import ingest_local
from ashare.pit.asof import query_daily_prices_as_of


@pytest.fixture()
def fixture_db_path(tmp_path: Path) -> Path:
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)
    ingest_local(input_dir=input_dir, db_path=db_path)
    return db_path


@pytest.fixture()
def connection(fixture_db_path: Path) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect(str(fixture_db_path))
    try:
        yield db
    finally:
        db.close()


def _value(factors: pd.DataFrame, stock_code: str, factor_name: str) -> float:
    rows = factors[(factors["stock_code"] == stock_code) & (factors["factor_name"] == factor_name)]
    assert len(rows) == 1
    return float(rows.iloc[0]["factor_value"])


def _has_row(factors: pd.DataFrame, stock_code: str, factor_name: str) -> bool:
    rows = factors[(factors["stock_code"] == stock_code) & (factors["factor_name"] == factor_name)]
    return not rows.empty


def _custom_config() -> dict[str, object]:
    return deepcopy(load_factor_config("configs/factors.yaml"))


def test_calculate_factors_for_date_returns_all_phase1a4_factors(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    factors = calculate_factors_for_date(connection, "2026-06-26", index_code=INDEX_CODE)

    assert set(SUPPORTED_FACTORS) - set(factors["factor_name"]) == {"industry_pe_ttm_percentile"}
    assert factors.attrs["universe_size"] == 4


def test_universe_selection_uses_index_members_or_pit_securities(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        INSERT INTO securities (
            stock_code, stock_name, exchange, list_date,
            delist_date, delist_publish_time, delist_effective_date
        )
        VALUES ('000099.SZ', 'Off Index', 'SZSE', DATE '2020-01-01', NULL, NULL, NULL)
        """
    )

    index_factors = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code=INDEX_CODE,
        factor_names=["is_suspended"],
    )
    all_security_factors = calculate_factors_for_date(
        connection,
        "2026-06-26",
        factor_names=["is_suspended"],
    )

    assert "000099.SZ" not in set(index_factors["stock_code"])
    assert _value(all_security_factors, "000099.SZ", "is_suspended") == 1.0


def test_include_delisted_controls_pit_securities_universe(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    default = calculate_factors_for_date(
        connection,
        "2026-06-26",
        factor_names=["is_delisted"],
    )
    include_delisted = calculate_factors_for_date(
        connection,
        "2026-06-26",
        factor_names=["is_delisted"],
        include_delisted=True,
    )

    assert "000003.SZ" not in set(default["stock_code"])
    assert _value(include_delisted, "000003.SZ", "is_delisted") == 1.0


def test_empty_universe_returns_empty_frame(connection: duckdb.DuckDBPyConnection) -> None:
    factors = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code="EMPTY_INDEX",
    )

    assert factors.empty
    assert factors.attrs["universe_size"] == 0


def test_return_20d_uses_adjusted_close_and_observation_shift(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    as_of = "2026-05-25"
    factors = calculate_factors_for_date(
        connection,
        as_of,
        factor_names=["return_20d"],
    )
    prices = query_daily_prices_as_of(connection, as_of, stock_code="000001.SZ")
    prices["trade_date"] = pd.to_datetime(prices["trade_date"]).dt.date
    current_index = prices.index[prices["trade_date"] == pd.Timestamp(as_of).date()][0]
    current = prices.loc[current_index]
    previous = prices.loc[current_index - 20]

    expected = (current["close"] * current["adj_factor"]) / (
        previous["close"] * previous["adj_factor"]
    ) - 1
    raw_close_return = current["close"] / previous["close"] - 1

    assert math.isclose(_value(factors, "000001.SZ", "return_20d"), expected)
    assert not math.isclose(expected, raw_close_return)


def test_return_60d_requires_observations_and_late_sample_writes(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    early = calculate_factors_for_date(
        connection,
        "2026-03-02",
        factor_names=["return_60d"],
    )
    late = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code=INDEX_CODE,
        factor_names=["return_60d"],
    )

    assert early.empty
    assert set(late["stock_code"]) == {"000001.SZ", "000002.SZ", "000004.SZ", "000005.SZ"}


def test_above_ma60_matches_latest_60_adjusted_observations(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    as_of = "2026-06-26"
    factors = calculate_factors_for_date(
        connection,
        as_of,
        index_code=INDEX_CODE,
        factor_names=["above_ma60"],
    )
    prices = query_daily_prices_as_of(connection, as_of, stock_code="000001.SZ")
    prices["adjusted_close"] = prices["close"] * prices["adj_factor"].fillna(1.0)
    latest = prices.tail(60)
    expected = 1.0 if latest.iloc[-1]["adjusted_close"] > latest["adjusted_close"].mean() else 0.0

    assert _value(factors, "000001.SZ", "above_ma60") == expected


def test_suspended_price_rows_count_as_momentum_observations(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    factors = calculate_factors_for_date(
        connection,
        "2026-02-02",
        factor_names=["return_20d"],
    )

    assert _has_row(factors, "000004.SZ", "return_20d")


def test_low_liquidity_uses_configured_threshold(connection: duckdb.DuckDBPyConnection) -> None:
    default = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code=INDEX_CODE,
        factor_names=["low_liquidity"],
    )
    config = _custom_config()
    config["hard_filters"]["low_liquidity"]["params"]["min_avg_amount"] = 1.0
    custom = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code=INDEX_CODE,
        factor_names=["low_liquidity"],
        factor_config=config,
    )

    assert _value(default, "000001.SZ", "low_liquidity") == 1.0
    assert _value(custom, "000001.SZ", "low_liquidity") == 0.0


def test_price_risk_and_amount_stability_factors_use_pit_observations(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    as_of = "2026-06-26"
    factors = calculate_factors_for_date(
        connection,
        as_of,
        index_code=INDEX_CODE,
        factor_names=["volatility_20d", "max_drawdown_60d", "amount_cv_20d"],
    )
    prices = query_daily_prices_as_of(connection, as_of, stock_code="000001.SZ")
    prices["adjusted_close"] = prices["close"] * prices["adj_factor"].fillna(1.0)

    latest_return_window = prices.tail(21)
    expected_volatility = latest_return_window["adjusted_close"].pct_change().dropna().std(ddof=0)
    latest_drawdown_window = prices.tail(60)
    drawdowns = (
        1.0
        - latest_drawdown_window["adjusted_close"]
        / latest_drawdown_window["adjusted_close"].cummax()
    )
    latest_amount_window = prices.tail(20)
    expected_amount_cv = (
        latest_amount_window["amount"].std(ddof=0) / latest_amount_window["amount"].mean()
    )

    assert math.isclose(_value(factors, "000001.SZ", "volatility_20d"), expected_volatility)
    assert math.isclose(_value(factors, "000001.SZ", "max_drawdown_60d"), drawdowns.max())
    assert math.isclose(_value(factors, "000001.SZ", "amount_cv_20d"), expected_amount_cv)


def test_industry_pe_percentile_uses_current_pit_industry_cross_section(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        UPDATE industry_classifications
        SET industry_l1 = 'Financials', industry_l2 = 'Banking'
        WHERE stock_code = '000002.SZ'
        """
    )

    factors = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code=INDEX_CODE,
        factor_names=["industry_pe_ttm_percentile"],
    )

    assert _value(factors, "000001.SZ", "industry_pe_ttm_percentile") == 0.0
    assert _value(factors, "000002.SZ", "industry_pe_ttm_percentile") == 1.0
    assert not _has_row(factors, "000004.SZ", "industry_pe_ttm_percentile")


def test_industry_pe_percentile_filters_industry_classification_by_data_source(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        UPDATE industry_classifications
        SET industry_l1 = 'Financials', industry_l2 = 'Banking'
        WHERE stock_code = '000002.SZ'
          AND source = 'fixture'
        """
    )
    connection.execute(
        """
        INSERT INTO industry_classifications (
            stock_code, industry_standard, industry_l1, industry_l2,
            in_date, out_date, in_publish_time, in_effective_date,
            out_publish_time, out_effective_date, version, source
        )
        VALUES (
            '000002.SZ', 'fixture_l1_l2', 'Consumer', 'Durables',
            DATE '2026-06-01', NULL, TIMESTAMP '2026-06-01 18:00:00', DATE '2026-06-02',
            NULL, NULL, '2026Q2', 'other-source'
        )
        """
    )

    factors = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code=INDEX_CODE,
        factor_names=["industry_pe_ttm_percentile"],
        data_source="fixture",
    )

    assert _value(factors, "000001.SZ", "industry_pe_ttm_percentile") == 0.0
    assert _value(factors, "000002.SZ", "industry_pe_ttm_percentile") == 1.0


def test_is_st_respects_interval_effective_dates(connection: duckdb.DuckDBPyConnection) -> None:
    expectations = {
        "2026-01-20": 0.0,
        "2026-01-21": 1.0,
        "2026-02-17": 1.0,
        "2026-02-18": 0.0,
    }

    for as_of, expected in expectations.items():
        factors = calculate_factors_for_date(connection, as_of, factor_names=["is_st"])
        assert _value(factors, "000002.SZ", "is_st") == expected


def test_is_suspended_covers_true_suspension_and_missing_price_row(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    suspended = calculate_factors_for_date(
        connection,
        "2026-01-26",
        factor_names=["is_suspended"],
    )
    missing_price = calculate_factors_for_date(
        connection,
        "2026-05-11",
        index_code=INDEX_CODE,
        factor_names=["is_suspended"],
    )

    assert _value(suspended, "000004.SZ", "is_suspended") == 1.0
    assert _value(missing_price, "000005.SZ", "is_suspended") == 1.0


def test_is_suspended_treats_null_flag_as_not_suspended(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        UPDATE daily_prices
        SET is_suspended = NULL
        WHERE stock_code = '000001.SZ' AND trade_date = DATE '2026-01-05'
        """
    )

    factors = calculate_factors_for_date(
        connection,
        "2026-01-05",
        factor_names=["is_suspended"],
    )

    assert _value(factors, "000001.SZ", "is_suspended") == 0.0


def test_is_delisted_respects_publish_effective_and_delist_dates(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before_visible = calculate_factors_for_date(
        connection,
        "2026-03-02",
        factor_names=["is_delisted"],
        include_delisted=True,
    )
    visible_before_delist = calculate_factors_for_date(
        connection,
        "2026-03-03",
        factor_names=["is_delisted"],
        include_delisted=True,
    )
    on_delist = calculate_factors_for_date(
        connection,
        "2026-03-06",
        factor_names=["is_delisted"],
        include_delisted=True,
    )

    assert _value(before_visible, "000003.SZ", "is_delisted") == 0.0
    assert _value(visible_before_delist, "000003.SZ", "is_delisted") == 0.0
    assert _value(on_delist, "000003.SZ", "is_delisted") == 1.0


def test_hard_filters_write_binary_rows_for_every_universe_stock(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    factors = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code=INDEX_CODE,
        factor_names=["is_st", "is_suspended", "is_delisted"],
    )

    assert factors.groupby("factor_name").size().to_dict() == {
        "is_delisted": 4,
        "is_st": 4,
        "is_suspended": 4,
    }
    assert set(factors["factor_value"]) <= {0.0, 1.0}


def test_valuation_percentiles_use_pit_rows_and_average_rank(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        INSERT INTO valuation_daily
        VALUES ('000001.SZ', DATE '2026-06-29', 0.01, 0.01, 2.0, 0.01, 1.0, 1.0, 'future')
        """
    )

    factors = calculate_factors_for_date(
        connection,
        "2026-06-26",
        factor_names=["pe_ttm_percentile", "pb_percentile"],
    )

    assert _value(factors, "000001.SZ", "pe_ttm_percentile") == 1.0
    assert _value(factors, "000001.SZ", "pb_percentile") == 0.5


def test_valuation_min_observations_can_be_overridden(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    default = calculate_factors_for_date(
        connection,
        "2026-01-09",
        factor_names=["pe_ttm_percentile", "pb_percentile"],
    )
    config = _custom_config()
    config["factors"]["pe_ttm_percentile"]["params"]["min_observations"] = 5
    config["factors"]["pb_percentile"]["params"]["min_observations"] = 5
    custom = calculate_factors_for_date(
        connection,
        "2026-01-09",
        factor_names=["pe_ttm_percentile", "pb_percentile"],
        factor_config=config,
    )

    assert default.empty
    assert _value(custom, "000001.SZ", "pe_ttm_percentile") == 1.0
    assert _value(custom, "000001.SZ", "pb_percentile") == 0.5


def test_financial_factors_use_effective_date_and_latest_visible_revision(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    before_effective = calculate_factors_for_date(
        connection,
        "2026-04-13",
        factor_names=["revenue_yoy", "profit_yoy"],
    )
    initial = calculate_factors_for_date(
        connection,
        "2026-04-14",
        factor_names=["revenue_yoy", "profit_yoy"],
    )
    revised = calculate_factors_for_date(
        connection,
        "2026-04-28",
        factor_names=["revenue_yoy", "profit_yoy"],
    )

    assert not _has_row(before_effective, "000001.SZ", "revenue_yoy")
    assert math.isclose(_value(initial, "000001.SZ", "revenue_yoy"), 0.3)
    assert math.isclose(_value(initial, "000001.SZ", "profit_yoy"), 0.5)
    assert math.isclose(_value(revised, "000001.SZ", "revenue_yoy"), 0.4)
    assert math.isclose(_value(revised, "000001.SZ", "profit_yoy"), 0.6)


def test_operating_cashflow_to_profit_uses_latest_visible_report(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    annual_report = calculate_factors_for_date(
        connection,
        "2026-04-13",
        factor_names=["operating_cashflow_to_profit"],
    )
    visible = calculate_factors_for_date(
        connection,
        "2026-04-14",
        factor_names=["operating_cashflow_to_profit"],
    )

    assert math.isclose(
        _value(annual_report, "000001.SZ", "operating_cashflow_to_profit"),
        95.0 / 120.0,
    )
    assert math.isclose(_value(visible, "000001.SZ", "operating_cashflow_to_profit"), 0.9)


def test_financial_factors_skip_invalid_previous_year_bases(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    factors = calculate_factors_for_date(
        connection,
        "2026-06-26",
        factor_names=["revenue_yoy", "profit_yoy"],
    )

    assert not _has_row(factors, "000004.SZ", "revenue_yoy")
    assert _has_row(factors, "000004.SZ", "profit_yoy")
    assert _has_row(factors, "000005.SZ", "revenue_yoy")
    assert not _has_row(factors, "000005.SZ", "profit_yoy")


def test_unknown_factor_names_raise(connection: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError, match="Unsupported factor"):
        calculate_factors_for_date(connection, "2026-06-26", factor_names=["not_real"])


def test_single_date_requires_open_trading_day(connection: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError, match="not a trading day"):
        calculate_factors_for_date(connection, "2026-06-27")


def test_write_factor_values_is_idempotent_and_partial_replace_is_scoped(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    full = calculate_factors_for_date(connection, "2026-06-26", index_code=INDEX_CODE)
    first_count = write_factor_values(connection, full, source_run_id="test-run", replace=True)
    second_count = write_factor_values(connection, full, source_run_id="test-run", replace=True)
    stored_count = connection.execute(
        "SELECT COUNT(*) FROM factor_values WHERE source_run_id = 'test-run'"
    ).fetchone()[0]

    subset = calculate_factors_for_date(
        connection,
        "2026-06-26",
        index_code=INDEX_CODE,
        factor_names=["return_20d"],
    )
    partial_count = write_factor_values(connection, subset, source_run_id="test-run", replace=True)
    after_partial = connection.execute(
        "SELECT COUNT(*) FROM factor_values WHERE source_run_id = 'test-run'"
    ).fetchone()[0]
    factor_counts = dict(
        connection.execute(
            """
            SELECT factor_name, COUNT(*)
            FROM factor_values
            WHERE source_run_id = 'test-run'
            GROUP BY factor_name
            """
        ).fetchall()
    )

    assert first_count == len(full)
    assert second_count == len(full)
    assert stored_count == len(full)
    assert partial_count == len(subset)
    assert after_partial == len(full)
    assert factor_counts["return_20d"] == len(subset)
    assert factor_counts["profit_yoy"] > 0
