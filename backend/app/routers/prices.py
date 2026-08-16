"""Prices: reading the cache, refreshing live, driving the batch, and the deal verdict."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends

from ..deps import ApiError, SessionDep, require_auth
from ..schemas import CamelModel, OkOut, PriceQuoteOut, ValuationOut
from ..services import collection_repo, prices
from ..services.price_updater import price_updater
from ..services.pricing import (
    StoreAvailability,
    evaluate_deal,
    make_valuation,
    percent_vs_store,
    source_display_name,
)

router = APIRouter(prefix="/prices", tags=["prix"], dependencies=[Depends(require_auth)])


class PricesOut(CamelModel):
    set_num: str
    quotes: list[PriceQuoteOut]
    store_price_eur: float | None
    store_currency: str | None
    availability: str
    store_price_fetched_at: datetime | None
    valuation: ValuationOut
    #: ±% versus the lego.com price, per source — computed here so every consumer shows the same
    #: number rather than each re-deriving it.
    percent_vs_store: dict[str, int]


class BatchStartIn(CamelModel):
    set_nums: list[str] | None = None
    only_missing: bool = False


class DealVerdictIn(CamelModel):
    set_num: str
    price_seen: float


async def _payload(session, set_num: str) -> PricesOut:
    cached = await collection_repo.cached_set(session, set_num)
    quotes = await collection_repo.cached_prices(session, set_num)
    conditions = await collection_repo.condition_by_list_id(session)
    condition = (
        conditions.get(cached.current_list_id) if cached and cached.current_list_id else None
    )
    store_price = cached.store_price_eur if cached else None
    availability = (
        StoreAvailability.from_raw(cached.store_availability) if cached else StoreAvailability.UNKNOWN
    )

    valuation = make_valuation(
        set_num,
        store_price,
        await collection_repo.paid_price(session, set_num),
        condition,
        quotes,
        store_price_fetched_at=cached.store_price_fetched_at if cached else None,
        availability=availability,
    )

    deltas: dict[str, int] = {}
    for quote in quotes:
        delta = percent_vs_store(quote.amount, quote.currency, store_price, "EUR")
        if delta is not None:
            deltas[quote.source.value] = delta

    return PricesOut(
        set_num=set_num,
        quotes=[PriceQuoteOut.of(quote) for quote in quotes],
        store_price_eur=store_price,
        store_currency="EUR",
        availability=availability.value,
        store_price_fetched_at=cached.store_price_fetched_at if cached else None,
        valuation=ValuationOut.of(valuation),
        percent_vs_store=deltas,
    )


@router.get("/batch/status")
async def batch_status() -> dict[str, object]:
    return price_updater.state


@router.post("/batch/start")
async def batch_start(payload: BatchStartIn, background: BackgroundTasks) -> dict[str, str]:
    """Kicks off the batch and returns at once — a full collection takes many minutes by design,
    since it is sequential to stay polite to the scraped sites. The UI polls `/batch/status`."""
    status = await price_updater.start(payload.set_nums, only_missing=payload.only_missing)
    return {"status": status}


@router.post("/batch/cancel", response_model=OkOut)
async def batch_cancel() -> OkOut:
    price_updater.cancel_preserving_progress()
    return OkOut()


@router.post("/deal-verdict")
async def deal_verdict(payload: DealVerdictIn, session: SessionDep) -> dict[str, object]:
    """Weighs a price seen in a shop against every reference already loaded for this set."""
    cached = await collection_repo.cached_set(session, payload.set_num)
    quotes = await collection_repo.cached_prices(session, payload.set_num)
    result = evaluate_deal(
        payload.price_seen,
        cached.store_price_eur if cached else None,
        "EUR",
        quotes,
        store_fetched_at=cached.store_price_fetched_at if cached else None,
    )
    if result is None:
        return {"verdict": None, "comparisons": []}

    return {
        "verdict": result.verdict.value,
        "emoji": result.verdict.emoji,
        "label": result.verdict.label,
        "comparisons": [
            {
                "label": comparison.label,
                "referenceAmount": comparison.reference_amount,
                "differenceAmount": comparison.difference_amount,
                "percent": comparison.percent,
                "fetchedAt": comparison.fetched_at,
            }
            for comparison in result.comparisons
        ],
    }


@router.get("/{set_num}", response_model=PricesOut)
async def read_prices(set_num: str, session: SessionDep) -> PricesOut:
    return await _payload(session, set_num)


@router.post("/{set_num}/refresh", response_model=PricesOut)
async def refresh_prices(set_num: str, session: SessionDep) -> PricesOut:
    cached = await collection_repo.cached_set(session, set_num)
    if cached is None:
        raise ApiError("Ce set n'est pas encore en cache", 404)
    await prices.refresh_set_prices(session, collection_repo.to_lego_set(cached), reconcile=True)
    return await _payload(session, set_num)


@router.post("/{set_num}/store-refresh", response_model=PricesOut)
async def refresh_store_price(set_num: str, session: SessionDep) -> PricesOut:
    """lego.com alone — the slowest source, so it gets its own button rather than forcing a full
    refresh when only the retail price is wanted."""
    await prices.fetch_store_price(session, set_num)
    return await _payload(session, set_num)


@router.get("/{set_num}/history")
async def read_history(set_num: str, session: SessionDep) -> dict[str, object]:
    history = await collection_repo.price_history(session, set_num)
    sold = await collection_repo.sold_listings(session, set_num)
    return {
        "history": [
            {
                "source": entry.source,
                "sourceName": source_display_name(entry.source),
                "amount": entry.amount,
                "fetchedAt": entry.fetched_at,
            }
            for entry in history
        ],
        "soldListings": [
            {
                "source": entry.source,
                "unitAmount": entry.unit_amount,
                "quantity": entry.quantity,
                "orderedAt": entry.ordered_at,
            }
            for entry in sold
        ],
    }
