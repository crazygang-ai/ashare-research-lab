from __future__ import annotations

from datetime import date
import sys
import types

import pandas as pd
import pytest

from ashare.ingest.akshare_provider import AkShareProvider
from ashare.ingest.contracts import normalize_dataset
from ashare.ingest.provider_checks import ClassifiedProviderError


def test_akshare_capability_check_reports_missing_api(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"
    fake.tool_trade_date_hist_sina = lambda: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "akshare", fake)

    check = AkShareProvider(rate_limit_seconds=0).capability_check()

    assert check.status == "FAIL"
    assert "stock_zh_a_hist|stock_zh_a_daily|stock_zh_a_hist_tx" in check.missing_apis
    assert check.field_mapping_version == "phase8.v1"


def test_akshare_empty_result_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"
    fake.tool_trade_date_hist_sina = lambda: pd.DataFrame()
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame()
    fake.stock_zh_a_hist = lambda **kwargs: pd.DataFrame()
    fake.stock_a_lg_indicator = lambda symbol: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "akshare", fake)

    provider = AkShareProvider(rate_limit_seconds=0)

    with pytest.raises(ClassifiedProviderError, match="empty_result"):
        provider.fetch_trading_calendar(date(2026, 1, 1), date(2026, 1, 2))


def test_akshare_network_error_is_retried_and_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"

    def fail() -> pd.DataFrame:
        raise TimeoutError("network timeout")

    fake.tool_trade_date_hist_sina = fail
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame()
    fake.stock_zh_a_hist = lambda **kwargs: pd.DataFrame()
    fake.stock_a_lg_indicator = lambda symbol: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "akshare", fake)

    provider = AkShareProvider(retries=1, retry_backoff_seconds=0, rate_limit_seconds=0)

    with pytest.raises(ClassifiedProviderError) as excinfo:
        provider.fetch_trading_calendar(date(2026, 1, 1), date(2026, 1, 2))

    assert excinfo.value.category == "network_error"
    assert "after 2 attempt" in str(excinfo.value)


def test_akshare_non_dataframe_is_type_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"
    fake.tool_trade_date_hist_sina = lambda: {"bad": "shape"}
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame()
    fake.stock_zh_a_hist = lambda **kwargs: pd.DataFrame()
    fake.stock_a_lg_indicator = lambda symbol: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "akshare", fake)

    provider = AkShareProvider(rate_limit_seconds=0)

    with pytest.raises(ClassifiedProviderError) as excinfo:
        provider.fetch_trading_calendar(date(2026, 1, 1), date(2026, 1, 2))

    assert excinfo.value.category == "type_error"


def test_akshare_capability_check_accepts_baidu_valuation_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"
    fake.tool_trade_date_hist_sina = lambda: pd.DataFrame({"trade_date": []})
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame()
    fake.stock_zh_a_hist = lambda **kwargs: pd.DataFrame()
    fake.stock_zh_valuation_baidu = lambda **kwargs: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "akshare", fake)

    check = AkShareProvider(rate_limit_seconds=0).capability_check()

    assert check.status == "PASS"
    assert "stock_zh_valuation_baidu" in check.available_apis
    assert "stock_a_lg_indicator" not in check.missing_apis


def test_akshare_fetch_daily_prices_uses_sina_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"

    def failing_hist(**kwargs: object) -> pd.DataFrame:
        raise ConnectionError("remote closed")

    def daily(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
        assert symbol == "sz002594"
        return pd.DataFrame(
            {
                "date": ["2026-01-02"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "volume": [1000.0],
                "amount": [10200.0],
            }
        )

    fake.tool_trade_date_hist_sina = lambda: pd.DataFrame({"trade_date": []})
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame()
    fake.stock_zh_a_hist = failing_hist
    fake.stock_zh_a_daily = daily
    fake.stock_zh_valuation_baidu = lambda **kwargs: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "akshare", fake)

    frame = AkShareProvider(retries=0, rate_limit_seconds=0).fetch_daily_prices(
        ["002594.SZ"],
        date(2026, 1, 1),
        date(2026, 1, 3),
    )

    assert frame["stock_code"].tolist() == ["002594.SZ"]
    assert frame["date"].tolist() == ["2026-01-02"]
    assert frame["volume"].tolist() == [1000.0]
    assert frame["amount"].tolist() == [10200.0]


def test_akshare_fetch_daily_prices_normalizes_mixed_api_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"

    def hist(symbol: str, **kwargs: object) -> pd.DataFrame:
        if symbol == "000001":
            return pd.DataFrame(
                {
                    "日期": ["2026-01-02"],
                    "股票代码": ["000001"],
                    "开盘": [10.0],
                    "最高": [10.5],
                    "最低": [9.8],
                    "收盘": [10.2],
                    "成交量": [1000.0],
                    "成交额": [10200.0],
                }
            )
        raise ConnectionError("hist unavailable for this symbol")

    def daily(symbol: str, **kwargs: object) -> pd.DataFrame:
        assert symbol == "sz002594"
        return pd.DataFrame(
            {
                "date": ["2026-01-02"],
                "open": [20.0],
                "high": [20.5],
                "low": [19.8],
                "close": [20.2],
                "volume": [2000.0],
                "amount": [40400.0],
            }
        )

    fake.tool_trade_date_hist_sina = lambda: pd.DataFrame({"trade_date": []})
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame()
    fake.stock_zh_a_hist = hist
    fake.stock_zh_a_daily = daily
    fake.stock_zh_valuation_baidu = lambda **kwargs: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "akshare", fake)

    raw = AkShareProvider(retries=0, rate_limit_seconds=0).fetch_daily_prices(
        ["000001.SZ", "002594.SZ"],
        date(2026, 1, 1),
        date(2026, 1, 3),
    )
    normalized = normalize_dataset("daily_prices", raw)

    assert normalized["stock_code"].tolist() == ["000001.SZ", "002594.SZ"]
    assert normalized["trade_date"].tolist() == [date(2026, 1, 2), date(2026, 1, 2)]
    assert normalized["close"].tolist() == [10.2, 20.2]


def test_akshare_fetch_valuation_daily_uses_baidu_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"

    def valuation(symbol: str, indicator: str, period: str) -> pd.DataFrame:
        values = {
            "市盈率(TTM)": [20.0, 21.0, 22.0],
            "市净率": [2.0, 2.1, 2.2],
            "总市值": [1000.0, 1010.0, 1020.0],
        }
        return pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
                "value": values[indicator],
            }
        )

    fake.tool_trade_date_hist_sina = lambda: pd.DataFrame({"trade_date": []})
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame()
    fake.stock_zh_a_hist = lambda **kwargs: pd.DataFrame()
    fake.stock_zh_valuation_baidu = valuation
    monkeypatch.setitem(sys.modules, "akshare", fake)

    frame = AkShareProvider(rate_limit_seconds=0).fetch_valuation_daily(
        ["002594.SZ"],
        date(2026, 1, 2),
        date(2026, 1, 3),
    )

    assert frame["stock_code"].tolist() == ["002594.SZ", "002594.SZ"]
    assert frame["trade_date"].tolist() == [date(2026, 1, 2), date(2026, 1, 3)]
    assert frame["pe_ttm"].tolist() == [21.0, 22.0]
    assert frame["pb"].tolist() == [2.1, 2.2]
    assert frame["total_mv"].tolist() == [1010.0, 1020.0]
