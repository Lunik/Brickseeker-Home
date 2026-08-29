"""`is_price_stale`: the threshold that decides whether opening a set's detail page schedules a
background price refresh (`routers/sets.py`)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.services import prices
from app.services.prices import STALE_PRICE_THRESHOLD, is_price_stale
from app.services.pricing import PriceQuote, PriceSource
from app.services.rebrickable import LegoSet


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
        set_num="12345",
        name="Test set",
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
        assert session_arg is not None
        del target
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

    async def fake_fnac(target):
        del target
        await asyncio.sleep(0.08)
        return PriceQuote(source=PriceSource.FNAC, amount=26.0, fetched_at=datetime.now(UTC))

    async def fake_alerts(session_arg, target):
        del session_arg, target
        return []

    with (
        patch.object(prices.bricklink, "fetch_prices", side_effect=fake_bricklink),
        patch.object(prices.amazon, "fetch_price", side_effect=fake_amazon),
        patch.object(prices.cdiscount, "fetch_price", side_effect=fake_cdiscount),
        patch.object(prices.cultura, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.fnac, "fetch_price", side_effect=fake_fnac),
        patch.object(prices.king_jouet, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.la_grande_recre, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.joueclub, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.carrefour, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.intermarche, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.collection_repo, "cache_prices", side_effect=cache_prices),
        patch.object(prices.alerts, "evaluate_alerts", new=fake_alerts),
        patch.object(prices.collection_repo, "mark_prices_fetched", new=AsyncMock()),
    ):
        task = asyncio.create_task(
            prices.refresh_set_prices(
                None,
                lego_set,
                include_store=False,
                reconcile=False,
                mark_fetched=False,
            )
        )
        await asyncio.sleep(0.05)
        assert any({"amazon"} <= sources for sources in persisted)
        result = await task
        assert any({"fnac"} <= sources for sources in persisted)
        assert {quote.source for quote in result["quotes"]} >= {
            PriceSource.AMAZON,
            PriceSource.FNAC,
            PriceSource.BRICKLINK_NEW,
        }


@pytest.mark.asyncio
async def test_stalled_source_is_cancelled_at_its_deadline() -> None:
    lego_set = LegoSet("12345", "Test set", 2024, 1, 100, None, None)
    cancelled = asyncio.Event()

    async def stalled(_session, _target):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with (
        patch.object(prices.settings, "scraping_enabled", False),
        patch.object(prices.settings, "price_source_timeout_seconds", 0.01),
        patch.object(prices.bricklink, "fetch_prices", side_effect=stalled),
    ):
        assert await asyncio.wait_for(prices.fetch_prices(None, lego_set), timeout=0.2) == []

    await asyncio.wait_for(cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_browser_sources_are_globally_bounded() -> None:
    lego_set = LegoSet("12345", "Test set", 2024, 1, 100, None, None)
    active = 0
    maximum_active = 0

    async def web_source(_target):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            await asyncio.sleep(0.01)
        finally:
            active -= 1
        return None

    with (
        patch.object(prices.settings, "scraping_enabled", True),
        patch.object(prices, "_web_source_slots", asyncio.Semaphore(2)),
        patch.object(prices.bricklink, "fetch_prices", new=AsyncMock(return_value=[])),
        patch.object(prices.amazon, "fetch_price", side_effect=web_source),
        patch.object(prices.cdiscount, "fetch_price", side_effect=web_source),
        patch.object(prices.cultura, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.fnac, "fetch_price", side_effect=web_source),
        patch.object(prices.king_jouet, "fetch_price", side_effect=web_source),
        patch.object(prices.la_grande_recre, "fetch_price", side_effect=web_source),
        patch.object(prices.joueclub, "fetch_price", side_effect=web_source),
        patch.object(prices.carrefour, "fetch_price", side_effect=web_source),
        patch.object(prices.intermarche, "fetch_price", side_effect=web_source),
    ):
        assert await prices.fetch_prices(None, lego_set) == []

    assert maximum_active == 2


@pytest.mark.asyncio
async def test_failed_browser_source_is_skipped_during_cooldown() -> None:
    source = "blockedRetailer"
    attempts = AsyncMock(side_effect=RuntimeError("blocked"))
    prices._source_unavailable_until.pop(source, None)

    with patch.object(prices, "_web_source_slots", asyncio.Semaphore(1)):
        assert (
            await prices._run_source(source, attempts, browser_backed=True)
            is None
        )
        assert (
            await prices._run_source(source, attempts, browser_backed=True)
            is None
        )

    assert attempts.await_count == 1
    prices._source_unavailable_until.pop(source, None)


@pytest.mark.asyncio
async def test_reconcile_preserves_sources_skipped_by_cooldown() -> None:
    lego_set = LegoSet("12345", "Test set", 2024, 1, 100, None, None)
    cache = AsyncMock()
    cooldown = {"amazon": time.monotonic() + 60}

    with (
        patch.object(prices.settings, "scraping_enabled", True),
        patch.object(prices, "_source_unavailable_until", cooldown),
        patch.object(prices.bricklink, "fetch_prices", new=AsyncMock(return_value=[])),
        patch.object(prices.amazon, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.cdiscount, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.cultura, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.fnac, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.king_jouet, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.la_grande_recre, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.joueclub, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.carrefour, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.intermarche, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.collection_repo, "cache_prices", new=cache),
        patch.object(prices.collection_repo, "mark_prices_fetched", new=AsyncMock()),
        patch.object(prices.alerts, "evaluate_alerts", new=AsyncMock(return_value=[])),
    ):
        await prices.refresh_set_prices(None, lego_set, include_store=False)

    assert cache.await_args.kwargs["preserve_sources"] == {"amazon"}


@pytest.mark.asyncio
async def test_cancelling_refresh_cancels_all_source_tasks() -> None:
    lego_set = LegoSet("12345", "Test set", 2024, 1, 100, None, None)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def stalled(_target):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with (
        patch.object(prices.settings, "scraping_enabled", True),
        patch.object(prices.bricklink, "fetch_prices", new=AsyncMock(return_value=[])),
        patch.object(prices.amazon, "fetch_price", side_effect=stalled),
        patch.object(prices.cdiscount, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.cultura, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.fnac, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.king_jouet, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.la_grande_recre, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.joueclub, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.carrefour, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.intermarche, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.collection_repo, "cache_prices", new=AsyncMock()),
        patch.object(prices.collection_repo, "mark_prices_fetched", new=AsyncMock()),
        patch.object(prices.alerts, "evaluate_alerts", new=AsyncMock(return_value=[])),
    ):
        task = asyncio.create_task(
            prices.refresh_set_prices(
                None,
                lego_set,
                include_store=False,
                reconcile=False,
                mark_fetched=False,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    await asyncio.wait_for(cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_complete_refresh_timeout_includes_persistence() -> None:
    lego_set = LegoSet("12345", "Test set", 2024, 1, 100, None, None)
    persistence_cancelled = asyncio.Event()

    async def amazon_quote(_target):
        return PriceQuote(
            source=PriceSource.AMAZON,
            amount=25.0,
            fetched_at=datetime.now(UTC),
        )

    async def stalled_cache(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            persistence_cancelled.set()

    with (
        patch.object(prices.settings, "scraping_enabled", True),
        patch.object(prices.settings, "price_source_timeout_seconds", 0.2),
        patch.object(prices.settings, "price_refresh_timeout_seconds", 0.02),
        patch.object(prices.bricklink, "fetch_prices", new=AsyncMock(return_value=[])),
        patch.object(prices.amazon, "fetch_price", side_effect=amazon_quote),
        patch.object(prices.cdiscount, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.cultura, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.fnac, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.king_jouet, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.la_grande_recre, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.joueclub, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.carrefour, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.intermarche, "fetch_price", new=AsyncMock(return_value=None)),
        patch.object(prices.collection_repo, "cache_prices", side_effect=stalled_cache),
        pytest.raises(prices.PriceRefreshTimeout),
    ):
        await prices.refresh_set_prices(
            None,
            lego_set,
            include_store=False,
            reconcile=False,
            mark_fetched=False,
        )

    await asyncio.wait_for(persistence_cancelled.wait(), timeout=0.2)


def test_background_refresh_claim_is_single_flight() -> None:
    set_num = "12345"
    prices.release_background_refresh(set_num)
    try:
        assert prices.claim_background_refresh(set_num) is True
        assert prices.claim_background_refresh(set_num) is False
        assert prices.is_background_refreshing(set_num) is True
    finally:
        prices.release_background_refresh(set_num)
    assert prices.is_background_refreshing(set_num) is False
