import pandas as pd
import pytest

from ashare.ingest.contracts import (
    FieldValidationError,
    normalize_dataset,
    normalize_stock_code,
    validate_dataset,
)


def _valid_daily_prices() -> pd.DataFrame:
    return normalize_dataset(
        "daily_prices",
        pd.DataFrame(
            {
                "股票代码": ["000001"],
                "日期": ["2026-03-30"],
                "开盘": [10.0],
                "最高": [10.5],
                "最低": [9.8],
                "收盘": [10.2],
                "成交量": [1000],
                "成交额": [10200.0],
            }
        ),
    )


def test_normalize_stock_code_and_chinese_daily_price_columns() -> None:
    frame = _valid_daily_prices()

    assert normalize_stock_code("sz000001") == "000001.SZ"
    assert frame.loc[0, "stock_code"] == "000001.SZ"
    assert frame.loc[0, "trade_date"].isoformat() == "2026-03-30"
    assert "unexpected" not in frame.columns


def test_normalize_dataset_coalesces_duplicate_alias_columns() -> None:
    frame = normalize_dataset(
        "universe_members",
        pd.DataFrame(
            {
                "指数代码": ["000300"],
                "index_code": [pd.NA],
                "成分券代码": ["002594"],
                "stock_code": [pd.NA],
                "纳入日期": ["2026-05-22"],
                "in_effective_date": ["2026-05-22"],
                "source": ["akshare"],
                "source_tag": ["akshare"],
                "universe_kind": ["current_snapshot"],
            }
        ),
    )

    assert frame.columns.tolist().count("index_code") == 1
    assert frame.columns.tolist().count("stock_code") == 1
    assert frame.loc[0, "index_code"] == "000300.SH"
    assert frame.loc[0, "stock_code"] == "002594.SZ"


def test_normalize_dataset_coalesces_distinct_aliases_for_same_field() -> None:
    frame = normalize_dataset(
        "daily_prices",
        pd.DataFrame(
            {
                "股票代码": ["000001", pd.NA],
                "stock_code": [pd.NA, "002594.SZ"],
                "日期": ["2026-01-02", pd.NA],
                "date": [pd.NA, "2026-01-02"],
                "开盘": [10.0, pd.NA],
                "open": [pd.NA, 20.0],
                "最高": [10.5, pd.NA],
                "high": [pd.NA, 20.5],
                "最低": [9.8, pd.NA],
                "low": [pd.NA, 19.8],
                "收盘": [10.2, pd.NA],
                "close": [pd.NA, 20.2],
                "成交量": [1000.0, pd.NA],
                "volume": [pd.NA, 2000.0],
                "成交额": [10200.0, pd.NA],
                "amount": [pd.NA, 40400.0],
            }
        ),
    )

    assert frame["stock_code"].tolist() == ["000001.SZ", "002594.SZ"]
    assert frame["trade_date"].tolist() == [pd.Timestamp("2026-01-02").date()] * 2
    assert frame["close"].tolist() == [10.2, 20.2]


def test_validate_dataset_missing_required_columns_fails() -> None:
    frame = pd.DataFrame({"stock_code": ["000001.SZ"]})

    with pytest.raises(FieldValidationError) as excinfo:
        validate_dataset("daily_prices", frame)

    assert "missing required columns" in str(excinfo.value)


def test_validate_dataset_duplicate_key_fails() -> None:
    frame = pd.concat([_valid_daily_prices(), _valid_daily_prices()], ignore_index=True)

    with pytest.raises(FieldValidationError) as excinfo:
        validate_dataset("daily_prices", frame)

    assert "duplicate key" in str(excinfo.value)


def test_validate_daily_price_consistency_fails() -> None:
    frame = _valid_daily_prices()
    frame.loc[0, "high"] = 9.0

    with pytest.raises(FieldValidationError) as excinfo:
        validate_dataset("daily_prices", frame)

    codes = {issue.code for issue in excinfo.value.issues}
    assert "high_below_low" in codes
    assert "close_outside_high_low" in codes


def test_validate_negative_volume_and_amount_fail() -> None:
    frame = _valid_daily_prices()
    frame.loc[0, "volume"] = -1
    frame.loc[0, "amount"] = -1.0

    with pytest.raises(FieldValidationError) as excinfo:
        validate_dataset("daily_prices", frame)

    codes = {issue.code for issue in excinfo.value.issues}
    assert {"negative_volume", "negative_amount"}.issubset(codes)


def test_valuation_non_positive_values_warn_without_dropping_rows() -> None:
    frame = normalize_dataset(
        "valuation_daily",
        pd.DataFrame(
            {
                "stock_code": ["000001.SZ"],
                "trade_date": ["2026-03-30"],
                "pe_ttm": [0.0],
                "pb": [-1.0],
                "source": ["phase1a7"],
            }
        ),
    )

    validated, issues = validate_dataset("valuation_daily", frame)

    assert len(validated) == 1
    assert {issue.code for issue in issues} == {"non_positive_pe_ttm", "non_positive_pb"}


def test_missing_optional_daily_fields_warn_and_missing_rate_is_preserved() -> None:
    validated, issues = validate_dataset("daily_prices", _valid_daily_prices())

    assert len(validated) == 1
    assert {"missing_adj_factor", "missing_limit_up", "missing_limit_down"}.issubset(
        {issue.code for issue in issues}
    )
