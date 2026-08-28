"""The gift list, stored on Brickset.

Rebrickable cannot host it: its `setlists` represent sets you actually own. Brickset's separate
`wanted` flag is the storage, which is why this is gated on its own account link rather than the
Rebrickable one.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from ..db import session_scope
from ..deps import ApiError, SessionDep, require_auth
from ..schemas import CamelModel, OkOut, SetRowOut
from ..services import brickset, catalog, collection_repo, rebrickable, wishlist_sync
from ..services.pricing import ListCondition, best_deal, resolve_wishlist_price_detailed

router = APIRouter(prefix="/wishlist", tags=["liste cadeaux"], dependencies=[Depends(require_auth)])

#: Wishlist-specific wording (iOS `WishlistView.priceLabel`, #157): a wishlist set isn't owned, so
#: "Neuf"/"Occasion" (what the collection chains use) would describe a condition nobody holds —
#: "meilleure offre" says what the amount actually is instead.
_WISHLIST_PRICE_LABEL = {
    ListCondition.NEW: "Meilleure offre",
    ListCondition.USED: "Meilleure offre (occasion)",
}


class WishlistOut(CamelModel):
    sets: list[SetRowOut]
    is_linked: bool
    last_synced_at: datetime | None


@router.get("", response_model=WishlistOut)
async def read_wishlist(session: SessionDep) -> WishlistOut:
    wanted = await collection_repo.wishlist_sets(session)
    quotes_by_set = await collection_repo.all_cached_prices(session)
    theme_names = await catalog.theme_names(session)
    alerted = {alert.set_num for alert in await collection_repo.price_alerts(session) if alert.is_enabled}

    rows: list[SetRowOut] = []
    for cached in wanted:
        # The wishlist chain puts the marketplaces *before* lego.com — reversed from History, on
        # purpose. Its final BrickLink-used step means a retired wishlisted set can resolve to a
        # used price, so the label has to say which condition the amount represents.
        resolved = resolve_wishlist_price_detailed(
            cached.store_price_eur, quotes_by_set.get(cached.set_num, [])
        )
        rows.append(
            SetRowOut.of(
                cached,
                theme_name=theme_names.get(cached.theme_id, f"Thème #{cached.theme_id}"),
                resolved_price=resolved[0] if resolved else None,
                price_condition=resolved[1].value if resolved else None,
                price_label=_WISHLIST_PRICE_LABEL[resolved[1]] if resolved else None,
                has_price_alert=cached.set_num in alerted,
                deal=best_deal(cached.store_price_eur, quotes_by_set.get(cached.set_num, [])),
            )
        )

    return WishlistOut(
        sets=rows,
        is_linked=await brickset.is_linked(session),
        last_synced_at=await collection_repo.last_wishlist_sync_at(session),
    )


@router.post("/sync")
async def sync_wishlist(session: SessionDep) -> dict[str, int]:
    client = await brickset.client_for(session)
    wanted = await client.fetch_wishlist_set_numbers()
    enriched = await wishlist_sync.apply(session, wanted)
    return {"count": len(wanted), "enriched": enriched}


# Above `/{set_num}` for the same reason as `/collection/bulk`: otherwise an import POST is
# dispatched to `add_to_wishlist(set_num="import")`.
@router.post("/import")
async def import_wishlist(
    background: BackgroundTasks, file: UploadFile = File(...)
) -> dict[str, object]:
    """Mass import from a Rebrickable custom-list CSV export.

    Returns immediately: each set costs a Brickset lookup plus an add, throttled to one call per
    second, so a 150-set list takes minutes. The UI polls `/wishlist/import/status`.
    """
    payload = await file.read()

    async def run() -> None:
        async with session_scope() as background_session:
            await wishlist_sync.import_csv(background_session, payload)

    background.add_task(run)
    return {"started": True, "total": len(wishlist_sync.parse_set_numbers(payload))}


@router.post("/{set_num}", response_model=OkOut)
async def add_to_wishlist(set_num: str, session: SessionDep) -> OkOut:
    client = await brickset.client_for(session)
    await client.add_to_wishlist(set_num)
    if await collection_repo.cached_set(session, set_num) is None:
        # No cache row yet — a catalogue set added straight to the wishlist, never scanned or
        # owned. `set_wishlist_status` no-ops without a row, so the add would succeed on Brickset
        # and never appear in Liste cadeaux until a full sync — the same case
        # `wishlist_sync.apply`'s enrichment pass exists to cover for the bulk sync path.
        rebrickable_client = await rebrickable.client_for(session)
        try:
            lego_set = await rebrickable_client.fetch_set(set_num)
        except ApiError:
            lego_set = None
        if lego_set is not None:
            await collection_repo.cache_wishlist_set(session, lego_set)
    await collection_repo.set_wishlist_status(session, set_num, True)
    return OkOut()


@router.delete("/{set_num}", response_model=OkOut)
async def remove_from_wishlist(set_num: str, session: SessionDep) -> OkOut:
    client = await brickset.client_for(session)
    await client.remove_from_wishlist(set_num)
    await collection_repo.set_wishlist_status(session, set_num, False)
    return OkOut()


@router.get("/import/status")
async def import_status() -> dict[str, object]:
    return wishlist_sync.progress.as_dict()
