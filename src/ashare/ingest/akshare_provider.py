"""AkShare provider wrapper for the Phase 1a-7 real data ingest pilot."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
import importlib

import pandas as pd

from ashare.ingest.providers import ProviderError


class AkShareProvider:
    """Thin wrapper around the small AkShare API surface used in Phase 1a-7."""

    name = "akshare"

    def __init__(self) -> None:
        try:
            self._akshare = importlib.import_module("akshare")
        except ModuleNotFoundError as exc:
            raise ProviderError("akshare is not installed in the active environment.") from exc

    @property
    def provider_version_or_unknown(self) -> str:
        version = getattr(self._akshare, "__version__", None)
        return f"akshare-{version}" if version else "akshare-version-unknown"

    def fetch_trading_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        api = self._api("tool_trade_date_hist_sina")
        frame = self._call_dataframe(api)
        if frame.empty:
            raise ProviderError("AkShare tool_trade_date_hist_sina returned no rows.")
        return frame

    def fetch_index_members(self, index_code: str, as_of_date: date) -> pd.DataFrame:
        api = self._api("index_stock_cons_csindex")
        symbol = index_code.split(".")[0]
        frame = self._call_dataframe(api, symbol=symbol)
        if frame.empty:
            raise ProviderError(f"AkShare index_stock_cons_csindex returned no rows for {symbol}.")
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
                raise ProviderError(f"AkShare stock_zh_a_hist returned no rows for {stock_code}.")
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
                raise ProviderError(f"AkShare stock_a_lg_indicator returned no rows for {stock_code}.")
            frame = frame.copy()
            if "stock_code" not in frame.columns and "股票代码" not in frame.columns:
                frame["stock_code"] = stock_code
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _api(self, name: str):
        api = getattr(self._akshare, name, None)
        if api is None:
            raise ProviderError(f"AkShare API is unavailable: {name}")
        return api

    def _call_dataframe(self, api, **kwargs: object) -> pd.DataFrame:
        try:
            frame = api(**kwargs)
        except TypeError:
            if kwargs:
                raise
            frame = api()
        except Exception as exc:  # pragma: no cover - provider boundary
            raise ProviderError(f"AkShare call failed: {api.__name__}: {exc}") from exc
        if not isinstance(frame, pd.DataFrame):
            raise ProviderError(f"AkShare call did not return a DataFrame: {api.__name__}")
        return frame
