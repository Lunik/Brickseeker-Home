"""Prices: reading the cache, refreshing live, driving the batch, and the deal verdict."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import Field

from ..deps import ApiError, SessionDep, require_auth
from ..schemas import CamelModel, OkOut, PriceQuoteOut, ValuationOut
from ..services import collection_repo, prices
from ..services.interactive_prices import interactive_price_manager
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
    captcha_required_sources: list[str]


class BatchStartIn(CamelModel):
    set_nums: list[str] | None = None
    only_missing: bool = False


class DealVerdictIn(CamelModel):
    set_num: str
    price_seen: float


class CaptchaPointerIn(CamelModel):
    event_type: Literal["move", "down", "up"]
    x: float = Field(ge=0, le=4096)
    y: float = Field(ge=0, le=4096)
    button: Literal["left", "middle", "right"] = "left"


class CaptchaWheelIn(CamelModel):
    delta_x: float = Field(ge=-4000, le=4000)
    delta_y: float = Field(ge=-4000, le=4000)


class CaptchaKeyIn(CamelModel):
    key: str | None = Field(default=None, max_length=32)
    text: str | None = Field(default=None, max_length=16)


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
        captcha_required_sources=prices.captcha_required_sources(),
    )


@router.get("/batch/status")
async def batch_status() -> dict[str, object]:
    return price_updater.state


@router.post("/batch/start")
async def batch_start(payload: BatchStartIn) -> dict[str, str]:
    """Kicks off the batch and returns at once — a full collection takes many minutes by design,
    since it is sequential to stay polite to the scraped sites. The UI polls `/batch/status`."""
    if interactive_price_manager.has_active_operation:
        return {"status": "busy"}
    status = await price_updater.start(payload.set_nums, only_missing=payload.only_missing)
    return {"status": status}


@router.post("/batch/cancel", response_model=OkOut)
async def batch_cancel() -> OkOut:
    await price_updater.cancel_preserving_progress()
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


@router.post("/interactive/start/{set_num}")
async def start_interactive_refresh(
    set_num: str,
    session: SessionDep,
) -> dict[str, object]:
    if await collection_repo.cached_set(session, set_num) is None:
        raise ApiError("Ce set n'est pas encore en cache", 404)
    if price_updater.state["isRunning"] or price_updater.is_watch_running:
        raise ApiError("Une actualisation en lot est déjà en cours", 409)
    try:
        return interactive_price_manager.start(set_num)
    except RuntimeError as error:
        raise ApiError(str(error), 409) from error


@router.get("/interactive/{operation_id}")
async def interactive_refresh_status(operation_id: str) -> dict[str, object]:
    try:
        return interactive_price_manager.state(operation_id)
    except KeyError as error:
        raise ApiError("Actualisation interactive introuvable ou expirée", 404) from error


@router.post("/interactive/{operation_id}/cancel", response_model=OkOut)
async def cancel_interactive_refresh(operation_id: str) -> OkOut:
    try:
        await interactive_price_manager.cancel(operation_id)
    except KeyError as error:
        raise ApiError("Actualisation interactive introuvable ou expirée", 404) from error
    return OkOut()


@router.get("/captcha/{challenge_id}")
async def captcha_status(challenge_id: str) -> dict[str, object]:
    try:
        return await interactive_price_manager.challenge_state(challenge_id)
    except KeyError as error:
        raise ApiError("Session CAPTCHA introuvable ou expirée", 404) from error


@router.get("/captcha/{challenge_id}/frame")
async def captcha_frame(challenge_id: str) -> Response:
    try:
        frame = await interactive_price_manager.frame(challenge_id)
    except KeyError as error:
        raise ApiError("Session CAPTCHA introuvable ou expirée", 404) from error
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.post("/captcha/{challenge_id}/pointer", response_model=OkOut)
async def captcha_pointer(challenge_id: str, payload: CaptchaPointerIn) -> OkOut:
    try:
        await interactive_price_manager.pointer(
            challenge_id,
            payload.event_type,
            payload.x,
            payload.y,
            payload.button,
        )
    except KeyError as error:
        raise ApiError("Session CAPTCHA introuvable ou expirée", 404) from error
    return OkOut()


@router.post("/captcha/{challenge_id}/wheel", response_model=OkOut)
async def captcha_wheel(challenge_id: str, payload: CaptchaWheelIn) -> OkOut:
    try:
        await interactive_price_manager.wheel(
            challenge_id,
            payload.delta_x,
            payload.delta_y,
        )
    except KeyError as error:
        raise ApiError("Session CAPTCHA introuvable ou expirée", 404) from error
    return OkOut()


@router.post("/captcha/{challenge_id}/key", response_model=OkOut)
async def captcha_key(challenge_id: str, payload: CaptchaKeyIn) -> OkOut:
    try:
        await interactive_price_manager.key(challenge_id, payload.key, payload.text)
    except KeyError as error:
        raise ApiError("Session CAPTCHA introuvable ou expirée", 404) from error
    except ValueError as error:
        raise ApiError(str(error), 422) from error
    return OkOut()


@router.post("/captcha/{challenge_id}/continue", response_model=OkOut)
async def continue_captcha(challenge_id: str) -> OkOut:
    try:
        interactive_price_manager.resolve_challenge(challenge_id, "continue")
    except KeyError as error:
        raise ApiError("Session CAPTCHA introuvable ou expirée", 404) from error
    return OkOut()


@router.post("/captcha/{challenge_id}/skip", response_model=OkOut)
async def skip_captcha(challenge_id: str) -> OkOut:
    try:
        interactive_price_manager.resolve_challenge(challenge_id, "skip")
    except KeyError as error:
        raise ApiError("Session CAPTCHA introuvable ou expirée", 404) from error
    return OkOut()


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
    """lego.com alone — the slowest source, isolated so the retail price can be re-read without
    paying for every external retail source.

    No screen calls it any more: the set sheet used to carry a "lego.com" button beside the refresh
    icon, and two controls for overlapping work needed more explaining than they saved. Kept because
    it is the cheap half of a refresh and costs nothing to leave in place."""
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
