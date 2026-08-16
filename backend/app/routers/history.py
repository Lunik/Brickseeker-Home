"""Scan history and the scan map.

A `ScanEvent` records that the user physically stood in front of a set. Its location exists to
answer "in which shop did I see this deal", which is why it is erased the moment the set joins the
collection — the question is then moot.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import ApiError, SessionDep, require_auth
from ..schemas import CamelModel, OkOut, ScanEventOut, SetRowOut
from ..services import catalog, collection_repo
from ..services.pricing import StoreAvailability, resolve_new_price

router = APIRouter(prefix="/history", tags=["historique"], dependencies=[Depends(require_auth)])


class ScanEventIn(CamelModel):
    set_num: str
    price_seen_eur: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    place_name: str | None = None


class ScanEventPatch(CamelModel):
    price_seen_eur: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    place_name: str | None = None


class MapPointOut(CamelModel):
    id: int
    set_num: str
    set_name: str
    set_img_url: str | None
    scanned_at: str
    latitude: float
    longitude: float
    place_name: str | None
    price_seen_eur: float | None


@router.get("")
async def read_history(session: SessionDep) -> dict[str, list[SetRowOut]]:
    scanned = await collection_repo.scanned_sets(session)
    quotes_by_set = await collection_repo.all_cached_prices(session)
    theme_names = await catalog.theme_names(session)
    alerted = {alert.set_num for alert in await collection_repo.price_alerts(session) if alert.is_enabled}

    rows = [
        SetRowOut.of(
            cached,
            theme_name=theme_names.get(cached.theme_id, f"Thème #{cached.theme_id}"),
            # History always values a set as new — it is about what you'd pay for it today.
            resolved_price=resolve_new_price(
                cached.store_price_eur,
                StoreAvailability.from_raw(cached.store_availability),
                quotes_by_set.get(cached.set_num, []),
            ),
            price_condition="newSet",
            price_label="Neuf",
            has_price_alert=cached.set_num in alerted,
        )
        for cached in scanned
    ]
    return {"sets": rows}


@router.get("/events")
async def read_events(session: SessionDep, set_num: str | None = None) -> dict[str, list[ScanEventOut]]:
    events = await collection_repo.scan_events(session, set_num)
    return {"events": [ScanEventOut.of(event) for event in events]}


@router.post("/events", response_model=ScanEventOut)
async def create_event(payload: ScanEventIn, session: SessionDep) -> ScanEventOut:
    event = await collection_repo.record_scan_event(
        session, payload.set_num, price_seen_eur=payload.price_seen_eur
    )
    if payload.latitude is not None and payload.longitude is not None:
        await collection_repo.attach_location(
            session, event.id, payload.latitude, payload.longitude, payload.place_name
        )
        await session.refresh(event)
    return ScanEventOut.of(event)


@router.patch("/events/{event_id}", response_model=ScanEventOut)
async def update_event(event_id: int, payload: ScanEventPatch, session: SessionDep) -> ScanEventOut:
    if payload.price_seen_eur is not None:
        await collection_repo.update_scan_event_price(session, event_id, payload.price_seen_eur)
    if payload.latitude is not None and payload.longitude is not None:
        await collection_repo.attach_location(
            session, event_id, payload.latitude, payload.longitude, payload.place_name
        )

    events = await collection_repo.scan_events(session)
    for event in events:
        if event.id == event_id:
            return ScanEventOut.of(event)
    raise ApiError("Scan introuvable", 404)


@router.delete("/events/{event_id}", response_model=OkOut)
async def delete_event(event_id: int, session: SessionDep) -> OkOut:
    await collection_repo.delete_scan_event(session, event_id)
    return OkOut()


@router.delete("/{set_num}", response_model=OkOut)
async def delete_from_history(set_num: str, session: SessionDep) -> OkOut:
    """Removes a set from History. A set still owned only loses `was_scanned` — it stays in the
    Collection, exactly as if it had never been scanned."""
    await collection_repo.delete_from_history(session, set_num)
    return OkOut()


@router.get("/map")
async def scan_map(session: SessionDep) -> dict[str, list[MapPointOut]]:
    events = await collection_repo.scan_events(session)
    located = [event for event in events if event.latitude is not None and event.longitude is not None]
    if not located:
        return {"points": []}

    names: dict[str, tuple[str, str | None]] = {}
    for event in located:
        if event.set_num not in names:
            cached = await collection_repo.cached_set(session, event.set_num)
            names[event.set_num] = (
                (cached.name, cached.set_img_url) if cached else (event.set_num, None)
            )

    return {
        "points": [
            MapPointOut(
                id=event.id,
                set_num=event.set_num,
                set_name=names[event.set_num][0],
                set_img_url=names[event.set_num][1],
                scanned_at=event.scanned_at.isoformat(),
                latitude=event.latitude,
                longitude=event.longitude,
                place_name=event.place_name,
                price_seen_eur=event.price_seen_eur,
            )
            for event in located
        ]
    }
