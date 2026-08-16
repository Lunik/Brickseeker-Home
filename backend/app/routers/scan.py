"""Camera/photo scanning: OCR, then resolution through the one shared lookup path."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from ..deps import SessionDep, require_auth
from ..schemas import CamelModel
from ..services import collection_repo, ocr
from .sets import ResolveOut, _resolve

router = APIRouter(prefix="/scan", tags=["scan"], dependencies=[Depends(require_auth)])


class OcrOut(CamelModel):
    candidates: list[str]
    set_nums: list[str]


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
    """Resolves a set number and, for a camera scan only, records the visit.

    Manual entry, photo import and re-opening a row from Historique carry no "I was standing in a
    shop" meaning, so they deliberately record nothing.
    """
    resolved = await _resolve(session, payload.set_num.strip())

    event_id: int | None = None
    if payload.source == "camera" and resolved.set is not None:
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
        if payload.latitude is not None and payload.longitude is not None:
            await collection_repo.attach_location(
                session, event.id, payload.latitude, payload.longitude, None
            )

    return LookupOut(
        status=resolved.status,
        set=resolved.set,
        candidates=resolved.candidates,
        is_from_cache=resolved.is_from_cache,
        scan_event_id=event_id,
    )
