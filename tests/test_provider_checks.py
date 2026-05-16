from __future__ import annotations

from datetime import date
import sys
import types

import pandas as pd
import pytest

from ashare.ingest.akshare_provider import AkShareProvider
from ashare.ingest.provider_checks import ClassifiedProviderError


def test_akshare_capability_check_reports_missing_api(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace()
    fake.__version__ = "test"
    fake.tool_trade_date_hist_sina = lambda: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "akshare", fake)

    check = AkShareProvider(rate_limit_seconds=0).capability_check()

    assert check.status == "FAIL"
    assert "stock_zh_a_hist" in check.missing_apis
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
