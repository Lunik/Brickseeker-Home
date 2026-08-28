"""The offline catalogues: download, purge, and the two discovery screens they feed.

Both discovery screens (Nouveaux sets, galerie de minifigs) apply the non-set filter — they
*suggest* items. Collection, Historique and Liste cadeaux never do: a LEGO cap you own is still
yours, and a set count that silently drops because of a Réglages toggle reads as a bug.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from ..db import session_scope
from ..deps import ApiError, SessionDep, require_auth
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


@router.get("/export")
async def export(session: SessionDep, name: str = Query()) -> StreamingResponse:
    """The client's own offline copy: the whole downloaded catalogue as NDJSON, one row per line.

    Streamed rather than one JSON array so neither side has to hold ~28 000 (sets) or ~12 000
    (minifigs) rows serialized in memory at once. Never owned-only or since-first-download
    filtered, unlike `/new-sets` and `/minifigs` — offline identification needs the whole thing.
    """
    if name == "sets":
        return StreamingResponse(catalog.export_sets(session), media_type="application/x-ndjson")
    if name == "minifigs":
        return StreamingResponse(catalog.export_minifigs(session), media_type="application/x-ndjson")
    raise ApiError(f"Catalogue non exportable : {name}")


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


@router.get("/new-sets/filter-options")
async def new_sets_filter_options(
    session: SessionDep,
    include_all: bool = Query(default=False, alias="includeAll"),
) -> dict[str, object]:
    """Theme and year choices for Nouveaux sets, over its whole scope — not just the current page.

    `SetListScreen` normally derives filter options from the `rows` it was handed, which is correct
    for a client-filtered screen (`rows` is everything) but not for this `serverFiltered` one:
    `rows` there is one 60-row page, so the dropdown offered only whatever themes/years happened to
    land on it, and picking anything else showed nothing (#finding-10). Scoped by `includeAll` the
    same way `/new-sets` itself is, so the choices always match what that call would actually find.
    """
    hide_enabled = bool(await app_settings.get_setting(session, "hide_wearables_enabled"))
    theme_names = await catalog.theme_names(session)

    query_stmt = select(CatalogSet.theme_id, CatalogSet.year).distinct()
    baseline = (await session.execute(select(func.min(CatalogSet.first_seen_at)))).scalar_one_or_none()
    if not include_all and baseline is not None:
        query_stmt = query_stmt.where(CatalogSet.first_seen_at > baseline)
    pairs = (await session.execute(query_stmt)).all()

    theme_ids = {theme_id for theme_id, _ in pairs}
    years = {year for _, year in pairs if year > 0}
    visible_theme_ids = {
        theme_id for theme_id in theme_ids if not await catalog.should_hide(session, theme_id, hide_enabled)
    }
    themes_out = sorted({theme_names.get(theme_id, f"Thème #{theme_id}") for theme_id in visible_theme_ids})
    return {"themes": themes_out, "years": sorted(years, reverse=True)}


@router.get("/new-sets")
async def new_sets(
    session: SessionDep,
    search: str | None = None,
    theme_name: str | None = Query(default=None, alias="themeName"),
    year: int | None = None,
    owned_only: bool | None = Query(default=None, alias="ownedOnly"),
    availability: str | None = None,
    sort: str = "dateAdded",
    ascending: bool = False,
    offset: int = 0,
    limit: int = Query(default=60, le=200),
    include_all: bool = Query(default=False, alias="includeAll"),
) -> dict[str, object]:
    """The sets that appeared in the catalogue *since the first download*.

    Not the whole catalogue: every row of the first-ever import shares one `first_seen_at`, so
    without excluding that baseline this screen would list all ~28 000 entries and the word "new"
    would mean nothing. `includeAll=true` opts back into the full catalogue for browsing.

    Default sort is `dateAdded` — when *this* install first saw the set — which is a truer "new"
    signal than the release year. `dateScanned` is meaningless here: a catalogue entry was never
    scanned.
    """
    hide_enabled = bool(await app_settings.get_setting(session, "hide_wearables_enabled"))
    theme_names = await catalog.theme_names(session)

    query = select(CatalogSet)
    baseline = (await session.execute(select(func.min(CatalogSet.first_seen_at)))).scalar_one_or_none()
    if not include_all and baseline is not None:
        query = query.where(CatalogSet.first_seen_at > baseline)
    rows = (await session.execute(query)).scalars().all()
    owned = {cached.set_num: cached for cached in await collection_repo.owned_sets(session)}
    cached_by_num = {row.set_num: row for row in await collection_repo.all_cached_sets(session)}

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

    results = _sort_results(results, sort, ascending)
    return {
        "count": len(results),
        "results": results[offset : offset + limit],
        "isFiltered": not include_all and baseline is not None,
    }


def _sort_nulls_last(rows: list, value_of, *, ascending: bool) -> list:
    """Sorts by `value_of`, with rows whose value is `None` always trailing — independent of
    `ascending`.

    A `(has_value, value)` tuple key can't do this: `reverse=not ascending` flips the has-value
    partition along with the value order, so "Prix croissant" put every unpriced set *first* —
    `False < True` wins when not reversed. Keeping the None/non-None split outside the reversible
    key, as a separate pass, is what `useFilterState.ts`'s `compareNullable` also does client-side.
    """
    present = [row for row in rows if value_of(row) is not None]
    missing = [row for row in rows if value_of(row) is None]
    present.sort(key=value_of, reverse=not ascending)
    return [*present, *missing]


def _sort_results(results: list, sort: str, ascending: bool) -> list:
    match sort:
        case "year":
            # `year` ties constantly — it is the finest date Rebrickable exposes, so hundreds of
            # sets share one value. `set_num` is not a chronological claim, only a stable one, so
            # the list stops reshuffling ties between reloads. Never `None`, so no null handling.
            results.sort(key=lambda row: (row.year, row.set_num), reverse=not ascending)
            return results
        case "name":
            results.sort(key=lambda row: row.name.lower(), reverse=not ascending)
            return results
        case "partCount":
            results.sort(key=lambda row: row.num_parts, reverse=not ascending)
            return results
        case "price":
            return _sort_nulls_last(results, lambda row: row.resolved_price, ascending=ascending)
        case _:
            return _sort_nulls_last(results, lambda row: row.first_seen_at, ascending=ascending)


@router.get("/minifigs/filter-options")
async def minifigs_filter_options(
    session: SessionDep,
    owned_only: bool = Query(default=True, alias="ownedOnly"),
) -> dict[str, object]:
    """Theme and year choices for the minifig gallery, over its whole scope — see
    `new_sets_filter_options` for why `rows`-derived options are wrong on a `serverFiltered`
    screen. Mirrors `owned_only` the same way the gallery itself does: with it on, a theme the
    user owns nothing in is not a useful filter choice, so it isn't offered.
    """
    theme_names = await catalog.theme_names(session)
    rows = (await session.execute(select(CatalogMinifig))).scalars().all()

    if owned_only:
        owned_set_nums = {cached.set_num for cached in await collection_repo.owned_sets(session)}
        pivots = (await session.execute(select(CatalogMinifigSet))).scalars().all()
        owned_fig_nums = {pivot.fig_num for pivot in pivots if pivot.set_num in owned_set_nums}
        rows = [row for row in rows if row.fig_num in owned_fig_nums]

    theme_ids = {row.theme_id for row in rows if row.theme_id is not None}
    years = {row.year for row in rows if row.year}
    themes_out = sorted({theme_names.get(theme_id, f"Thème #{theme_id}") for theme_id in theme_ids})
    return {"themes": themes_out, "years": sorted(years, reverse=True)}


@router.get("/minifigs")
async def minifigs(
    session: SessionDep,
    search: str | None = None,
    theme_name: str | None = Query(default=None, alias="themeName"),
    year: int | None = None,
    owned_only: bool = Query(default=True, alias="ownedOnly"),
    sort: str = "name",
    ascending: bool = True,
    offset: int = 0,
    #: The ceiling is high because the gallery screen filters and sorts client-side and therefore
    #: needs the whole owned set in one payload — capped at 200 it silently showed 200 of 601 while
    #: Accueil, reading the same endpoint's `count`, said 601. The cost of a larger page is only
    #: serialisation: this handler already walks every pivot and every catalogue row before slicing.
    limit: int = Query(default=60, le=5000),
) -> dict[str, object]:
    """The owned-minifig gallery.

    A minifig is owned when any set containing it is owned, and the quantity multiplies through:
    two copies of a set with two of the same minifig is four.

    `count` is the total **after filtering and before slicing** — the number a caller needs to know
    whether what it received is everything.
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
            results = _sort_nulls_last(results, lambda row: row.resolved_price, ascending=ascending)
        case _:
            results.sort(key=lambda row: row.name.lower(), reverse=not ascending)

    return {"count": len(results), "results": results[offset : offset + limit]}
