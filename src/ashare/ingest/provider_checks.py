"""Provider capability checks and classified provider errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from ashare.ingest.providers import ProviderError


FIELD_MAPPING_VERSION = "phase8.v1"


class ProviderErrorCategory:
    NETWORK = "network_error"
    EMPTY_RESULT = "empty_result"
    MISSING_FIELD = "missing_field"
    TYPE_ERROR = "type_error"
    RATE_LIMITED = "rate_limited"
    CACHE_MISS = "cache_miss"
    API_UNAVAILABLE = "api_unavailable"
    UNKNOWN = "unknown"


class ClassifiedProviderError(ProviderError):
    """ProviderError carrying a machine-readable failure category."""

    def __init__(self, message: str, *, category: str, api_name: str | None = None) -> None:
        self.category = category
        self.api_name = api_name
        prefix = f"{category}"
        if api_name:
            prefix += f":{api_name}"
        super().__init__(f"{prefix}: {message}")


@dataclass(frozen=True)
class ProviderCapabilityCheck:
    provider: str
    provider_version: str
    field_mapping_version: str
    available_apis: tuple[str, ...]
    missing_apis: tuple[str, ...]

    @property
    def status(self) -> str:
        return "PASS" if not self.missing_apis else "FAIL"

    def as_warning(self) -> str:
        if self.status == "PASS":
            return (
                f"provider_capability_check PASS provider={self.provider} "
                f"version={self.provider_version} field_mapping={self.field_mapping_version}"
            )
        return (
            f"provider_capability_check FAIL provider={self.provider} "
            f"missing_apis={','.join(self.missing_apis)}"
        )


def classify_exception(exc: BaseException) -> str:
    """Classify provider-boundary exceptions into stable categories."""
    if isinstance(exc, ClassifiedProviderError):
        return exc.category
    text = str(exc).lower()
    if any(token in text for token in ["timeout", "connection", "network", "temporary failure"]):
        return ProviderErrorCategory.NETWORK
    if any(token in text for token in ["rate limit", "too many requests", "429", "频率"]):
        return ProviderErrorCategory.RATE_LIMITED
    if isinstance(exc, TypeError):
        return ProviderErrorCategory.TYPE_ERROR
    return ProviderErrorCategory.UNKNOWN


def require_dataframe(frame: Any, *, api_name: str) -> pd.DataFrame:
    """Validate that a provider API returned a DataFrame."""
    if not isinstance(frame, pd.DataFrame):
        raise ClassifiedProviderError(
            "provider API did not return a pandas DataFrame",
            category=ProviderErrorCategory.TYPE_ERROR,
            api_name=api_name,
        )
    return frame
