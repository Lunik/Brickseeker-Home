"""Set resolution and the detail payload.

`/sets/{setNum}` answers from the cache alone, never blocking on a live scrape — a detail screen
that spun up a browser on every open would be unusable. It does still *schedule* one in the
background when `prices_fetched_at` is more than `prices.STALE_PRICE_THRESHOLD` old, so a set
nobody has looked at in a week gets a live price without the user having to remember to ask for
one via the explicit `/prices/{setNum}/refresh`. The response says so (`pricesRefreshing`) so the
frontend can pick up the fresh numbers once the background task finishes, rather than requiring a
manual reload to notice.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from ..db import session_scope
from ..deps import ApiError, SessionDep, not_found, require_auth
from ..schemas import (
    CamelModel,
    LegoSetOut,
    PriceAlertOut,
    PriceQuoteOut,
    ScanEventOut,
    ValuationOut,
)
from ..services import catalog, collection_repo, prices, rebrickable
from ..services.alerts import effective_threshold
from ..services.pricing import (
    StoreAvailability,
    is_minifig,
    make_valuation,
    source_display_name,
)
from ..services.rebrickable import Ambiguous, Found, NotFound
from ..services.scraping.lego_store import instructions_url, store_url

router = APIRouter(tags=["sets"], dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)


class ResolveOut(CamelModel):
    status: str  # found | ambiguous | notFound | offline
    set: LegoSetOut | None = None
    candidates: list[LegoSetOut] = []
    is_from_cache: bool = False


class PriceHistoryPointOut(CamelModel):
    source: str
    source_name: str
    amount: float
    fetched_at: datetime


class SoldSaleOut(CamelModel):
    source: str
    unit_amount: float
    quantity: int
    ordered_at: datetime


class SetDetailOut(CamelModel):
    set: LegoSetOut
    theme_name: str
    is_in_collection: bool
    current_list_id: int | None
    current_list_name: str | None
    list_condition: str | None
    quantity: int
    is_in_wishlist: bool
    store_price_eur: float | None
    store_currency: str | None
    availability: str
    store_price_fetched_at: datetime | None
    quotes: list[PriceQuoteOut]
    valuation: ValuationOut
    paid_price_eur: float | None
    price_history: list[PriceHistoryPointOut]
    sold_listings: list[SoldSaleOut]
    scan_events: list[ScanEventOut]
    best_price_scan_id: int | None
    alerts: list[PriceAlertOut]
    non_set_kind: str | None
    store_url: str | None
    instructions_url: str | None
    is_minifig: bool
    is_offline_result: bool = False
    prices_refreshing: bool = False
    captcha_required_sources: list[str]


async def _resolve(session, query: str) -> ResolveOut:
    """Cache-first, exactly like the iOS scanner: a cached row answers instantly.

    The offline-catalogue fallback fires on a connectivity failure (503/504) *and* on a missing
    Rebrickable API key (412, `missing_credentials`) — a downloaded catalogue is meant to answer
    "what set is this" without ever needing that key, not just when the network happens to be
    down. Any other error (bad key, server bug) is a real problem and must not be silently masked
    by a stale catalogue hit.
    """
    cached = await collection_repo.cached_set(session, query)
    if cached is None and "-" not in query:
        cached = await collection_repo.cached_set(session, f"{query}-1")
    if cached is not None:
        return ResolveOut(
            status="found",
            set=LegoSetOut.model_validate(collection_repo.to_lego_set(cached), from_attributes=True),
            is_from_cache=True,
        )

    try:
        client = await rebrickable.client_for(session)
        resolution = await client.resolve_set(query)
    except ApiError as error:
        if error.status_code in (503, 504, 412):
            offline = await catalog.lookup_catalog_set(session, query) or await catalog.lookup_catalog_set(
                session, f"{query}-1"
            )
            if offline is not None:
                return ResolveOut(
                    status="offline",
                    set=LegoSetOut.model_validate(offline, from_attributes=True),
                )
        raise

    match resolution:
        case Found(lego_set):
            return ResolveOut(
                status="found", set=LegoSetOut.model_validate(lego_set, from_attributes=True)
            )
        case Ambiguous(candidates):
            hidden = await _hide_non_sets(session, candidates)
            return ResolveOut(
                status="ambiguous",
                candidates=[LegoSetOut.model_validate(item, from_attributes=True) for item in hidden],
            )
        case NotFound():
            offline = await catalog.lookup_catalog_set(session, query)
            if offline is not None:
                return ResolveOut(
                    status="offline",
                    set=LegoSetOut.model_validate(offline, from_attributes=True),
                )
            return ResolveOut(status="notFound")
    return ResolveOut(status="notFound")


async def _hide_non_sets(session, candidates: list) -> list:
    """The disambiguator is a *discovery* surface, so the non-set filter applies here — unlike
    Collection/Historique, where a LEGO cap you own stays visible whatever the toggle says."""
    from ..services import app_settings

    hide_enabled = bool(await app_settings.get_setting(session, "hide_wearables_enabled"))
    kept = []
    for candidate in candidates:
        if not await catalog.should_hide(session, candidate.theme_id, hide_enabled):
            kept.append(candidate)
    # Never return an empty list: hiding every candidate would leave the user with nothing to pick
    # after they deliberately pointed the camera at something.
    return kept or candidates


@router.get("/sets/resolve", response_model=ResolveOut)
async def resolve_set(session: SessionDep, q: str = Query(min_length=1)) -> ResolveOut:
    return await _resolve(session, q.strip())


@router.get("/sets/search")
async def search_sets(
    session: SessionDep, q: str = Query(min_length=1), page_size: int = 20
) -> dict[str, object]:
    client = await rebrickable.client_for(session)
    results = await client.search_sets(q.strip(), page_size=page_size)
    return {"results": [LegoSetOut.model_validate(item, from_attributes=True) for item in results]}


@router.get("/sets/{set_num}", response_model=SetDetailOut)
async def set_detail(set_num: str, session: SessionDep, background: BackgroundTasks) -> SetDetailOut:
    cached = await collection_repo.cached_set(session, set_num)
    lego_set = None
    is_offline = False

    if cached is not None:
        lego_set = collection_repo.to_lego_set(cached)
    else:
        if is_minifig(set_num):
            # Rebrickable has no `/lego/sets/fig-…/`, so a minifig only ever resolves locally.
            lego_set = await catalog.lookup_catalog_minifig(session, set_num)
            if lego_set is None:
                raise not_found("Minifig introuvable — téléchargez le catalogue des minifigs.")
        else:
            try:
                client = await rebrickable.client_for(session)
                lego_set = await client.fetch_set(set_num)
            except ApiError:
                lego_set = await catalog.lookup_catalog_set(session, set_num)
                is_offline = lego_set is not None
                if lego_set is None:
                    raise
        # Cache the row so prices, alerts and scans have something to attach to. Not marked as
        # scanned: opening a set is not scanning it.
        cached = await collection_repo.cache_set(
            session,
            lego_set,
            is_in_collection=False,
            list_id=None,
            list_name=None,
            mark_as_scanned=False,
        )

    # Scheduled, not awaited: the response below answers from the cache regardless, so a stale set
    # is never the reason this request is slow. `refresh_set_prices` already resolves per-item
    # (minifig -> BrickLink only, a set -> every source) — nothing to branch on here.
    stale_prices = prices.is_price_stale(cached.prices_fetched_at)
    refreshing = stale_prices or prices.is_background_refreshing(set_num)
    if stale_prices and prices.claim_background_refresh(set_num):
        target = lego_set

        async def run() -> None:
            try:
                async with session_scope() as bg_session:
                    await prices.refresh_set_prices(bg_session, target)
            except Exception:  # noqa: BLE001 - see below
                # Individual source failures are already swallowed inside `refresh_set_prices`; only
                # a genuinely unexpected error (a DB hiccup, say) reaches here. The claim below still
                # gets released, so a later visit may retry without the current polling loop stacking
                # another ten browser pages on top of a refresh already in flight.
                logger.warning("Actualisation en tâche de fond échouée pour %s", set_num, exc_info=True)
            finally:
                prices.release_background_refresh(set_num)

        background.add_task(run)

    quotes = await collection_repo.cached_prices(session, set_num)
    conditions = await collection_repo.condition_by_list_id(session)
    condition = conditions.get(cached.current_list_id) if cached.current_list_id else None
    paid_price = await collection_repo.paid_price(session, set_num)

    valuation = make_valuation(
        set_num,
        cached.store_price_eur,
        paid_price,
        condition,
        quotes,
        store_price_fetched_at=cached.store_price_fetched_at,
        availability=StoreAvailability.from_raw(cached.store_availability),
    )

    events = await collection_repo.scan_events(session, set_num)
    priced = [event for event in events if event.price_seen_eur]
    best_scan = min(priced, key=lambda event: event.price_seen_eur or 0) if priced else None

    alerts = await collection_repo.price_alerts(session, set_num)
    history = await collection_repo.price_history(session, set_num)
    sold = await collection_repo.sold_listings(session, set_num)
    minifig = is_minifig(set_num)

    return SetDetailOut(
        set=LegoSetOut.model_validate(lego_set, from_attributes=True),
        theme_name=await catalog.theme_name(session, cached.theme_id),
        is_in_collection=cached.is_in_collection,
        current_list_id=cached.current_list_id,
        current_list_name=cached.current_list_name,
        list_condition=condition.value if condition else None,
        quantity=cached.quantity,
        is_in_wishlist=cached.is_in_wishlist,
        store_price_eur=cached.store_price_eur,
        store_currency="EUR",
        availability=StoreAvailability.from_raw(cached.store_availability).value,
        store_price_fetched_at=cached.store_price_fetched_at,
        quotes=[PriceQuoteOut.of(quote) for quote in quotes],
        valuation=ValuationOut.of(valuation),
        paid_price_eur=paid_price,
        price_history=[
            PriceHistoryPointOut(
                source=entry.source,
                source_name=source_display_name(entry.source),
                amount=entry.amount,
                fetched_at=entry.fetched_at,
            )
            for entry in history
        ],
        sold_listings=[
            SoldSaleOut(
                source=entry.source,
                unit_amount=entry.unit_amount,
                quantity=entry.quantity,
                ordered_at=entry.ordered_at,
            )
            for entry in sold
        ],
        scan_events=[ScanEventOut.of(event) for event in events],
        best_price_scan_id=best_scan.id if best_scan else None,
        alerts=[_alert_out(alert) for alert in alerts],
        non_set_kind=await catalog.non_set_kind(session, cached.theme_id),
        store_url=None if minifig else store_url(set_num),
        instructions_url=None if minifig else instructions_url(set_num),
        is_minifig=minifig,
        is_offline_result=is_offline,
        prices_refreshing=refreshing,
        captcha_required_sources=prices.captcha_required_sources(),
    )


def _alert_out(alert) -> PriceAlertOut:  # noqa: ANN001 - ORM row
    return PriceAlertOut(
        id=alert.id,
        set_num=alert.set_num,
        condition=alert.condition,
        set_name=alert.set_name,
        set_img_url=alert.set_img_url,
        threshold_eur=alert.threshold_eur,
        discount_percent=alert.discount_percent,
        reference_price_eur=alert.reference_price_eur,
        reference_source_name=alert.reference_source_name,
        effective_threshold_eur=effective_threshold(alert),
        is_enabled=alert.is_enabled,
        last_observed_price_eur=alert.last_observed_price_eur,
        last_notified_at=alert.last_notified_at,
        created_at=alert.created_at,
    )


class PaidPriceIn(CamelModel):
    paid_price_eur: float | None = None


@router.put("/sets/{set_num}/paid-price")
async def set_paid_price(set_num: str, payload: PaidPriceIn, session: SessionDep) -> dict[str, object]:
    """What the user actually paid — the preferred reference for the growth figure.

    Its own table rather than a `CachedSet` column, because a cache clear or a set leaving the
    collection must not destroy a hand-typed number. Passing null clears it, so the reference falls
    back to the retail price rather than keeping a stale one.
    """
    await collection_repo.set_paid_price(session, set_num, payload.paid_price_eur)
    return {"setNum": set_num, "paidPriceEur": await collection_repo.paid_price(session, set_num)}


@router.get("/sets/{set_num}/minifigs")
async def minifigs_in_set(set_num: str, session: SessionDep, page_size: int = 30) -> dict[str, object]:
    client = await rebrickable.client_for(session)
    page = await client.fetch_minifigs_in_set(set_num, page_size=page_size)
    return {
        "count": page.count,
        "results": [
            {
                "setNum": entry.set_num,
                "name": entry.name,
                "quantity": entry.quantity,
                "setImgUrl": entry.set_img_url,
            }
            for entry in page.results
        ],
    }


@router.get("/sets/{set_num}/similar")
async def similar_sets(set_num: str, session: SessionDep, page_size: int = 20) -> dict[str, object]:
    cached = await collection_repo.cached_set(session, set_num)
    client = await rebrickable.client_for(session)
    lego_set = collection_repo.to_lego_set(cached) if cached else await client.fetch_set(set_num)

    page = await client.fetch_similar_sets(lego_set, page_size=page_size)
    # The reference set always matches its own filter (same theme, and its own part count sits
    # inside a window derived from itself), so it is excluded here rather than in the client.
    candidates = [item for item in page.results if item.set_num != lego_set.set_num]
    # Rebrickable has no "closest to N parts" ordering, so the proximity sort happens here.
    candidates.sort(key=lambda item: abs(item.num_parts - lego_set.num_parts))
    return {
        "results": [LegoSetOut.model_validate(item, from_attributes=True) for item in candidates]
    }


@router.get("/minifigs/{fig_num}/sets")
async def sets_containing_minifig(
    fig_num: str, session: SessionDep, page_size: int = 30
) -> dict[str, object]:
    client = await rebrickable.client_for(session)
    page = await client.fetch_sets_containing_minifig(fig_num, page_size=page_size)
    return {
        "count": page.count,
        "results": [
            {
                "setNum": entry.set_num,
                "name": entry.name,
                "numParts": entry.num_parts,
                "setImgUrl": entry.set_img_url,
                "setUrl": entry.set_url,
                "quantity": entry.quantity,
            }
            for entry in page.results
        ],
    }
