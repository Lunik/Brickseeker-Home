"""Camera/photo scanning: OCR, then resolution through the one shared lookup path."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from ..deps import SessionDep, require_auth
from ..schemas import CamelModel
from ..services import collection_repo, geocoding, ocr
from .sets import ResolveOut, _resolve

router = APIRouter(prefix="/scan", tags=["scan"], dependencies=[Depends(require_auth)])


class OcrOut(CamelModel):
    candidates: list[str]
    set_nums: list[str]


#: Sources that count as a scan. `listReopen` is deliberately absent — reopening a row from a
#: list is browsing, and it must not bump the set to the top of Historique.
RECORDED_SOURCES = {"camera", "manualEntry", "photoImport"}


class LookupIn(CamelModel):
    set_num: str
    #: camera | manualEntry | photoImport | listReopen — only "camera" records a ScanEvent.
    source: str = "manualEntry"
    price_seen_eur: float | None = None
    latitude: float | None = None
    longitude: float | None = None


class LookupOut(ResolveOut):
    scan_event_id: int | None = None


@router.post("/ocr", response_model=OcrOut)
async def run_ocr(file: UploadFile = File(...)) -> OcrOut:
    payload = await file.read()
    candidates = await ocr.recognize_text(payload)
    return OcrOut(candidates=candidates, set_nums=ocr.extract_set_numbers(candidates))


@router.post("/lookup", response_model=LookupOut)
async def lookup(payload: LookupIn, session: SessionDep) -> LookupOut:
    """Resolves a set number and records the visit for every deliberate lookup.

    A camera scan, a typed number and an imported photo all count as "I looked this set up" and all
    land in Historique (iOS #133). Only re-opening a row from a list is exempt — that is browsing,
    not scanning. The *location* is narrower still: only a camera scan carries the "I was standing
    in a shop" meaning, so only it stores coordinates.
    """
    resolved = await _resolve(session, payload.set_num.strip())

    event_id: int | None = None
    if payload.source in RECORDED_SOURCES and resolved.set is not None:
        set_num = resolved.set.set_num
        # Cache first: a scan event with no cached row would leave History showing a bare number.
        cached = await collection_repo.cached_set(session, set_num)
        if cached is None:
            from ..services.rebrickable import LegoSet

            await collection_repo.cache_set(
                session,
                LegoSet(
                    set_num=set_num,
                    name=resolved.set.name,
                    year=resolved.set.year,
                    theme_id=resolved.set.theme_id,
                    num_parts=resolved.set.num_parts,
                    set_img_url=resolved.set.set_img_url,
                    set_url=resolved.set.set_url,
                ),
                is_in_collection=False,
                list_id=None,
                list_name=None,
                mark_as_scanned=True,
            )
        else:
            await collection_repo.cache_set(
                session,
                collection_repo.to_lego_set(cached),
                is_in_collection=cached.is_in_collection,
                list_id=cached.current_list_id,
                list_name=cached.current_list_name,
                mark_as_scanned=True,
            )

        event = await collection_repo.record_scan_event(
            session, set_num, price_seen_eur=payload.price_seen_eur
        )
        event_id = event.id
        # Location only for a real camera scan: a typed number says nothing about where you were.
        if payload.source == "camera" and payload.latitude is not None and payload.longitude is not None:
            place = await geocoding.reverse_geocode(payload.latitude, payload.longitude)
            await collection_repo.attach_location(
                session, event.id, payload.latitude, payload.longitude, place
            )

    return LookupOut(
        status=resolved.status,
        set=resolved.set,
        candidates=resolved.candidates,
        is_from_cache=resolved.is_from_cache,
        scan_event_id=event_id,
    )
