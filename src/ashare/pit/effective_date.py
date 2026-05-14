"""Point-in-time effective-date rules."""

from bisect import bisect_right
from collections.abc import Sequence
from datetime import date, datetime


def next_trading_day(after_date: date, trading_days: Sequence[date]) -> date:
    """Return the first trading day strictly after ``after_date``."""
    sorted_days = sorted(trading_days)
    next_index = bisect_right(sorted_days, after_date)

    if next_index >= len(sorted_days):
        raise ValueError(f"No trading day found after {after_date.isoformat()}.")

    return sorted_days[next_index]


def calculate_effective_date(publish_time: date | datetime, trading_days: Sequence[date]) -> date:
    """Calculate the PIT date when published information becomes usable."""
    publish_date = publish_time.date() if isinstance(publish_time, datetime) else publish_time
    return next_trading_day(publish_date, trading_days)
