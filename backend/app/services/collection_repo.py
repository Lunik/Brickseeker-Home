"""Port of the iOS `LocalRepository` — the one writer of the collection and price caches.

Three rules the rest of the app leans on. Every function here either upholds one or would
silently break it:

* **`CachedSet.was_scanned` says why a row exists**, not what it is (scan → History, sync →
  Collection, a set can be both). Only `mark_as_scanned` may set it — reopening a set from
  Collection or Statistiques must not bump it to the top of History (#133).
* **Hand-entered data outlives the caches.** `clear_cache` wipes the five reconstructible tables
  and nothing else; a threshold, a paid price or a past day's valuation cannot be re-fetched.
* **One repo call is one unit of work.** `get_session` hands out an uncommitted session, so every
  writer here commits, exactly where the original called `modelContext.save()`.

Routers never touch the price tables: quotes go in and come back out as `pricing.PriceQuote`, and
the row ↔ quote conversion lives here.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CachedSet,
    CachedSetList,
    CachedSetPrice,
    CollectionSyncState,
    CollectionValueSnapshot,
    PriceAlert,
    PriceHistoryEntry,
    ScanEvent,
    SetPurchaseRecord,
    SoldListing,
)
from .pricing import LEGO_STORE_HISTORY_SOURCE, ListCondition, PriceQuote, PriceSource, SoldSale
from .rebrickable import LegoSet, SetList, UserSet

if TYPE_CHECKING:
    from .scraping.lego_store import StorePrice

#: Matches the iOS trim in `recordPriceHistory` — the chart only ever plots six months.
PRICE_HISTORY_RETENTION_DAYS = 180

#: Four years of daily collection valuations, the depth BrickEconomy's `periods` used to expose.
SNAPSHOT_RETENTION_DAYS = 1460

#: SQLite caps bound parameters per statement (999 on builds older than 3.32). A several-hundred
#: set collection reaches that in a single `IN`, so the large ones are chunked.
_IN_CHUNK = 400

#: Owned/wishlist listings sort like the iOS `SortDescriptor(\.name)` did, which folded case;
#: SQLite's default binary collation would file every lowercase name after "Zzz".
_BY_NAME = CachedSet.name.collate("NOCASE")


@dataclass(slots=True, frozen=True)
class PriceWatchTarget:
    """One set the background refresher is allowed to fetch, with the date it comes due."""

    lego_set: LegoSet
    #: Aware UTC: SQLite hands datetimes back naive, and the refresher compares this against
    #: `datetime.now(UTC)`.
    due_at: datetime


# --------------------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """Every stored datetime is UTC, but SQLite drops the offset — re-attaching it is what keeps a
    read-back value comparable with `datetime.now(UTC)` instead of raising."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _day_key(moment: datetime) -> str:
    """Zero-padded so plain lexicographic order is also chronological — both the retention purge
    and the chart's sort rely on that."""
    return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"


def _condition(raw: str | None) -> ListCondition:
    try:
        return ListCondition(raw or "")
    except ValueError:
        return ListCondition.NEW


def _in_chunks(values: Sequence[str], size: int = _IN_CHUNK) -> Iterator[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def to_lego_set(cached: CachedSet) -> LegoSet:
    """Port of `CachedSet.asLegoSet()` — every screen that reads the cache needs it."""
    return LegoSet(
        set_num=cached.set_num,
        name=cached.name,
        year=cached.year,
        theme_id=cached.theme_id,
        num_parts=cached.num_parts,
        set_img_url=cached.set_img_url,
        set_url=cached.set_url,
    )


def _to_quote(row: CachedSetPrice) -> PriceQuote | None:
    """`None` for a source this build doesn't know — one unreadable row must not poison the list.

    `sales` stays `None` on purpose: a cache-rebuilt quote says nothing about sold listings, and
    `cache_prices` treats `[]` as "a live fetch found none" and would clear the stored rows.
    """
    try:
        source = PriceSource(row.source)
    except ValueError:
        return None
    return PriceQuote(
        source=source,
        amount=row.amount,
        currency=row.currency,
        source_url=row.source_url,
        fetched_at=_aware(row.fetched_at),
        min_amount=row.min_amount,
        max_amount=row.max_amount,
        lot_count=row.lot_count,
    )


def _new_cached_set(
    lego_set: LegoSet,
    *,
    is_in_collection: bool = False,
    list_id: int | None = None,
    list_name: str | None = None,
) -> CachedSet:
    return CachedSet(
        set_num=lego_set.set_num,
        name=lego_set.name,
        year=lego_set.year,
        theme_id=lego_set.theme_id,
        num_parts=lego_set.num_parts,
        set_img_url=lego_set.set_img_url,
        set_url=lego_set.set_url,
        last_scanned_at=_now(),
        is_in_collection=is_in_collection,
        current_list_id=list_id,
        current_list_name=list_name,
    )


# --------------------------------------------------------------------------------------
# Cached sets
# --------------------------------------------------------------------------------------


async def cache_set(
    session: AsyncSession,
    lego_set: LegoSet,
    *,
    is_in_collection: bool,
    list_id: int | None = None,
    list_name: str | None = None,
    mark_as_scanned: bool,
) -> CachedSet:
    """Upserts the catalogue half unconditionally, the scanned half only when asked.

    Name/collection status/list are always worth refreshing whatever brought the user here;
    `was_scanned`/`last_scanned_at` decide whether — and where in History's order — the set
    appears as scanned, so a detail-view reconcile passes `mark_as_scanned=False` (#133).
    """
    existing = await session.get(CachedSet, lego_set.set_num)
    if existing is not None:
        existing.name = lego_set.name
        existing.year = lego_set.year
        existing.theme_id = lego_set.theme_id
        existing.num_parts = lego_set.num_parts
        existing.set_img_url = lego_set.set_img_url
        existing.set_url = lego_set.set_url
        if mark_as_scanned:
            existing.was_scanned = True
            existing.last_scanned_at = _now()
        existing.is_in_collection = is_in_collection
        existing.current_list_id = list_id
        existing.current_list_name = list_name
        cached = existing
    else:
        cached = _new_cached_set(
            lego_set, is_in_collection=is_in_collection, list_id=list_id, list_name=list_name
        )
        cached.was_scanned = mark_as_scanned
        session.add(cached)

    if is_in_collection:
        await _enter_collection(session, lego_set.set_num)
    await session.commit()
    return cached


async def _enter_collection(session: AsyncSession, set_num: str) -> None:
    """What "this set is now owned" implies beyond the flag itself.

    The location's only purpose is "in which store did I see this deal", moot once the set is
    bought (#46) — and the in-store price the user typed becomes the purchase record, since
    "I saw it at 39,99 € and bought it" is the common case and re-typing it would be busywork.
    """
    await _strip_scan_locations(session, {set_num})
    await _seed_paid_price_from_scan(session, set_num)


async def cached_set(session: AsyncSession, set_num: str) -> CachedSet | None:
    return await session.get(CachedSet, set_num)


async def owned_sets(session: AsyncSession) -> list[CachedSet]:
    rows = await session.execute(select(CachedSet).where(CachedSet.is_in_collection).order_by(_BY_NAME))
    return list(rows.scalars().all())


async def scanned_sets(session: AsyncSession) -> list[CachedSet]:
    rows = await session.execute(
        select(CachedSet).where(CachedSet.was_scanned).order_by(CachedSet.last_scanned_at.desc())
    )
    return list(rows.scalars().all())


async def wishlist_sets(session: AsyncSession) -> list[CachedSet]:
    rows = await session.execute(select(CachedSet).where(CachedSet.is_in_wishlist).order_by(_BY_NAME))
    return list(rows.scalars().all())


async def counts(session: AsyncSession) -> dict[str, int]:
    """The Accueil tiles. `totalScans` counts scan *events* — the iOS `ScanStatsStore` counter,
    which `ScanEvent` now supersedes: a set scanned five times is one scanned set, five scans."""
    scanned = await session.scalar(select(func.count()).select_from(CachedSet).where(CachedSet.was_scanned))
    total_scans = await session.scalar(select(func.count()).select_from(ScanEvent))
    owned = await session.scalar(
        select(func.count()).select_from(CachedSet).where(CachedSet.is_in_collection)
    )
    wishlist = await session.scalar(
        select(func.count()).select_from(CachedSet).where(CachedSet.is_in_wishlist)
    )
    return {
        "scannedSets": scanned or 0,
        "totalScans": total_scans or 0,
        "ownedSets": owned or 0,
        "wishlistSets": wishlist or 0,
    }


async def set_collection_status(
    session: AsyncSession,
    set_num: str,
    *,
    is_in_collection: bool,
    list_id: int | None = None,
    list_name: str | None = None,
) -> None:
    """The collection-status half of `cache_set`, for the bulk actions menu (#141): those callers
    only mirror a remote move/add/remove that already succeeded and hold no `LegoSet` to upsert.
    No-ops when no row exists."""
    existing = await session.get(CachedSet, set_num)
    if existing is None:
        return
    existing.is_in_collection = is_in_collection
    existing.current_list_id = list_id
    existing.current_list_name = list_name
    if is_in_collection:
        await _enter_collection(session, set_num)
    await session.commit()


async def set_wishlist_status(session: AsyncSession, set_num: str, is_in_wishlist: bool) -> None:
    """No-ops without a row: wishlist status is only meaningful on a set already reached through
    the resolve flow, which caches one first."""
    existing = await session.get(CachedSet, set_num)
    if existing is None:
        return
    existing.is_in_wishlist = is_in_wishlist
    await session.commit()


async def set_quantity(session: AsyncSession, set_num: str, quantity: int) -> None:
    """Its own setter rather than a `cache_set` argument — `cache_set` never touches `quantity`,
    only `sync_collection`'s full reconcile does."""
    existing = await session.get(CachedSet, set_num)
    if existing is None:
        return
    existing.quantity = quantity
    await session.commit()


async def cached_set_nums(session: AsyncSession) -> set[str]:
    rows = await session.execute(select(CachedSet.set_num))
    return set(rows.scalars().all())


async def cache_wishlist_set(session: AsyncSession, lego_set: LegoSet) -> None:
    """Inserts a wishlist-only row for a set never scanned or owned — without it a wanted set
    would appear nowhere in the app. No-ops when a row already exists."""
    if await session.get(CachedSet, lego_set.set_num) is not None:
        return
    cached = _new_cached_set(lego_set)
    cached.was_scanned = False
    cached.is_in_wishlist = True
    session.add(cached)
    await session.commit()


# --------------------------------------------------------------------------------------
# Full sync
# --------------------------------------------------------------------------------------


async def sync_collection(
    session: AsyncSession, user_sets: Sequence[UserSet], lists: Sequence[SetList]
) -> None:
    """Full collection reconcile — the offline cache behind Collection, distinct from the always
    live per-set status check.

    Deliberately does **not** seed purchase records: a set added from the Rebrickable website
    would inherit a shelf price this install never witnessed. Its own detail screen seeds it on
    the next open, through `cache_set`.
    """
    # External API data: a duplicated list id must not crash the sync.
    list_name_by_id: dict[int, str] = {}
    for set_list in lists:
        list_name_by_id.setdefault(set_list.id, set_list.name)

    # A set owned in several lists is returned once per list; `CachedSet` assumes one current
    # list per set, so the first occurrence wins.
    first_by_set_num: dict[str, UserSet] = {}
    for user_set in user_sets:
        first_by_set_num.setdefault(user_set.lego_set.set_num, user_set)

    # One indexed fetch of the whole cache instead of one per owned set (a 500-set collection used
    # to mean 500 queries per sync). The same rows serve the "gone from the collection" pass.
    all_cached = list((await session.execute(select(CachedSet))).scalars().all())
    cached_by_set_num = {row.set_num: row for row in all_cached}

    now = _now()
    for set_num, user_set in first_by_set_num.items():
        lego_set = user_set.lego_set
        list_name = list_name_by_id.get(user_set.list_id) if user_set.list_id is not None else None
        existing = cached_by_set_num.get(set_num)
        if existing is not None:
            existing.name = lego_set.name
            existing.year = lego_set.year
            existing.theme_id = lego_set.theme_id
            existing.num_parts = lego_set.num_parts
            existing.set_img_url = lego_set.set_img_url
            existing.set_url = lego_set.set_url
            existing.quantity = user_set.quantity
            existing.is_in_collection = True
            existing.current_list_id = user_set.list_id
            existing.current_list_name = list_name
            existing.last_synced_at = now
        else:
            cached = _new_cached_set(
                lego_set, is_in_collection=True, list_id=user_set.list_id, list_name=list_name
            )
            cached.was_scanned = False
            cached.quantity = user_set.quantity
            cached.last_synced_at = now
            session.add(cached)

    # A row that left the collection but was scanned stays as a History row, losing only its
    # collection fields; a sync-only row has nothing left to justify it and goes.
    owned_set_nums = set(first_by_set_num)
    for row in all_cached:
        if not row.is_in_collection or row.set_num in owned_set_nums:
            continue
        if row.was_scanned:
            row.is_in_collection = False
            row.current_list_id = None
            row.current_list_name = None
        else:
            await session.delete(row)

    await _strip_scan_locations(session, owned_set_nums)
    await _cache_set_lists(session, lists)

    state = (await session.execute(select(CollectionSyncState).limit(1))).scalars().first()
    if state is None:
        session.add(CollectionSyncState(id=1, last_full_sync_at=now))
    else:
        state.last_full_sync_at = now
    await session.commit()


async def sync_wishlist(session: AsyncSession, wanted_set_nums: set[str]) -> None:
    """Reconciles `is_in_wishlist` on every *already cached* row against Brickset's wanted list.
    Never creates rows (there is no `LegoSet` data here to build one from) — pair with
    `cached_set_nums`/`cache_wishlist_set` to cover wanted sets with no local row yet."""
    rows = (await session.execute(select(CachedSet))).scalars().all()
    for row in rows:
        should_be_wanted = row.set_num in wanted_set_nums
        if row.is_in_wishlist != should_be_wanted:
            row.is_in_wishlist = should_be_wanted

    now = _now()
    state = (await session.execute(select(CollectionSyncState).limit(1))).scalars().first()
    if state is None:
        session.add(CollectionSyncState(id=1, last_wishlist_sync_at=now))
    else:
        state.last_wishlist_sync_at = now
    await session.commit()


async def last_full_sync_at(session: AsyncSession) -> datetime | None:
    state = (await session.execute(select(CollectionSyncState).limit(1))).scalars().first()
    if state is None or state.last_full_sync_at is None:
        return None
    return _aware(state.last_full_sync_at)


async def last_wishlist_sync_at(session: AsyncSession) -> datetime | None:
    state = (await session.execute(select(CollectionSyncState).limit(1))).scalars().first()
    if state is None or state.last_wishlist_sync_at is None:
        return None
    return _aware(state.last_wishlist_sync_at)


# --------------------------------------------------------------------------------------
# Set lists
# --------------------------------------------------------------------------------------


async def _cache_set_lists(session: AsyncSession, set_lists: Sequence[SetList]) -> None:
    rows = (await session.execute(select(CachedSetList))).scalars().all()
    cached_by_list_id = {row.list_id: row for row in rows}
    now = _now()
    for set_list in set_lists:
        existing = cached_by_list_id.get(set_list.id)
        if existing is not None:
            # `condition` is a local annotation, not Rebrickable's — a sync must never reset it.
            existing.name = set_list.name
            existing.num_sets = set_list.num_sets
            existing.last_fetched_at = now
        else:
            inserted = CachedSetList(
                list_id=set_list.id, name=set_list.name, num_sets=set_list.num_sets, last_fetched_at=now
            )
            session.add(inserted)
            cached_by_list_id[set_list.id] = inserted


async def cache_set_lists(session: AsyncSession, set_lists: Sequence[SetList]) -> None:
    await _cache_set_lists(session, set_lists)
    await session.commit()


async def cached_set_lists(session: AsyncSession) -> list[CachedSetList]:
    rows = await session.execute(select(CachedSetList).order_by(CachedSetList.name.collate("NOCASE")))
    return list(rows.scalars().all())


async def condition_by_list_id(session: AsyncSession) -> dict[int, ListCondition]:
    """Batch form for the collection-wide screens, so they don't issue one query per row."""
    rows = await session.execute(select(CachedSetList.list_id, CachedSetList.condition))
    return {list_id: _condition(raw) for list_id, raw in rows.all()}


async def set_list_condition(session: AsyncSession, list_id: int, condition: ListCondition) -> None:
    existing = await session.get(CachedSetList, list_id)
    if existing is None:
        return
    existing.condition = ListCondition(condition).value
    await session.commit()


# --------------------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------------------


async def cache_store_price(session: AsyncSession, set_num: str, store_price: StorePrice) -> None:
    """No-ops without a row — the price is only meaningful attached to a set already cached."""
    existing = await session.get(CachedSet, set_num)
    if existing is None:
        return
    existing.store_price_eur = store_price.amount
    existing.store_availability = store_price.availability
    existing.store_price_fetched_at = _now()
    if store_price.amount is not None:
        await record_price_history(
            session, set_num, LEGO_STORE_HISTORY_SOURCE, store_price.amount, store_price.currency or "EUR"
        )
    await session.commit()


async def mark_prices_fetched(session: AsyncSession, set_num: str) -> None:
    """Stamped once *every* source has been tried, price found or not — that is what stops
    "Compléter les prix manquants" from re-offering a definitively unfindable set forever
    (#194). No-ops without a row."""
    existing = await session.get(CachedSet, set_num)
    if existing is None:
        return
    existing.prices_fetched_at = _now()
    await session.commit()


async def cache_prices(
    session: AsyncSession, quotes: Sequence[PriceQuote], set_num: str, *, reconcile: bool = False
) -> None:
    """`reconcile=True` only ever for a genuine live fetch: it drops cached sources absent from
    `quotes`, so a source that went "Indisponible" stops showing its last known price. A
    cache-only or partial write (the batch updater) cannot tell an empty result from a network
    hiccup, and since prices never expire (#244) a wrongly reconciled row would need another live
    fetch to come back.
    """
    rows = list(
        (await session.execute(select(CachedSetPrice).where(CachedSetPrice.set_num == set_num)))
        .scalars()
        .all()
    )
    cached_by_source: dict[str, CachedSetPrice] = {}
    for row in rows:
        cached_by_source.setdefault(row.source, row)

    if reconcile:
        fetched_sources = {quote.source.value for quote in quotes}
        for row in rows:
            if row.source not in fetched_sources:
                await session.delete(row)

    now = _now()
    for quote in quotes:
        source = quote.source.value
        existing = cached_by_source.get(source)
        if existing is not None:
            existing.amount = quote.amount
            existing.currency = quote.currency
            existing.source_url = quote.source_url
            existing.fetched_at = quote.fetched_at or now
            # Assigned unconditionally, `None` included: a source that stopped reporting a range
            # must not keep showing the previous refresh's numbers beside a fresh average.
            existing.min_amount = quote.min_amount
            existing.max_amount = quote.max_amount
            existing.lot_count = quote.lot_count
        else:
            inserted = CachedSetPrice(
                set_num=set_num,
                source=source,
                amount=quote.amount,
                currency=quote.currency,
                source_url=quote.source_url,
                fetched_at=quote.fetched_at or now,
                min_amount=quote.min_amount,
                max_amount=quote.max_amount,
                lot_count=quote.lot_count,
            )
            session.add(inserted)
            # A source repeated within `quotes` updates the pending row instead of inserting a
            # second one, which the (set_num, source) unique constraint would reject.
            cached_by_source[source] = inserted

        await record_price_history(session, set_num, source, quote.amount, quote.currency)
        # Only a quote carrying sales information may rewrite the stored rows: `None` means "says
        # nothing about sales" (a cache-rebuilt quote), `[]` is a live fetch that found none.
        if quote.sales is not None:
            await _replace_sold_listings(session, set_num, source, quote.sales, quote.currency)

    await session.commit()


async def _replace_sold_listings(
    session: AsyncSession, set_num: str, source: str, sales: Sequence[SoldSale], currency: str
) -> None:
    """Wholesale replacement, never an append (#214): BrickLink re-sends its entire 6-month window
    on every refresh, so appending would multiply each sale by the number of refreshes."""
    await session.execute(
        delete(SoldListing).where(SoldListing.set_num == set_num, SoldListing.source == source)
    )
    fetched_at = _now()
    for sale in sales:
        session.add(
            SoldListing(
                set_num=set_num,
                source=source,
                unit_amount=sale.unit_amount,
                quantity=sale.quantity,
                ordered_at=sale.ordered_at,
                currency=currency,
                fetched_at=fetched_at,
            )
        )


async def cached_prices(session: AsyncSession, set_num: str) -> list[PriceQuote]:
    """Every cached quote for a set, whatever its age (#244) — a stale price is captioned by the
    UI, never dropped here."""
    rows = (
        (await session.execute(select(CachedSetPrice).where(CachedSetPrice.set_num == set_num)))
        .scalars()
        .all()
    )
    return [quote for quote in (_to_quote(row) for row in rows) if quote is not None]


async def all_cached_prices(session: AsyncSession) -> dict[str, list[PriceQuote]]:
    """Every cached quote in one query, for the collection-wide screens (valuation, Statistiques,
    exports). Calling `cached_prices` per set is one query per set — hundreds per recompute."""
    rows = (await session.execute(select(CachedSetPrice))).scalars().all()
    by_set_num: dict[str, list[PriceQuote]] = {}
    for row in rows:
        quote = _to_quote(row)
        if quote is not None:
            by_set_num.setdefault(row.set_num, []).append(quote)
    return by_set_num


async def record_price_history(
    session: AsyncSession, set_num: str, source: str, amount: float, currency: str
) -> None:
    """One reading per (set, source, calendar day) — opening SetDetail five times must not stack
    five points — and nothing older than 180 days. The caller commits."""
    latest = await session.scalar(
        select(PriceHistoryEntry.fetched_at)
        .where(PriceHistoryEntry.set_num == set_num, PriceHistoryEntry.source == source)
        .order_by(PriceHistoryEntry.fetched_at.desc())
        .limit(1)
    )
    now = _now()
    if latest is not None and _aware(latest).date() == now.date():
        return

    session.add(
        PriceHistoryEntry(
            set_num=set_num, source=source, amount=amount, currency=currency, fetched_at=now
        )
    )
    cutoff = now - timedelta(days=PRICE_HISTORY_RETENTION_DAYS)
    await session.execute(
        delete(PriceHistoryEntry).where(
            PriceHistoryEntry.set_num == set_num,
            PriceHistoryEntry.source == source,
            PriceHistoryEntry.fetched_at < cutoff,
        )
    )


async def price_history(session: AsyncSession, set_num: str) -> list[PriceHistoryEntry]:
    """Oldest first — the series the SetDetail chart plots."""
    rows = await session.execute(
        select(PriceHistoryEntry)
        .where(PriceHistoryEntry.set_num == set_num)
        .order_by(PriceHistoryEntry.fetched_at)
    )
    return list(rows.scalars().all())


async def sold_listings(session: AsyncSession, set_num: str) -> list[SoldListing]:
    """Both conditions, oldest first; filtering to the set's own is the caller's call."""
    rows = await session.execute(
        select(SoldListing).where(SoldListing.set_num == set_num).order_by(SoldListing.ordered_at)
    )
    return list(rows.scalars().all())


# --------------------------------------------------------------------------------------
# Purchase records
# --------------------------------------------------------------------------------------


async def paid_price(session: AsyncSession, set_num: str) -> float | None:
    """Needs no `CachedSet` row: the purchase record is deliberately independent of the caches."""
    record = await session.get(SetPurchaseRecord, set_num)
    return record.paid_price_eur if record else None


async def paid_price_by_set_num(session: AsyncSession) -> dict[str, float]:
    rows = await session.execute(select(SetPurchaseRecord.set_num, SetPurchaseRecord.paid_price_eur))
    return dict(rows.all())


async def set_paid_price(session: AsyncSession, set_num: str, paid_price_eur: float | None) -> None:
    """`None` clears the record, so the growth figure falls back to the retail basis rather than
    keeping a stale number."""
    existing = await session.get(SetPurchaseRecord, set_num)
    if paid_price_eur is None or paid_price_eur <= 0:
        if existing is not None:
            await session.delete(existing)
        await session.commit()
        return
    if existing is not None:
        existing.paid_price_eur = paid_price_eur
        existing.recorded_at = _now()
    else:
        session.add(SetPurchaseRecord(set_num=set_num, paid_price_eur=paid_price_eur))
    await session.commit()


async def _seed_paid_price_from_scan(session: AsyncSession, set_num: str) -> None:
    """Idempotent: never overwrites an existing record, so a hand-edited price survives a later
    re-add or sync. Takes the **most recent** priced scan — the purchase follows the last look at
    the shelf, which is a different question from SetDetail's "where was it cheapest?".
    """
    if await session.get(SetPurchaseRecord, set_num) is not None:
        return
    price = await session.scalar(
        select(ScanEvent.price_seen_eur)
        .where(ScanEvent.set_num == set_num, ScanEvent.price_seen_eur.is_not(None))
        .order_by(ScanEvent.scanned_at.desc(), ScanEvent.id.desc())
        .limit(1)
    )
    if price is None or price <= 0:
        return
    session.add(SetPurchaseRecord(set_num=set_num, paid_price_eur=price))


# --------------------------------------------------------------------------------------
# Scan events
# --------------------------------------------------------------------------------------


async def record_scan_event(
    session: AsyncSession, set_num: str, price_seen_eur: float | None = None
) -> ScanEvent:
    """Camera scans only — a manual entry or a History re-open carries no "I was standing in a
    store" meaning. Returned so the caller can attach a late location fix."""
    event = ScanEvent(set_num=set_num, scanned_at=_now(), price_seen_eur=price_seen_eur)
    session.add(event)
    await session.commit()
    return event


async def update_scan_event_price(
    session: AsyncSession, event_id: int, price_seen_eur: float | None
) -> None:
    event = await session.get(ScanEvent, event_id)
    if event is None:
        return
    event.price_seen_eur = price_seen_eur
    await session.commit()


async def attach_location(
    session: AsyncSession, event_id: int, lat: float, lon: float, place_name: str | None = None
) -> None:
    """No-ops once the set is owned: the strip-on-add rule has to win the race against a slow GPS
    fix, or a just-bought set ends up located anyway."""
    event = await session.get(ScanEvent, event_id)
    if event is None:
        return
    owner = await session.get(CachedSet, event.set_num)
    if owner is not None and owner.is_in_collection:
        return
    event.latitude = lat
    event.longitude = lon
    event.place_name = place_name
    await session.commit()


async def _strip_scan_locations(session: AsyncSession, set_nums: set[str] | None) -> None:
    if set_nums is not None and not set_nums:
        return
    targets = sorted(set_nums) if set_nums is not None else None
    if targets is None:
        await session.execute(
            update(ScanEvent)
            .where(ScanEvent.latitude.is_not(None))
            .values(latitude=None, longitude=None, place_name=None)
        )
        return
    for chunk in _in_chunks(targets):
        await session.execute(
            update(ScanEvent)
            .where(ScanEvent.latitude.is_not(None), ScanEvent.set_num.in_(chunk))
            .values(latitude=None, longitude=None, place_name=None)
        )


async def strip_scan_locations(session: AsyncSession, set_nums: set[str] | None) -> None:
    """Clears the location fields, never the rows — the "when did I scan this" history stays.
    `None` strips everything (history purge, cache clear)."""
    await _strip_scan_locations(session, set_nums)
    await session.commit()


async def scan_events(session: AsyncSession, set_num: str | None = None) -> list[ScanEvent]:
    """Newest first."""
    stmt = select(ScanEvent).order_by(ScanEvent.scanned_at.desc(), ScanEvent.id.desc())
    if set_num is not None:
        stmt = stmt.where(ScanEvent.set_num == set_num)
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def delete_scan_event(session: AsyncSession, event_id: int) -> None:
    """Never touches `CachedSet`, except that `last_scanned_at` is recomputed from the remaining
    rows when the deleted event was the most recent one — it would otherwise keep pointing at a
    scan that no longer exists (#88)."""
    event = await session.get(ScanEvent, event_id)
    if event is None:
        return
    set_num = event.set_num
    newest_id = await session.scalar(
        select(ScanEvent.id)
        .where(ScanEvent.set_num == set_num)
        .order_by(ScanEvent.scanned_at.desc(), ScanEvent.id.desc())
        .limit(1)
    )
    was_newest = newest_id == event.id
    await session.delete(event)

    if was_newest:
        owner = await session.get(CachedSet, set_num)
        if owner is not None:
            remaining = await session.scalar(
                select(ScanEvent.scanned_at)
                .where(ScanEvent.set_num == set_num)
                .order_by(ScanEvent.scanned_at.desc(), ScanEvent.id.desc())
                .limit(1)
            )
            if remaining is not None:
                owner.last_scanned_at = remaining
    await session.commit()


async def delete_from_history(session: AsyncSession, set_num: str) -> None:
    """`CachedSet` is one row shared by History and Collection, so a still-owned set only loses
    `was_scanned` — falling back to a collection-only row, exactly as if it had never been
    scanned. A set no longer owned goes, taking its scan events with it (#88)."""
    cached = await session.get(CachedSet, set_num)
    if cached is None:
        return
    if cached.is_in_collection:
        cached.was_scanned = False
    else:
        await session.delete(cached)
        await session.execute(delete(ScanEvent).where(ScanEvent.set_num == set_num))
    await session.commit()


# --------------------------------------------------------------------------------------
# Price alerts (#229) and the background watch (#230)
# --------------------------------------------------------------------------------------


async def price_alerts(session: AsyncSession, set_num: str | None = None) -> list[PriceAlert]:
    """Newest first. Both of a set's conditions come back — SetDetail shows neuf and occasion as
    two independent rows, because they are two independent alerts."""
    stmt = select(PriceAlert).order_by(PriceAlert.created_at.desc(), PriceAlert.id.desc())
    if set_num is not None:
        stmt = stmt.where(PriceAlert.set_num == set_num)
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def upsert_price_alert(
    session: AsyncSession,
    set_num: str,
    condition: ListCondition,
    *,
    set_name: str = "",
    set_img_url: str | None = None,
    threshold_eur: float | None = None,
    discount_percent: float | None = None,
    reference_price_eur: float | None = None,
    reference_source_name: str | None = None,
    is_enabled: bool = True,
) -> PriceAlert:
    """Creates or replaces the alert for (set, condition). Exactly one of `threshold_eur` /
    `discount_percent` is meaningful; the percentage's reference is resolved by the caller once
    and only stored here.

    Overwriting resets the crossing state: a new threshold is a new question, so the next
    evaluation must be free to fire even though the old one had already reported the price low.
    `is_enabled` is a real argument, not a hardcoded `True` — saving from a sheet whose toggle was
    just switched off must not silently re-arm the alert.
    """
    # Imported here, not at module scope: `alerts.py` reads the cache this module writes, so an
    # eager import would cycle.
    from .alerts import next_due_date

    raw_condition = ListCondition(condition).value
    existing = (
        await session.execute(
            select(PriceAlert).where(PriceAlert.set_num == set_num, PriceAlert.condition == raw_condition)
        )
    ).scalars().first()

    if existing is not None:
        existing.set_name = set_name
        existing.set_img_url = set_img_url
        existing.threshold_eur = threshold_eur
        existing.discount_percent = discount_percent
        existing.reference_price_eur = reference_price_eur
        existing.reference_source_name = reference_source_name
        existing.is_enabled = is_enabled
        existing.was_below_threshold = False
        existing.last_notified_at = None
        alert = existing
    else:
        alert = PriceAlert(
            set_num=set_num,
            condition=raw_condition,
            set_name=set_name,
            set_img_url=set_img_url,
            threshold_eur=threshold_eur,
            discount_percent=discount_percent,
            reference_price_eur=reference_price_eur,
            reference_source_name=reference_source_name,
            is_enabled=is_enabled,
            created_at=_now(),
            next_refresh_due=next_due_date(),
        )
        session.add(alert)
    await session.commit()
    return alert


async def set_price_alert_enabled(session: AsyncSession, alert_id: int, is_enabled: bool) -> None:
    alert = await session.get(PriceAlert, alert_id)
    if alert is None:
        return
    alert.is_enabled = is_enabled
    # Re-arms the crossing detector, so a re-enabled alert can notify on the next evaluation
    # instead of staying silent because the price was already low when it was switched off.
    if is_enabled:
        alert.was_below_threshold = False
    await session.commit()


async def delete_price_alert(session: AsyncSession, alert_id: int) -> None:
    alert = await session.get(PriceAlert, alert_id)
    if alert is None:
        return
    await session.delete(alert)
    await session.commit()


async def price_watch_targets(session: AsyncSession) -> list[PriceWatchTarget]:
    """Everything the background refresher may touch: **only** sets carrying an enabled alert.

    Not the collection and not the gift list (#230). That restricted scope is the whole answer to
    "background polling doesn't scale"; the gift list was in scope and was pulled back out because
    the pass can only query BrickLink, while the gift list displays best(Amazon, Cdiscount) →
    lego.com first — it was ~99 % of the work to keep an invisible series warm. Widening this
    re-opens the decision.
    """
    alerts = (
        (await session.execute(select(PriceAlert).where(PriceAlert.is_enabled))).scalars().all()
    )
    if not alerts:
        return []

    watched = {alert.set_num for alert in alerts}
    cached_rows = (
        (await session.execute(select(CachedSet).where(CachedSet.set_num.in_(watched)))).scalars().all()
    )
    cached_by_set_num = {row.set_num: row for row in cached_rows}

    targets: dict[str, PriceWatchTarget] = {}
    for alert in alerts:
        cached = cached_by_set_num.get(alert.set_num)
        # An alert outlives its `CachedSet` row, so its set can genuinely have none left — hence
        # the copy of the name and image it carries.
        lego_set = (
            to_lego_set(cached)
            if cached is not None
            else LegoSet(
                set_num=alert.set_num,
                name=alert.set_name,
                year=0,
                theme_id=0,
                num_parts=0,
                set_img_url=alert.set_img_url,
                set_url=None,
            )
        )
        due_at = _aware(alert.next_refresh_due)
        # A set can hold two alerts (neuf and occasion) and one fetch serves both, so the earlier
        # due date wins rather than the set being processed twice.
        known = targets.get(alert.set_num)
        if known is not None:
            due_at = min(due_at, known.due_at)
        targets[alert.set_num] = PriceWatchTarget(lego_set=lego_set, due_at=due_at)

    return sorted(targets.values(), key=lambda target: target.due_at)


async def reschedule_watch(session: AsyncSession, set_num: str) -> None:
    """Re-draws the due date for *every* alert on the set: one watched in both conditions must not
    come straight back due through the alert that wasn't reset."""
    from .alerts import next_due_date

    await session.execute(
        update(PriceAlert).where(PriceAlert.set_num == set_num).values(next_refresh_due=next_due_date())
    )
    await session.commit()


# --------------------------------------------------------------------------------------
# Collection value history (#216)
# --------------------------------------------------------------------------------------


async def record_collection_value_snapshot(
    session: AsyncSession,
    *,
    total_value_eur: float,
    sets_count: int,
    units_count: int,
    priced_sets_count: int,
) -> None:
    """One row per calendar day, updated in place while the day is current — idempotent, because
    both callers (opening Statistiques, finishing a price batch) fire freely and neither knows
    what the other already wrote today.

    The coverage guard is load-bearing even though prices no longer expire (#244): a genuinely
    uncovered reading is still possible (nothing ever fetched, a total outage) and would be just
    as destructive written over a good one. So nothing is written at zero coverage, and today's
    row is only replaced by a reading that priced at least as many sets.
    """
    if priced_sets_count <= 0:
        return

    now = _now()
    day_key = _day_key(now)
    # Only the newest row can be today's — one indexed read instead of loading all 1460.
    latest = (
        (
            await session.execute(
                select(CollectionValueSnapshot)
                .order_by(CollectionValueSnapshot.day_key.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    if latest is not None and latest.day_key == day_key:
        if priced_sets_count < latest.priced_sets_count:
            return
        latest.captured_at = now
        latest.total_value_eur = total_value_eur
        latest.sets_count = sets_count
        latest.units_count = units_count
        latest.priced_sets_count = priced_sets_count
    else:
        session.add(
            CollectionValueSnapshot(
                day_key=day_key,
                captured_at=now,
                total_value_eur=total_value_eur,
                sets_count=sets_count,
                units_count=units_count,
                priced_sets_count=priced_sets_count,
            )
        )
        # Only after an insert: an in-place update can't grow the table.
        stale = (
            (
                await session.execute(
                    select(CollectionValueSnapshot.day_key)
                    .order_by(CollectionValueSnapshot.day_key.desc())
                    .offset(SNAPSHOT_RETENTION_DAYS)
                )
            )
            .scalars()
            .all()
        )
        if stale:
            await session.execute(
                delete(CollectionValueSnapshot).where(CollectionValueSnapshot.day_key.in_(stale))
            )
    await session.commit()


async def collection_value_snapshots(session: AsyncSession) -> list[CollectionValueSnapshot]:
    """Oldest first — the raw daily series Statistiques buckets into daily/weekly/monthly points."""
    rows = await session.execute(
        select(CollectionValueSnapshot).order_by(CollectionValueSnapshot.day_key)
    )
    return list(rows.scalars().all())


# --------------------------------------------------------------------------------------
# Cache clear
# --------------------------------------------------------------------------------------


async def clear_cache(session: AsyncSession) -> None:
    """"Vider le cache" discards what can be rebuilt, and only that.

    Kept, deliberately: `ScanEvent` (the "when did I scan this" history — though its locations go,
    since purging the history revokes the "where", #46), `SetPurchaseRecord` and `PriceAlert`
    (hand-typed, unrecoverable), `PriceHistoryEntry` and `CollectionValueSnapshot` (a past
    reading isn't merely expensive to re-fetch, it is unobtainable — no source can say today what
    the collection was worth last March). `SoldListing` *is* purged: BrickLink re-sends its whole
    6-month window on the next refresh.
    """
    await _strip_scan_locations(session, None)
    for model in (CachedSet, CachedSetList, CachedSetPrice, SoldListing, CollectionSyncState):
        await session.execute(delete(model))
    await session.commit()
