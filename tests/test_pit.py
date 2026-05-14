from datetime import date, datetime

import pytest

from ashare.pit.effective_date import calculate_effective_date, next_trading_day


TRADING_DAYS = [
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 7),
    date(2026, 1, 8),
    date(2026, 1, 9),
    date(2026, 1, 12),
]


def test_regular_trading_day_publish_uses_strict_next_trading_day() -> None:
    assert calculate_effective_date(date(2026, 1, 5), TRADING_DAYS) == date(2026, 1, 6)


def test_friday_publish_uses_next_monday_trading_day() -> None:
    assert calculate_effective_date(date(2026, 1, 9), TRADING_DAYS) == date(2026, 1, 12)


def test_weekend_publish_uses_next_trading_day() -> None:
    assert calculate_effective_date(date(2026, 1, 10), TRADING_DAYS) == date(2026, 1, 12)


def test_datetime_publish_uses_only_date_part() -> None:
    publish_time = datetime(2026, 1, 5, 9, 30)

    assert calculate_effective_date(publish_time, TRADING_DAYS) == date(2026, 1, 6)


def test_unsorted_trading_days_do_not_change_effective_date() -> None:
    trading_days = [
        date(2026, 1, 12),
        date(2026, 1, 6),
        date(2026, 1, 5),
        date(2026, 1, 9),
    ]

    assert calculate_effective_date(date(2026, 1, 5), trading_days) == date(2026, 1, 6)


def test_next_trading_day_raises_when_no_later_day_exists() -> None:
    with pytest.raises(ValueError, match="No trading day found after 2026-01-12"):
        next_trading_day(date(2026, 1, 12), TRADING_DAYS)
