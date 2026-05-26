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


class AkShareProvider:
    """Thin wrapper around the small AkShare API surface used in Phase 1a-7."""

    name = "akshare"
    CORE_APIS = (
        "tool_trade_date_hist_sina",
        "index_stock_cons_csindex",
    )
    DAILY_PRICE_APIS = (
        "stock_zh_a_hist",
        "stock_zh_a_daily",
        "stock_zh_a_hist_tx",
    )
    VALUATION_APIS = (
        "stock_a_lg_indicator",
        "stock_zh_valuation_baidu",
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
        for api_name in self.CORE_APIS:
            if callable(getattr(self._akshare, api_name, None)):
                available.append(api_name)
            else:
                missing.append(api_name)
        available_daily_price_apis = [
            api_name for api_name in self.DAILY_PRICE_APIS
            if callable(getattr(self._akshare, api_name, None))
        ]
        available.extend(available_daily_price_apis)
        if not available_daily_price_apis:
            missing.append("|".join(self.DAILY_PRICE_APIS))
        available_valuation_apis = [
            api_name for api_name in self.VALUATION_APIS
            if callable(getattr(self._akshare, api_name, None))
        ]
        available.extend(available_valuation_apis)
        if not available_valuation_apis:
            missing.append("|".join(self.VALUATION_APIS))
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
        frames: list[pd.DataFrame] = []
        active_api_name: str | None = None
        for stock_code in stock_codes:
            frame, active_api_name = self._fetch_daily_price_one_stock(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                preferred_api_name=active_api_name,
            )
            if frame.empty:
                raise ClassifiedProviderError(
                    f"AkShare daily price APIs returned no rows for {stock_code}",
                    category=ProviderErrorCategory.EMPTY_RESULT,
                    api_name="|".join(self.DAILY_PRICE_APIS),
                )
            frame = frame.copy()
            frame["stock_code"] = stock_code
            if "trade_date" not in frame.columns:
                frame["trade_date"] = pd.NA
            for source_column in ("date", "日期"):
                if source_column in frame.columns:
                    missing_trade_date = frame["trade_date"].isna() | (
                        frame["trade_date"].astype("string").str.strip() == ""
                    )
                    frame.loc[missing_trade_date, "trade_date"] = frame.loc[
                        missing_trade_date,
                        source_column,
                    ]
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _fetch_daily_price_one_stock(
        self,
        *,
        stock_code: str,
        start_date: date,
        end_date: date,
        preferred_api_name: str | None,
    ) -> tuple[pd.DataFrame, str]:
        api_names = self._available_daily_price_api_names()
        if preferred_api_name in api_names:
            api_names = [
                preferred_api_name,
                *[name for name in api_names if name != preferred_api_name],
            ]
        errors: list[str] = []
        for api_name in api_names:
            api = self._api(api_name)
            try:
                frame = self._call_daily_price_api(
                    api_name,
                    api,
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                )
            except ClassifiedProviderError as exc:
                errors.append(str(exc))
                continue
            except Exception as exc:
                category = classify_exception(exc)
                errors.append(f"{api_name}:{category}:{exc}")
                continue
            if not frame.empty:
                return frame, api_name
            errors.append(f"{api_name}:empty_result")
        raise ClassifiedProviderError(
            "All supported AkShare daily price APIs failed for "
            f"{stock_code}. Attempts: {'; '.join(errors)}",
            category=ProviderErrorCategory.NETWORK
            if any("network_error" in item for item in errors)
            else ProviderErrorCategory.UNKNOWN,
            api_name="|".join(self.DAILY_PRICE_APIS),
        )

    def _available_daily_price_api_names(self) -> list[str]:
        names = [
            api_name for api_name in self.DAILY_PRICE_APIS
            if callable(getattr(self._akshare, api_name, None))
        ]
        if not names:
            raise ClassifiedProviderError(
                "No supported AkShare daily price API is available.",
                category=ProviderErrorCategory.API_UNAVAILABLE,
                api_name="|".join(self.DAILY_PRICE_APIS),
            )
        return names

    def _call_daily_price_api(
        self,
        api_name: str,
        api,
        *,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        raw_symbol = stock_code.split(".")[0]
        market_symbol = _market_symbol(stock_code)
        if api_name == "stock_zh_a_hist":
            return self._call_dataframe(
                api,
                symbol=raw_symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="",
            )
        if api_name == "stock_zh_a_daily":
            return self._call_dataframe(
                api,
                symbol=market_symbol,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="",
            )
        if api_name == "stock_zh_a_hist_tx":
            frame = self._call_dataframe(
                api,
                symbol=market_symbol,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="",
            )
            return _normalize_tx_daily_price_frame(frame)
        raise ClassifiedProviderError(
            f"Unsupported daily price API: {api_name}",
            category=ProviderErrorCategory.API_UNAVAILABLE,
            api_name=api_name,
        )

    def fetch_valuation_daily(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        api_name, api = self._valuation_api()
        if api_name == "stock_zh_valuation_baidu":
            return self._fetch_valuation_daily_baidu(api, stock_codes, start_date, end_date)

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

    def _valuation_api(self):
        for api_name in self.VALUATION_APIS:
            api = getattr(self._akshare, api_name, None)
            if callable(api):
                return api_name, api
        raise ClassifiedProviderError(
            "No supported AkShare valuation API is available.",
            category=ProviderErrorCategory.API_UNAVAILABLE,
            api_name="|".join(self.VALUATION_APIS),
        )

    def _fetch_valuation_daily_baidu(
        self,
        api,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        period = _baidu_valuation_period(start_date, end_date)
        frames: list[pd.DataFrame] = []
        for stock_code in stock_codes:
            symbol = stock_code.split(".")[0]
            pe = self._fetch_baidu_valuation_indicator(
                api,
                symbol=symbol,
                indicator="市盈率(TTM)",
                output_column="pe_ttm",
                period=period,
            )
            pb = self._fetch_baidu_valuation_indicator(
                api,
                symbol=symbol,
                indicator="市净率",
                output_column="pb",
                period=period,
            )
            total_mv = self._fetch_baidu_valuation_indicator(
                api,
                symbol=symbol,
                indicator="总市值",
                output_column="total_mv",
                period=period,
                required=False,
            )
            merged = pe.merge(pb, on="trade_date", how="inner")
            if not total_mv.empty:
                merged = merged.merge(total_mv, on="trade_date", how="left")
            else:
                merged["total_mv"] = pd.NA
            merged = merged[
                (merged["trade_date"] >= start_date) & (merged["trade_date"] <= end_date)
            ].copy()
            if merged.empty:
                raise ClassifiedProviderError(
                    f"AkShare stock_zh_valuation_baidu returned no valuation rows for "
                    f"{stock_code} in {start_date.isoformat()}..{end_date.isoformat()}",
                    category=ProviderErrorCategory.EMPTY_RESULT,
                    api_name="stock_zh_valuation_baidu",
                )
            merged["stock_code"] = stock_code
            frames.append(merged)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _fetch_baidu_valuation_indicator(
        self,
        api,
        *,
        symbol: str,
        indicator: str,
        output_column: str,
        period: str,
        required: bool = True,
    ) -> pd.DataFrame:
        frame = self._call_dataframe(
            api,
            symbol=symbol,
            indicator=indicator,
            period=period,
        )
        if frame.empty:
            if required:
                raise ClassifiedProviderError(
                    f"AkShare stock_zh_valuation_baidu returned no rows for "
                    f"{symbol} {indicator}",
                    category=ProviderErrorCategory.EMPTY_RESULT,
                    api_name="stock_zh_valuation_baidu",
                )
            return pd.DataFrame(columns=["trade_date", output_column])
        missing = {"date", "value"} - set(frame.columns)
        if missing:
            raise ClassifiedProviderError(
                "AkShare stock_zh_valuation_baidu response is missing column(s): "
                + ", ".join(sorted(missing)),
                category=ProviderErrorCategory.MISSING_FIELD,
                api_name="stock_zh_valuation_baidu",
            )
        result = frame.loc[:, ["date", "value"]].copy()
        result = result.rename(columns={"date": "trade_date", "value": output_column})
        result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.date
        result[output_column] = pd.to_numeric(result[output_column], errors="coerce")
        result = result.dropna(subset=["trade_date", output_column])
        result = result.sort_values("trade_date", kind="mergesort").drop_duplicates(
            "trade_date",
            keep="last",
        )
        return result.reset_index(drop=True)

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


def _baidu_valuation_period(start_date: date, end_date: date) -> str:
    days = max((end_date - start_date).days, 0)
    if days <= 366:
        return "近一年"
    if days <= 366 * 3:
        return "近三年"
    if days <= 366 * 5:
        return "近五年"
    if days <= 366 * 10:
        return "近十年"
    return "全部"


def _market_symbol(stock_code: str) -> str:
    raw = stock_code.strip().lower()
    if "." not in raw:
        return raw
    code, exchange = raw.split(".", 1)
    return f"{exchange}{code}"


def _normalize_tx_daily_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "amount" not in frame.columns:
        return frame
    result = frame.copy()
    if "volume" not in result.columns and "close" in result.columns:
        tx_volume_lots = pd.to_numeric(result["amount"], errors="coerce")
        close = pd.to_numeric(result["close"], errors="coerce")
        result["volume"] = tx_volume_lots * 100.0
        result["amount"] = result["volume"] * close
    return result
