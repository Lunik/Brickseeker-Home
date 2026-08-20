"""`is_price_stale`: the threshold that decides whether opening a set's detail page schedules a
background price refresh (`routers/sets.py`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.prices import STALE_PRICE_THRESHOLD, is_price_stale


def test_never_fetched_is_stale() -> None:
    assert is_price_stale(None) is True


def test_just_fetched_is_not_stale() -> None:
    assert is_price_stale(datetime.now(UTC)) is False


def test_fetched_just_under_the_threshold_is_not_stale() -> None:
    fetched_at = datetime.now(UTC) - STALE_PRICE_THRESHOLD + timedelta(minutes=1)
    assert is_price_stale(fetched_at) is False


def test_fetched_just_over_the_threshold_is_stale() -> None:
    fetched_at = datetime.now(UTC) - STALE_PRICE_THRESHOLD - timedelta(minutes=1)
    assert is_price_stale(fetched_at) is True


def test_naive_datetime_is_treated_as_utc() -> None:
    """`CachedSet.prices_fetched_at` is stored naive (SQLite has no timezone-aware column type) —
    comparing it against `datetime.now(UTC)` without normalizing first would raise, not misbehave,
    so this is really guarding against a regression that fails loudly in production."""
    naive_fetched_at = (datetime.now(UTC) - timedelta(days=1)).replace(tzinfo=None)
    assert is_price_stale(naive_fetched_at) is False
