"""Fetching every price source for one set, and persisting the result.

The rule the whole price layer rests on: **a source that fails is omitted, never fatal.** A
CAPTCHA, a layout change, a timeout or missing BrickLink credentials must not hide the sources that
did answer.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import session_scope
from . import alerts, bricklink, collection_repo
from .pricing import PriceQuote, is_minifig
from .rebrickable import LegoSet
from .scraping import amazon, cdiscount
from .scraping.lego_store import LegoStoreError, StorePrice
from .scraping.lego_store import fetch_store_price as scrape_store_price

logger = logging.getLogger(__name__)


async def fetch_prices(
    session: AsyncSession, lego_set: LegoSet, *, bricklink_only: bool = False
) -> list[PriceQuote]:
    """Every marketplace quote for a set, fetched concurrently.

    A minifig (`fig-…`) skips lego.com/Amazon/Cdiscount entirely: it is never sold at retail on its
    own, so scraping them would only burn requests and produce misleading "Indisponible" rows.
    `bricklink_only` is the background-pass mode — there is no browser to drive from a scheduler
    tick, and BrickLink is a plain signed API call.
    """
    quotes: list[PriceQuote] = []

    async def bricklink_quotes() -> list[PriceQuote]:
        try:
            return await bricklink.fetch_prices(session, lego_set)
        except Exception:  # noqa: BLE001 - one source failing must not hide the others
            logger.debug("BrickLink indisponible pour %s", lego_set.set_num, exc_info=True)
            return []

    if bricklink_only or is_minifig(lego_set.set_num) or not settings.scraping_enabled:
        return await bricklink_quotes()

    async def scraped(fetch) -> list[PriceQuote]:  # noqa: ANN001 - two identical scraper signatures
        try:
            quote = await fetch(lego_set)
        except Exception:  # noqa: BLE001
            logger.debug("Source web indisponible pour %s", lego_set.set_num, exc_info=True)
            return []
        return [quote] if quote else []

    results = await asyncio.gather(
        bricklink_quotes(),
        scraped(amazon.fetch_price),
        scraped(cdiscount.fetch_price),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, list):
            quotes.extend(result)
    return quotes


async def fetch_store_price(session: AsyncSession, set_num: str) -> StorePrice | None:
    """The lego.com retail price, persisted on success.

    Deliberately separate from `fetch_prices`: it is by far the slowest source (a full page load
    plus a Cloudflare challenge), and several callers want the marketplace quotes without paying
    for it.
    """
    if not settings.scraping_enabled or is_minifig(set_num):
        return None
    try:
        price = await scrape_store_price(set_num)
    except LegoStoreError as error:
        logger.debug("lego.com : %s (%s)", error, set_num)
        return None
    await collection_repo.cache_store_price(session, set_num, price)
    return price


async def refresh_set_prices(
    session: AsyncSession,
    lego_set: LegoSet,
    *,
    reconcile: bool = True,
    include_store: bool = True,
    mark_fetched: bool = True,
) -> dict[str, object]:
    """One set's full refresh: every source, persisted, then alerts evaluated once.

    `reconcile=True` is correct only for a genuine live fetch — it deletes cached sources absent
    from this result, so a source that went silent stops showing its last known price. A cache-only
    or partial write must pass False, where an empty result can't be told apart from a hiccup.
    """
    set_num = lego_set.set_num

    async def isolated_store_price() -> StorePrice | None:
        # Own session: this task runs concurrently with `fetch_prices` below, and an AsyncSession
        # cannot be shared across concurrent operations (SQLAlchemy raises, or worse, doesn't).
        async with session_scope() as store_session:
            return await fetch_store_price(store_session, set_num)

    store_task = asyncio.create_task(isolated_store_price()) if include_store else None
    quotes = await fetch_prices(session, lego_set)
    store_price = await store_task if store_task else None

    await collection_repo.cache_prices(session, quotes, set_num, reconcile=reconcile)
    if mark_fetched:
        # Stamped whether or not anything was found: a set that stays unpriced after every source
        # was asked is "introuvable", not "pas encore essayé" (#194).
        await collection_repo.mark_prices_fetched(session, set_num)

    fired = await alerts.evaluate_alerts(session, set_num)

    return {
        "setNum": set_num,
        "quotes": quotes,
        "storePrice": store_price,
        "alertsFired": len(fired),
    }
