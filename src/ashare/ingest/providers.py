"""Provider interfaces for the Phase 1a-7 real data ingest pilot."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

import pandas as pd


class ProviderError(RuntimeError):
    """Raised when a market data provider cannot return the requested dataset."""


class MarketDataProvider(Protocol):
    """Small provider protocol used by the real data ingest pilot."""

    name: str

    @property
    def provider_version_or_unknown(self) -> str:
        """Return a provider package/version string when available."""
        ...

    def fetch_trading_calendar(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch raw trading-calendar rows."""
        ...

    def fetch_index_members(
        self,
        index_code: str,
        as_of_date: date,
    ) -> pd.DataFrame:
        """Fetch raw index-members rows."""
        ...

    def fetch_securities(
        self,
        stock_codes: Sequence[str],
        as_of_date: date,
    ) -> pd.DataFrame:
        """Fetch raw securities rows for the requested stocks."""
        ...

    def fetch_daily_prices(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch raw daily price rows."""
        ...

    def fetch_valuation_daily(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch raw valuation rows."""
        ...
