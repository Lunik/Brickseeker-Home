"""Fetching every price source for one set, and persisting the result.

The rule the whole price layer rests on: **a source that fails is omitted, never fatal.** A
CAPTCHA, a layout change, a timeout or missing BrickLink credentials must not hide the sources that
did answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import session_scope
from . import alerts, bricklink, collection_repo
from .pricing import PriceQuote, PriceSource, is_minifig
from .rebrickable import LegoSet
from .scraping import (
    amazon,
    carrefour,
    cdiscount,
    cultura,
    fnac,
    intermarche,
    joueclub,
    king_jouet,
    la_grande_recre,
)
from .scraping.browser import ScrapeBlocked
from .scraping.lego_store import LegoStoreError, StorePrice
from .scraping.lego_store import fetch_store_price as scrape_store_price

logger = logging.getLogger(__name__)

#: How old `CachedSet.prices_fetched_at` can be before opening the set/minifig's detail page
#: triggers a background refresh (see `is_price_stale` and its caller in `routers/sets.py`).
STALE_PRICE_THRESHOLD = timedelta(days=7)

SourceProgressStatus = Literal[
    "started",
    "completed",
    "failed",
    "timed_out",
    "cancelled",
    "skipped",
    "captcha_required",
]
SourceProgressCallback = Callable[[str, SourceProgressStatus], None]
CaptchaRequiredCallback = Callable[[str, ScrapeBlocked], None]

_background_refreshes: set[str] = set()
_web_source_slots = asyncio.Semaphore(settings.scrape_max_concurrency)
_source_unavailable_until: dict[str, float] = {}
_captcha_required_until: dict[str, float] = {}
_SOURCE_FAILURE_COOLDOWN_SECONDS = 15 * 60


class PriceRefreshTimeout(RuntimeError):
    """The complete refresh exceeded its deadline and was cancelled cleanly."""


@dataclass(slots=True)
class _SourceOutput:
    quotes: list[PriceQuote] | None = None
    store_price: StorePrice | None = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def is_price_stale(prices_fetched_at: datetime | None) -> bool:
    """`None` means every source was never even tried once — that is staler than any threshold."""
    if prices_fetched_at is None:
        return True
    return datetime.now(UTC) - _aware(prices_fetched_at) > STALE_PRICE_THRESHOLD


def claim_background_refresh(set_num: str) -> bool:
    """Atomically claims one automatic detail-page refresh in this single-process server."""
    if set_num in _background_refreshes:
        return False
    _background_refreshes.add(set_num)
    return True


def release_background_refresh(set_num: str) -> None:
    _background_refreshes.discard(set_num)


def is_background_refreshing(set_num: str) -> bool:
    return set_num in _background_refreshes


def captcha_required_sources() -> list[str]:
    now = time.monotonic()
    expired = [source for source, until in _captcha_required_until.items() if until <= now]
    for source in expired:
        _captcha_required_until.pop(source, None)
    return sorted(_captcha_required_until)


def clear_captcha_requirement(source: str) -> None:
    _captcha_required_until.pop(source, None)
    _source_unavailable_until.pop(source, None)


def _retail_fetchers() -> tuple[
    tuple[str, Callable[[LegoSet], Awaitable[PriceQuote | None]], bool], ...
]:
    # Resolve the functions at call time so tests and runtime instrumentation can patch a source.
    return (
        (PriceSource.AMAZON.value, amazon.fetch_price, True),
        (PriceSource.CDISCOUNT.value, cdiscount.fetch_price, True),
        (PriceSource.CULTURA.value, cultura.fetch_price, False),
        (PriceSource.FNAC.value, fnac.fetch_price, True),
        (PriceSource.KING_JOUET.value, king_jouet.fetch_price, True),
        (PriceSource.LA_GRANDE_RECRE.value, la_grande_recre.fetch_price, True),
        (PriceSource.JOUECLUB.value, joueclub.fetch_price, True),
        (PriceSource.CARREFOUR.value, carrefour.fetch_price, True),
        (PriceSource.INTERMARCHE.value, intermarche.fetch_price, True),
    )


async def _run_source[T](
    source: str,
    operation: Callable[[], Awaitable[T]],
    on_progress: SourceProgressCallback | None = None,
    *,
    browser_backed: bool = False,
    on_captcha: CaptchaRequiredCallback | None = None,
    bypass_cooldown: bool = False,
) -> T | None:
    if on_progress:
        on_progress(source, "started")
    unavailable_until = _source_unavailable_until.get(source, 0)
    if browser_backed and not bypass_cooldown and unavailable_until > time.monotonic():
        logger.info("Source %s ignorée temporairement après son dernier échec", source)
        if on_progress:
            on_progress(
                source,
                "captcha_required" if source in _captcha_required_until else "skipped",
            )
        return None
    try:
        if browser_backed:
            # Waiting for a slot is not a source timeout: only two heavy pages may render at once,
            # so later retailers legitimately queue behind earlier ones. The enclosing set deadline
            # still bounds the whole queue.
            async with _web_source_slots:
                async with asyncio.timeout(settings.price_source_timeout_seconds):
                    result = await operation()
        else:
            async with asyncio.timeout(settings.price_source_timeout_seconds):
                result = await operation()
    except TimeoutError:
        if browser_backed:
            _source_unavailable_until[source] = (
                time.monotonic() + _SOURCE_FAILURE_COOLDOWN_SECONDS
            )
        logger.warning(
            "Source %s abandonnée pour dépassement du délai de %.0f s",
            source,
            settings.price_source_timeout_seconds,
        )
        if on_progress:
            on_progress(source, "timed_out")
        return None
    except asyncio.CancelledError:
        if on_progress:
            on_progress(source, "cancelled")
        raise
    except ScrapeBlocked as error:
        until = time.monotonic() + _SOURCE_FAILURE_COOLDOWN_SECONDS
        _source_unavailable_until[source] = until
        _captcha_required_until[source] = until
        logger.info("Source %s : CAPTCHA requis (%s)", source, error.reason)
        if on_captcha:
            on_captcha(source, error)
        if on_progress:
            on_progress(source, "captcha_required")
        return None
    except Exception as error:  # noqa: BLE001 - one source failing must not hide the others
        if browser_backed:
            _source_unavailable_until[source] = (
                time.monotonic() + _SOURCE_FAILURE_COOLDOWN_SECONDS
            )
        logger.info("Source %s indisponible : %s", source, error)
        if on_progress:
            on_progress(source, "failed")
        return None
    if on_progress:
        on_progress(source, "completed")
    clear_captcha_requirement(source)
    return result


async def _cancel_tasks(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def fetch_prices(
    session: AsyncSession, lego_set: LegoSet, *, bricklink_only: bool = False
) -> list[PriceQuote]:
    """Every marketplace quote for a set, fetched concurrently.

    A minifig (`fig-…`) skips lego.com and every external retail source entirely: it is never sold
    at retail on its own, so scraping them would only burn requests and produce misleading
    "Indisponible" rows.
    `bricklink_only` is the background-pass mode — there is no browser to drive from a scheduler
    tick, and BrickLink is a plain signed API call.
    """
    async def bricklink_quotes() -> list[PriceQuote]:
        found = await _run_source(
            "bricklink",
            lambda: bricklink.fetch_prices(session, lego_set),
        )
        return found or []

    if bricklink_only or is_minifig(lego_set.set_num) or not settings.scraping_enabled:
        return await bricklink_quotes()

    async def scraped(
        source: str,
        fetch: Callable[[LegoSet], Awaitable[PriceQuote | None]],
        browser_backed: bool,
    ) -> list[PriceQuote]:
        quote = await _run_source(
            source,
            lambda: fetch(lego_set),
            browser_backed=browser_backed,
        )
        return [quote] if quote else []

    tasks = [asyncio.create_task(bricklink_quotes())]
    tasks.extend(
        asyncio.create_task(scraped(source, fetch, browser_backed))
        for source, fetch, browser_backed in _retail_fetchers()
    )
    try:
        results = await asyncio.gather(*tasks)
    finally:
        await _cancel_tasks(tasks)
    return [quote for result in results for quote in result]


async def _read_store_price(set_num: str) -> StorePrice | None:
    if not settings.scraping_enabled or is_minifig(set_num):
        return None
    try:
        return await scrape_store_price(set_num)
    except LegoStoreError as error:
        logger.debug("lego.com : %s (%s)", error, set_num)
        return None


async def fetch_store_price(session: AsyncSession, set_num: str) -> StorePrice | None:
    """The lego.com retail price, persisted on success.

    Deliberately separate from `fetch_prices`: it is by far the slowest source (a full page load
    plus a Cloudflare challenge), and several callers want the marketplace quotes without paying
    for it.
    """
    price = await _run_source(
        "legoStore",
        lambda: _read_store_price(set_num),
        browser_backed=True,
    )
    if price is None:
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
    on_progress: SourceProgressCallback | None = None,
    on_captcha: CaptchaRequiredCallback | None = None,
    bypass_cooldown: bool = False,
) -> dict[str, object]:
    """One set's full refresh: every source, persisted, then alerts evaluated once.

    The price rows are written incrementally as each source answers so the UI can start showing a
    retailer price before the last browser scrape finishes. Live refreshes still reconcile the final
    result set once all sources are done, but a partial commit is never delayed until the last one.

    `reconcile=True` is correct only for a genuine live fetch — it deletes cached sources absent
    from this result, so a source that went silent stops showing its last known price. A cache-only
    or partial write must pass False, where an empty result can't be told apart from a hiccup.
    """
    try:
        async with asyncio.timeout(settings.price_refresh_timeout_seconds):
            return await _refresh_set_prices(
                session,
                lego_set,
                reconcile=reconcile,
                include_store=include_store,
                mark_fetched=mark_fetched,
                on_progress=on_progress,
                on_captcha=on_captcha,
                bypass_cooldown=bypass_cooldown,
            )
    except TimeoutError as exc:
        logger.warning(
            "Rafraîchissement de %s abandonné après %.0f s",
            lego_set.set_num,
            settings.price_refresh_timeout_seconds,
        )
        raise PriceRefreshTimeout(
            f"Le rafraîchissement de {lego_set.set_num} a dépassé "
            f"{settings.price_refresh_timeout_seconds:.0f} s"
        ) from exc


async def _refresh_set_prices(
    session: AsyncSession,
    lego_set: LegoSet,
    *,
    reconcile: bool,
    include_store: bool,
    mark_fetched: bool,
    on_progress: SourceProgressCallback | None,
    on_captcha: CaptchaRequiredCallback | None,
    bypass_cooldown: bool,
) -> dict[str, object]:
    set_num = lego_set.set_num
    skipped_sources: set[str] = set()

    def report_progress(source: str, status: SourceProgressStatus) -> None:
        if status in ("skipped", "captcha_required"):
            skipped_sources.add(source)
        if on_progress:
            on_progress(source, status)

    async def isolated_bricklink() -> list[PriceQuote]:
        # Streaming retailer results are persisted on the caller's session while BrickLink may still
        # be resolving an item. It therefore needs its own session: AsyncSession is not task-safe.
        async with session_scope() as bricklink_session:
            return await bricklink.fetch_prices(bricklink_session, lego_set)

    async def quote_output(
        source: str,
        operation: Callable[[], Awaitable[list[PriceQuote] | PriceQuote | None]],
        *,
        browser_backed: bool = False,
    ) -> _SourceOutput:
        found = await _run_source(
            source,
            operation,
            report_progress,
            browser_backed=browser_backed,
            on_captcha=on_captcha,
            bypass_cooldown=bypass_cooldown,
        )
        if isinstance(found, list):
            return _SourceOutput(quotes=found)
        return _SourceOutput(quotes=[found] if found else [])

    async def store_output() -> _SourceOutput:
        found = await _run_source(
            "legoStore",
            lambda: _read_store_price(set_num),
            report_progress,
            browser_backed=True,
            on_captcha=on_captcha,
            bypass_cooldown=bypass_cooldown,
        )
        return _SourceOutput(store_price=found)

    tasks: list[asyncio.Task] = [
        asyncio.create_task(quote_output("bricklink", isolated_bricklink))
    ]
    if not is_minifig(set_num) and settings.scraping_enabled:
        tasks.extend(
            asyncio.create_task(
                quote_output(
                    source,
                    lambda fetch=fetch: fetch(lego_set),
                    browser_backed=browser_backed,
                )
            )
            for source, fetch, browser_backed in _retail_fetchers()
        )
        if include_store:
            tasks.append(asyncio.create_task(store_output()))

    quotes: list[PriceQuote] = []
    store_price: StorePrice | None = None
    try:
        for completed in asyncio.as_completed(tasks):
            output = await completed
            if output.quotes is not None:
                if output.quotes:
                    await collection_repo.cache_prices(
                        session,
                        output.quotes,
                        set_num,
                        reconcile=False,
                    )
                    quotes.extend(output.quotes)
            elif output.store_price is not None:
                store_price = output.store_price
                await collection_repo.cache_store_price(session, set_num, store_price)
    finally:
        await _cancel_tasks(tasks)

    if reconcile:
        await collection_repo.cache_prices(
            session,
            quotes,
            set_num,
            reconcile=True,
            preserve_sources=skipped_sources,
        )
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


async def refresh_retail_source(
    session: AsyncSession,
    lego_set: LegoSet,
    source: str,
    *,
    on_captcha: CaptchaRequiredCallback | None = None,
    on_progress: SourceProgressCallback | None = None,
) -> PriceQuote | None:
    """Retries one challenged retailer in the shared context after human validation."""
    selected = next(
        (
            (fetch, browser_backed)
            for key, fetch, browser_backed in _retail_fetchers()
            if key == source
        ),
        None,
    )
    if selected is None:
        raise ValueError(f"Source retail inconnue : {source}")
    fetch, browser_backed = selected
    quote = await _run_source(
        source,
        lambda: fetch(lego_set),
        on_progress,
        browser_backed=browser_backed,
        on_captcha=on_captcha,
        bypass_cooldown=True,
    )
    if quote is not None:
        await collection_repo.cache_prices(
            session,
            [quote],
            lego_set.set_num,
            reconcile=False,
        )
        await alerts.evaluate_alerts(session, lego_set.set_num)
    return quote
