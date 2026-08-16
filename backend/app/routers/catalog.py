"""The offline catalogues: download, purge, and the two discovery screens they feed.

Both discovery screens (Nouveaux sets, galerie de minifigs) apply the non-set filter — they
*suggest* items. Collection, Historique and Liste cadeaux never do: a LEGO cap you own is still
yours, and a set count that silently drops because of a Réglages toggle reads as a bug.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select

from ..db import session_scope
from ..deps import SessionDep, require_auth
from ..models import CatalogMinifig, CatalogMinifigSet, CatalogSet
from ..schemas import CamelModel, OkOut
from ..services import app_settings, catalog, collection_repo
from ..services.pricing import ListCondition, StoreAvailability, resolve_minifig_price

router = APIRouter(prefix="/catalog", tags=["catalogue"], dependencies=[Depends(require_auth)])


class CatalogSetOut(CamelModel):
    set_num: str
    name: str
    year: int
    theme_id: int
    theme_name: str
    num_parts: int
    set_img_url: str | None
    first_seen_at: datetime | None
    is_owned: bool
    availability: str
    resolved_price: float | None


class MinifigOut(CamelModel):
    fig_num: str
    name: str
    num_parts: int
    img_url: str | None
    theme_id: int | None
    theme_name: str | None
    year: int | None
    owned_quantity: int
    resolved_price: float | None
    containing_set_nums: list[str]


@router.get("/status")
async def status(session: SessionDep) -> dict[str, object]:
    return await catalog.catalog_status(session)


@router.post("/sets/download", response_model=OkOut)
async def download_sets(background: BackgroundTasks) -> OkOut:
    """Returns at once — the dump is ~28 000 rows and the UI polls `/catalog/status` for progress."""

    async def run() -> None:
        async with session_scope() as session:
            await catalog.download_sets_catalog(session)

    background.add_task(run)
    return OkOut()


@router.post("/minifigs/download", response_model=OkOut)
async def download_minifigs(background: BackgroundTasks) -> OkOut:
    async def run() -> None:
        async with session_scope() as session:
            await catalog.download_minifigs_catalog(session)

    background.add_task(run)
    return OkOut()


@router.delete("/{name}", response_model=OkOut)
async def purge(name: str, session: SessionDep) -> OkOut:
    await catalog.purge_catalog(session, name)
    return OkOut()


@router.get("/themes")
async def themes(session: SessionDep) -> dict[str, object]:
    names = await catalog.theme_names(session)
    return {"themes": [{"themeId": theme_id, "name": name} for theme_id, name in sorted(names.items())]}


@router.get("/new-sets")
async def new_sets(
    session: SessionDep,
    search: str | None = None,
    theme_name: str | None = None,
    year: int | None = None,
    owned_only: bool | None = None,
    availability: str | None = None,
    sort: str = "dateAdded",
    ascending: bool = False,
    offset: int = 0,
    limit: int = Query(default=60, le=200),
) -> dict[str, object]:
    """Browse the downloaded catalogue.

    Default sort is `dateAdded` — when *this* install first saw the set in a snapshot, which is a
    truer "new" signal than the release year. `dateScanned` is meaningless here: a catalogue entry
    was never scanned.
    """
    hide_enabled = bool(await app_settings.get_setting(session, "hide_wearables_enabled"))
    theme_names = await catalog.theme_names(session)

    rows = (await session.execute(select(CatalogSet))).scalars().all()
    owned = {cached.set_num: cached for cached in await collection_repo.owned_sets(session)}
    cached_by_num = {row.set_num: row for row in await collection_repo.scanned_sets(session)}
    cached_by_num.update(owned)

    needle = (search or "").strip().lower()
    results: list[CatalogSetOut] = []
    for row in rows:
        if await catalog.should_hide(session, row.theme_id, hide_enabled):
            continue
        name = theme_names.get(row.theme_id, f"Thème #{row.theme_id}")
        if needle and needle not in row.name.lower() and needle not in row.set_num.lower():
            continue
        if theme_name and name != theme_name:
            continue
        if year is not None and row.year != year:
            continue
        is_owned = row.set_num in owned
        if owned_only is not None and is_owned != owned_only:
            continue

        cached = cached_by_num.get(row.set_num)
        status_value = (
            StoreAvailability.from_raw(cached.store_availability) if cached else StoreAvailability.UNKNOWN
        )
        # A never-checked set has no availability string at all, so it matches only the explicit
        # "Inconnue" choice and never leaks into one of the three real lego.com states.
        if availability is not None and status_value.value != availability:
            continue

        results.append(
            CatalogSetOut(
                set_num=row.set_num,
                name=row.name,
                year=row.year,
                theme_id=row.theme_id,
                theme_name=name,
                num_parts=row.num_parts,
                set_img_url=row.set_img_url,
                first_seen_at=row.first_seen_at,
                is_owned=is_owned,
                availability=status_value.value,
                resolved_price=cached.store_price_eur if cached else None,
            )
        )

    results.sort(key=_sort_key(sort), reverse=not ascending)
    return {"count": len(results), "results": results[offset : offset + limit]}


def _sort_key(sort: str):  # noqa: ANN202 - a key function per sort option
    match sort:
        case "year":
            # `year` ties constantly — it is the finest date Rebrickable exposes, so hundreds of
            # sets share one value. `set_num` is not a chronological claim, only a stable one, so
            # the list stops reshuffling ties between reloads.
            return lambda row: (row.year, row.set_num)
        case "name":
            return lambda row: row.name.lower()
        case "partCount":
            return lambda row: row.num_parts
        case "price":
            # Unpriced entries sort last in both directions.
            return lambda row: (row.resolved_price is not None, row.resolved_price or 0.0)
        case _:
            return lambda row: (row.first_seen_at is not None, row.first_seen_at or datetime.min)


@router.get("/minifigs")
async def minifigs(
    session: SessionDep,
    search: str | None = None,
    theme_name: str | None = None,
    year: int | None = None,
    owned_only: bool = True,
    sort: str = "name",
    ascending: bool = True,
    offset: int = 0,
    limit: int = Query(default=60, le=200),
) -> dict[str, object]:
    """The owned-minifig gallery.

    A minifig is owned when any set containing it is owned, and the quantity multiplies through:
    two copies of a set with two of the same minifig is four.
    """
    owned_sets = {cached.set_num: cached for cached in await collection_repo.owned_sets(session)}
    conditions = await collection_repo.condition_by_list_id(session)
    theme_names = await catalog.theme_names(session)
    quotes_by_set = await collection_repo.all_cached_prices(session)

    pivots = (await session.execute(select(CatalogMinifigSet))).scalars().all()
    quantity_by_fig: dict[str, int] = {}
    sets_by_fig: dict[str, list[str]] = {}
    condition_by_fig: dict[str, ListCondition] = {}
    for pivot in pivots:
        sets_by_fig.setdefault(pivot.fig_num, []).append(pivot.set_num)
        owner = owned_sets.get(pivot.set_num)
        if owner is None:
            continue
        quantity_by_fig[pivot.fig_num] = (
            quantity_by_fig.get(pivot.fig_num, 0) + pivot.quantity_per_set * owner.quantity
        )
        if pivot.fig_num not in condition_by_fig and owner.current_list_id:
            resolved = conditions.get(owner.current_list_id)
            if resolved:
                condition_by_fig[pivot.fig_num] = resolved

    rows = (await session.execute(select(CatalogMinifig))).scalars().all()
    needle = (search or "").strip().lower()
    results: list[MinifigOut] = []
    for row in rows:
        quantity = quantity_by_fig.get(row.fig_num, 0)
        if owned_only and quantity == 0:
            continue
        if needle and needle not in row.name.lower() and needle not in row.fig_num.lower():
            continue
        name = theme_names.get(row.theme_id) if row.theme_id is not None else None
        if theme_name and name != theme_name:
            continue
        if year is not None and row.year != year:
            continue

        results.append(
            MinifigOut(
                fig_num=row.fig_num,
                name=row.name,
                num_parts=row.num_parts,
                img_url=row.img_url,
                theme_id=row.theme_id,
                theme_name=name,
                year=row.year,
                owned_quantity=quantity,
                # A minifig only ever has BrickLink quotes — it is never sold at retail, so no
                # store/marketplace step exists for it.
                resolved_price=resolve_minifig_price(
                    condition_by_fig.get(row.fig_num), quotes_by_set.get(row.fig_num, [])
                ),
                containing_set_nums=sets_by_fig.get(row.fig_num, [])[:12],
            )
        )

    match sort:
        case "partCount":
            results.sort(key=lambda row: row.num_parts, reverse=not ascending)
        case "year":
            results.sort(key=lambda row: (row.year or 0, row.fig_num), reverse=not ascending)
        case "price":
            results.sort(
                key=lambda row: (row.resolved_price is not None, row.resolved_price or 0.0),
                reverse=not ascending,
            )
        case _:
            results.sort(key=lambda row: row.name.lower(), reverse=not ascending)

    return {"count": len(results), "results": results[offset : offset + limit]}
