"""AkShare provider wrapper for the Phase 1a-7 real data ingest pilot."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
import importlib
import time

import pandas as pd

from ashare.ingest.provider_checks import (
    FIELD_MAPPING_VERSION,
    ClassifiedProviderError,
    ProviderCapabilityCheck,
    ProviderErrorCategory,
    classify_exception,
    require_dataframe,
)
from ashare.ingest.providers import ProviderError


class AkShareProvider:
    """Thin wrapper around the small AkShare API surface used in Phase 1a-7."""

    name = "akshare"
    REQUIRED_APIS = (
        "tool_trade_date_hist_sina",
        "index_stock_cons_csindex",
        "stock_zh_a_hist",
        "stock_a_lg_indicator",
    )

    def __init__(
        self,
        *,
        retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        rate_limit_seconds: float = 0.1,
    ) -> None:
        self.retries = max(int(retries), 0)
        self.retry_backoff_seconds = max(float(retry_backoff_seconds), 0.0)
        self.rate_limit_seconds = max(float(rate_limit_seconds), 0.0)
        try:
            self._akshare = importlib.import_module("akshare")
        except ModuleNotFoundError as exc:
            raise ClassifiedProviderError(
                "akshare is not installed in the active environment",
                category=ProviderErrorCategory.API_UNAVAILABLE,
                api_name="import akshare",
            ) from exc

    @property
    def provider_version_or_unknown(self) -> str:
        version = getattr(self._akshare, "__version__", None)
        return f"akshare-{version}" if version else "akshare-version-unknown"

    @property
    def field_mapping_version(self) -> str:
        return FIELD_MAPPING_VERSION

    def capability_check(self) -> ProviderCapabilityCheck:
        available = []
        missing = []
        for api_name in self.REQUIRED_APIS:
            if callable(getattr(self._akshare, api_name, None)):
                available.append(api_name)
            else:
                missing.append(api_name)
        return ProviderCapabilityCheck(
            provider=self.name,
            provider_version=self.provider_version_or_unknown,
            field_mapping_version=self.field_mapping_version,
            available_apis=tuple(available),
            missing_apis=tuple(missing),
        )

    def fetch_trading_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        api = self._api("tool_trade_date_hist_sina")
        frame = self._call_dataframe(api)
        if frame.empty:
            raise ClassifiedProviderError(
                "AkShare tool_trade_date_hist_sina returned no rows",
                category=ProviderErrorCategory.EMPTY_RESULT,
                api_name="tool_trade_date_hist_sina",
            )
        return frame

    def fetch_index_members(self, index_code: str, as_of_date: date) -> pd.DataFrame:
        api = self._api("index_stock_cons_csindex")
        symbol = index_code.split(".")[0]
        frame = self._call_dataframe(api, symbol=symbol)
        if frame.empty:
            raise ClassifiedProviderError(
                f"AkShare index_stock_cons_csindex returned no rows for {symbol}",
                category=ProviderErrorCategory.EMPTY_RESULT,
                api_name="index_stock_cons_csindex",
            )
        frame = frame.copy()
        if "index_code" not in frame.columns:
            frame["index_code"] = index_code
        if "in_date" not in frame.columns:
            frame["in_date"] = as_of_date
        if "in_effective_date" not in frame.columns:
            frame["in_effective_date"] = as_of_date
        return frame

    def fetch_securities(self, stock_codes: Sequence[str], as_of_date: date) -> pd.DataFrame:
        # Phase 1a-7 can derive names from index_stock_cons_csindex and list_date from
        # universe_as_of_date. Avoid making stock_info_a_code_name a hard dependency because
        # that endpoint may fail independently of the target index-member pilot path.
        return pd.DataFrame({"stock_code": list(stock_codes)})

    def fetch_daily_prices(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        api = self._api("stock_zh_a_hist")
        frames: list[pd.DataFrame] = []
        for stock_code in stock_codes:
            symbol = stock_code.split(".")[0]
            frame = self._call_dataframe(
                api,
                symbol=symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="",
            )
            if frame.empty:
                raise ClassifiedProviderError(
                    f"AkShare stock_zh_a_hist returned no rows for {stock_code}",
                    category=ProviderErrorCategory.EMPTY_RESULT,
                    api_name="stock_zh_a_hist",
                )
            frame = frame.copy()
            if "stock_code" not in frame.columns and "股票代码" not in frame.columns:
                frame["stock_code"] = stock_code
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def fetch_valuation_daily(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        api = self._api("stock_a_lg_indicator")
        frames: list[pd.DataFrame] = []
        for stock_code in stock_codes:
            symbol = stock_code.split(".")[0]
            frame = self._call_dataframe(api, symbol=symbol)
            if frame.empty:
                raise ClassifiedProviderError(
                    f"AkShare stock_a_lg_indicator returned no rows for {stock_code}",
                    category=ProviderErrorCategory.EMPTY_RESULT,
                    api_name="stock_a_lg_indicator",
                )
            frame = frame.copy()
            if "stock_code" not in frame.columns and "股票代码" not in frame.columns:
                frame["stock_code"] = stock_code
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _api(self, name: str):
        api = getattr(self._akshare, name, None)
        if api is None:
            raise ClassifiedProviderError(
                f"AkShare API is unavailable: {name}",
                category=ProviderErrorCategory.API_UNAVAILABLE,
                api_name=name,
            )
        return api

    def _call_dataframe(self, api, **kwargs: object) -> pd.DataFrame:
        api_name = getattr(api, "__name__", "unknown_api")
        last_exc: BaseException | None = None
        for attempt in range(self.retries + 1):
            if self.rate_limit_seconds:
                time.sleep(self.rate_limit_seconds)
            try:
                try:
                    frame = api(**kwargs)
                except TypeError:
                    if kwargs:
                        raise
                    frame = api()
                return require_dataframe(frame, api_name=api_name)
            except Exception as exc:  # pragma: no cover - provider boundary
                last_exc = exc
                category = classify_exception(exc)
                if category not in {
                    ProviderErrorCategory.NETWORK,
                    ProviderErrorCategory.RATE_LIMITED,
                    ProviderErrorCategory.UNKNOWN,
                }:
                    break
                if attempt < self.retries and self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
        assert last_exc is not None
        category = classify_exception(last_exc)
        raise ClassifiedProviderError(
            f"AkShare call failed after {self.retries + 1} attempt(s): {last_exc}",
            category=category,
            api_name=api_name,
        ) from last_exc
