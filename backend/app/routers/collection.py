"""The owned-sets collection.

Every remote mutation is mirrored into the local cache immediately. That is not an optimisation:
the list screens read the cache, not the API, so an add/move/remove that isn't written back leaves
a stale "in collection" state on screen — a documented trap in the iOS app.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from ..deps import ApiError, SessionDep, require_auth
from ..schemas import CamelModel, EntryOut, SetListOut, SetRowOut
from ..security import CredentialKey, has_credential
from ..services import catalog, collection_repo, rebrickable
from ..services.brickset import is_linked as brickset_is_linked
from ..services.pricing import (
    ListCondition,
    StoreAvailability,
    resolve_collection_price_detailed,
)

router = APIRouter(prefix="/collection", tags=["collection"], dependencies=[Depends(require_auth)])


class CollectionOut(CamelModel):
    sets: list[SetRowOut]
    lists: list[SetListOut]
    last_synced_at: datetime | None
    is_linked: bool
    brickset_linked: bool


class AddToCollectionIn(CamelModel):
    list_id: int | None = None


class UpdateCollectionIn(CamelModel):
    list_id: int | None = None
    quantity: int | None = None


class ListConditionIn(CamelModel):
    condition: ListCondition


class CreateListIn(CamelModel):
    name: str


class BulkIn(CamelModel):
    set_nums: list[str]
    action: str  # move | remove
    list_id: int | None = None


async def _rows(session) -> list[SetRowOut]:
    owned = await collection_repo.owned_sets(session)
    quotes_by_set = await collection_repo.all_cached_prices(session)
    conditions = await collection_repo.condition_by_list_id(session)
    theme_names = await catalog.theme_names(session)
    alerted = {alert.set_num for alert in await collection_repo.price_alerts(session) if alert.is_enabled}

    rows: list[SetRowOut] = []
    for cached in owned:
        condition = conditions.get(cached.current_list_id) if cached.current_list_id else None
        resolved = resolve_collection_price_detailed(
            cached.store_price_eur,
            condition,
            StoreAvailability.from_raw(cached.store_availability),
            quotes_by_set.get(cached.set_num, []),
        )
        rows.append(
            SetRowOut.of(
                cached,
                theme_name=theme_names.get(cached.theme_id, f"Thème #{cached.theme_id}"),
                resolved_price=resolved[0] if resolved else None,
                price_condition=resolved[1].value if resolved else None,
                # The label names the condition the amount *actually* represents, which is not
                # always the list's nominal one once the cross-fallback kicks in.
                price_label=resolved[1].display_name if resolved else None,
                has_price_alert=cached.set_num in alerted,
            )
        )
    return rows


async def _lists(session) -> list[SetListOut]:
    return [
        SetListOut(
            id=row.list_id, name=row.name, num_sets=row.num_sets, condition=row.condition
        )
        for row in await collection_repo.cached_set_lists(session)
    ]


@router.get("", response_model=CollectionOut)
async def read_collection(session: SessionDep) -> CollectionOut:
    return CollectionOut(
        sets=await _rows(session),
        lists=await _lists(session),
        last_synced_at=await collection_repo.last_full_sync_at(session),
        is_linked=await has_credential(session, CredentialKey.REBRICKABLE_USER_TOKEN),
        brickset_linked=await brickset_is_linked(session),
    )


async def _resync(session, client) -> None:  # noqa: ANN001
    user_sets = await client.fetch_all_user_sets()
    set_lists = await client.fetch_user_set_lists()
    await collection_repo.sync_collection(session, user_sets, set_lists)


@router.post("/sync", response_model=CollectionOut)
async def sync_collection(session: SessionDep) -> CollectionOut:
    await _resync(session, await rebrickable.client_for(session))
    return await read_collection(session)


@router.get("/lists")
async def read_lists(session: SessionDep) -> dict[str, object]:
    return {"lists": await _lists(session)}


@router.post("/lists", response_model=SetListOut)
async def create_list(payload: CreateListIn, session: SessionDep) -> SetListOut:
    client = await rebrickable.client_for(session)
    created = await client.create_set_list(payload.name)
    await collection_repo.cache_set_lists(session, [created])
    return SetListOut(id=created.id, name=created.name, num_sets=created.num_sets, condition="newSet")


@router.patch("/lists/{list_id}", response_model=SetListOut)
async def update_list_condition(list_id: int, payload: ListConditionIn, session: SessionDep) -> SetListOut:
    """The per-list condition is local: Rebrickable has no such concept, and it is what decides
    which price source values the sets inside that list."""
    await collection_repo.set_list_condition(session, list_id, payload.condition)
    for row in await collection_repo.cached_set_lists(session):
        if row.list_id == list_id:
            return SetListOut(
                id=row.list_id, name=row.name, num_sets=row.num_sets, condition=row.condition
            )
    raise ApiError("Liste introuvable", 404)


# Declared before the `/{set_num}` routes: Starlette matches in declaration order with no
# preference for literal paths, so a `/bulk` declared after them is dispatched to
# `add_to_collection(set_num="bulk")` — every bulk action then silently did the wrong thing.
@router.post("/bulk")
async def bulk_action(payload: BulkIn, session: SessionDep) -> dict[str, object]:
    """Bulk work reuses the single-set paths so the two can't drift. A per-set failure is reported
    rather than aborting the batch — a network blip on set 40 of 60 shouldn't undo the first 39."""
    client = await rebrickable.client_for(session)
    succeeded: list[str] = []
    failed: list[dict[str, str]] = []

    for set_num in payload.set_nums:
        try:
            if payload.action == "remove":
                await client.remove_set_from_collection(set_num)
                await collection_repo.set_collection_status(
                    session, set_num, is_in_collection=False, list_id=None, list_name=None
                )
            elif payload.action == "move":
                if payload.list_id is None:
                    raise ApiError("Choisis une liste de destination")
                cached = await collection_repo.cached_set(session, set_num)
                if cached and cached.current_list_id:
                    await client.move_set_to_list(set_num, cached.current_list_id, payload.list_id)
                else:
                    await client.add_set_to_list(set_num, payload.list_id)
                list_name = next(
                    (
                        row.name
                        for row in await collection_repo.cached_set_lists(session)
                        if row.list_id == payload.list_id
                    ),
                    None,
                )
                user_set = await client.fetch_user_set(set_num) if cached is None else None
                if user_set is not None:
                    # No cache row yet — a catalogue set added straight into a list, never
                    # opened first. `set_collection_status` no-ops without a row, so this needs
                    # the same fetch-and-upsert `add_to_collection` uses, or the move succeeds on
                    # Rebrickable and never appears in Ma collection until a full sync.
                    await collection_repo.cache_set(
                        session,
                        user_set.lego_set,
                        is_in_collection=True,
                        list_id=user_set.list_id or payload.list_id,
                        list_name=list_name,
                        mark_as_scanned=False,
                    )
                else:
                    await collection_repo.set_collection_status(
                        session,
                        set_num,
                        is_in_collection=True,
                        list_id=payload.list_id,
                        list_name=list_name,
                        from_list_id=cached.current_list_id if cached else None,
                    )
            else:
                raise ApiError(f"Action inconnue : {payload.action}")
        except ApiError as error:
            failed.append({"setNum": set_num, "error": error.detail})
        else:
            succeeded.append(set_num)

    return {"succeeded": succeeded, "failed": failed}


@router.post("/{set_num}")
async def add_to_collection(set_num: str, payload: AddToCollectionIn, session: SessionDep) -> dict:
    client = await rebrickable.client_for(session)
    if payload.list_id is None:
        raise ApiError("Choisis une liste de destination")
    await client.add_set_to_list(set_num, payload.list_id)

    # The add endpoint's response body is not reliably the nested Set shape, so authoritative
    # status is re-read rather than decoded from it.
    user_set = await client.fetch_user_set(set_num)
    list_name = next(
        (
            row.name
            for row in await collection_repo.cached_set_lists(session)
            if row.list_id == payload.list_id
        ),
        None,
    )
    if user_set is not None:
        await collection_repo.cache_set(
            session,
            user_set.lego_set,
            is_in_collection=True,
            list_id=user_set.list_id or payload.list_id,
            list_name=list_name,
            mark_as_scanned=False,
        )
    else:
        await collection_repo.set_collection_status(
            session, set_num, is_in_collection=True, list_id=payload.list_id, list_name=list_name
        )
    # `cache_set` only seeds an entry for a set with none: a second list needs its own.
    entries = {e.list_id for e in await collection_repo.set_entries(session, set_num)}
    if payload.list_id not in entries:
        await collection_repo.set_entry_quantity(session, set_num, payload.list_id, list_name, 1)
    return {"status": "inCollection", "listId": payload.list_id, "listName": list_name}


@router.delete("/{set_num}")
async def remove_from_collection(set_num: str, session: SessionDep, list_id: int | None = None) -> dict:
    """`list_id` drops the set from that list only; without it the set leaves every list."""
    client = await rebrickable.client_for(session)
    if list_id is not None:
        await client.remove_set_from_list(set_num, list_id)
        await collection_repo.set_entry_quantity(session, set_num, list_id, None, 0)
        cached = await collection_repo.cached_set(session, set_num)
        return {"status": "inCollection" if cached and cached.is_in_collection else "notInCollection"}
    await client.remove_set_from_collection(set_num)
    await collection_repo.set_collection_status(
        session, set_num, is_in_collection=False, list_id=None, list_name=None
    )
    return {"status": "notInCollection"}


async def _list_name(session, list_id: int) -> str | None:
    return next(
        (row.name for row in await collection_repo.cached_set_lists(session) if row.list_id == list_id),
        None,
    )


@router.patch("/{set_num}")
async def update_collection_entry(
    set_num: str, payload: UpdateCollectionIn, session: SessionDep
) -> dict:
    """Two shapes. `{listId, quantity}` sets the copies held in *that* list (0 drops it, a list the
    set isn't in yet adds it). `{listId}` alone moves the set's biggest list to `listId`; a bare
    `{quantity}` targets that biggest list too."""
    cached = await collection_repo.cached_set(session, set_num)
    if cached is None or not cached.is_in_collection:
        raise ApiError("Ce set n'est pas dans la collection", 404)

    client = await rebrickable.client_for(session)
    entries = {entry.list_id: entry for entry in await collection_repo.set_entries(session, set_num)}

    if payload.list_id is not None and payload.quantity is not None:
        list_id, quantity = payload.list_id, max(0, payload.quantity)
        list_name = await _list_name(session, list_id)
        if quantity == 0:
            if list_id in entries:
                await client.remove_set_from_list(set_num, list_id)
        else:
            if list_id not in entries:
                try:
                    await client.add_set_to_list(set_num, list_id)
                except ApiError as error:
                    if "already exists" not in error.detail:
                        raise
                    # Our cache missed a list Rebrickable already has (synced before entries were
                    # kept per list): reconcile instead of failing, and leave its quantity alone.
                    await _resync(session, client)
                    return await _entry_state(session, set_num)
            if quantity != 1 or list_id in entries:
                await client.update_set_quantity(set_num, list_id, quantity)
        await collection_repo.set_entry_quantity(session, set_num, list_id, list_name, quantity)
    elif payload.list_id is not None and payload.list_id not in entries:
        source = cached.current_list_id
        if source is None:
            await client.add_set_to_list(set_num, payload.list_id)
        else:
            # Rebrickable has no "change the list" endpoint: a move is a delete then an add.
            await client.move_set_to_list(set_num, source, payload.list_id)
        await collection_repo.set_collection_status(
            session,
            set_num,
            is_in_collection=True,
            list_id=payload.list_id,
            list_name=await _list_name(session, payload.list_id),
            from_list_id=source,
        )
    elif payload.quantity is not None and cached.current_list_id is not None:
        quantity = max(1, payload.quantity)
        await client.update_set_quantity(set_num, cached.current_list_id, quantity)
        await collection_repo.set_entry_quantity(
            session, set_num, cached.current_list_id, cached.current_list_name, quantity
        )

    return await _entry_state(session, set_num)


async def _entry_state(session, set_num: str) -> dict:  # noqa: ANN001
    refreshed = await collection_repo.cached_set(session, set_num)
    return {
        "status": "inCollection" if refreshed and refreshed.is_in_collection else "notInCollection",
        "listId": refreshed.current_list_id if refreshed else None,
        "listName": refreshed.current_list_name if refreshed else None,
        "quantity": refreshed.quantity if refreshed else 0,
        "entries": [
            EntryOut(list_id=e.list_id, list_name=e.list_name, quantity=e.quantity).model_dump(by_alias=True)
            for e in await collection_repo.set_entries(session, set_num)
        ],
    }
