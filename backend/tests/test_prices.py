"""`is_price_stale`: the threshold that decides whether opening a set's detail page schedules a
background price refresh (`routers/sets.py`)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.services import prices
from app.services.pricing import PriceQuote, PriceSource
from app.services.rebrickable import LegoSet
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


@pytest.mark.asyncio
async def test_refresh_set_prices_persists_partial_results_while_fetching() -> None:
    """A retailer quote should appear in the cache before the slowest browser scrape finishes."""
    lego_set = LegoSet(
        set_num='12345',
        name='Test set',
        year=2024,
        theme_id=1,
        num_parts=100,
        set_img_url=None,
        set_url=None,
    )
    persisted: list[set[str]] = []

    async def cache_prices(session, quotes, set_num, *, reconcile=False):
        del session, set_num, reconcile
        persisted.append({quote.source.value for quote in quotes})

    async def fake_bricklink(session_arg, target):
        del session_arg, target
        await asyncio.sleep(0.15)
        return [PriceQuote(source=PriceSource.BRICKLINK_NEW, amount=30.0, fetched_at=datetime.now(UTC))]

    async def fake_amazon(target):
        del target
        await asyncio.sleep(0.02)
        return PriceQuote(source=PriceSource.AMAZON, amount=25.0, fetched_at=datetime.now(UTC))

    async def fake_cdiscount(target):
        del target
        await asyncio.sleep(0.30)
        return None

    async def fake_alerts(session_arg, target):
        del session_arg, target
        return []

    with (
        patch.object(prices.bricklink, 'fetch_prices', side_effect=fake_bricklink),
        patch.object(prices.amazon, 'fetch_price', side_effect=fake_amazon),
        patch.object(prices.cdiscount, 'fetch_price', side_effect=fake_cdiscount),
        patch.object(prices.collection_repo, 'cache_prices', side_effect=cache_prices),
        patch.object(prices.alerts, 'evaluate_alerts', new=fake_alerts),
        patch.object(prices.collection_repo, 'mark_prices_fetched', new=AsyncMock()),
    ):
        task = asyncio.create_task(
            prices.refresh_set_prices(None, lego_set, include_store=False, reconcile=False, mark_fetched=False)
        )
        await asyncio.sleep(0.05)
        assert any({'amazon'} <= sources for sources in persisted)
        await task
