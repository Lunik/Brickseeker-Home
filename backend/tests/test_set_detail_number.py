"""Opening a set by the number printed on its box must not forget that the set is owned."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from app.deps import ApiError
from app.models import CachedSet, CatalogSet
from app.routers.sets import set_detail
from app.services import collection_repo
from app.services.rebrickable import LegoSet

FERRARI = LegoSet(
    set_num="76906-1",
    name="1970 Ferrari 512 M",
    year=2022,
    theme_id=601,
    num_parts=291,
    set_img_url=None,
    set_url=None,
)


async def _own_ferrari(session) -> None:  # noqa: ANN001 - fixture session
    await collection_repo.cache_set(
        session, FERRARI, is_in_collection=True, list_id=7, list_name="displayed", mark_as_scanned=False
    )
    row = await session.get(CachedSet, "76906-1")
    row.quantity = 2
    row.prices_fetched_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()


async def _rebrickable_answers_404(*_args, **_kwargs):  # noqa: ANN002, ANN003
    raise ApiError("Ressource introuvable", 404)


@pytest.mark.parametrize("number", ["76906", "76906-1"])
async def test_owned_set_stays_owned_whatever_the_number_form(session, number: str) -> None:  # noqa: ANN001
    await _own_ferrari(session)

    with patch("app.routers.sets.rebrickable.client_for", _rebrickable_answers_404):
        detail = await set_detail(number, session, BackgroundTasks())

    row = await session.get(CachedSet, "76906-1")
    assert (row.is_in_collection, row.current_list_id, row.current_list_name, row.quantity) == (
        True,
        7,
        "displayed",
        2,
    )
    assert detail.is_in_collection is True
    assert detail.current_list_name == "displayed"
    assert detail.set.set_num == "76906-1"
    assert detail.is_offline_result is False


async def test_bare_number_reads_the_prices_of_the_full_number(session) -> None:  # noqa: ANN001
    await _own_ferrari(session)
    assessed_prices = AsyncMock(return_value=[])

    with patch("app.routers.sets.collection_repo.assessed_prices", assessed_prices):
        await set_detail("76906", session, BackgroundTasks())

    assessed_prices.assert_awaited_once_with(session, "76906-1")


async def test_set_found_only_in_the_catalogue_is_cached_as_not_owned(session) -> None:  # noqa: ANN001
    session.add(CatalogSet(set_num="76906-1", name=FERRARI.name, year=2022, theme_id=601, num_parts=291))
    await session.commit()

    with (
        patch("app.routers.sets.rebrickable.client_for", _rebrickable_answers_404),
        patch("app.routers.sets.prices.claim_background_refresh", return_value=False),
    ):
        detail = await set_detail("76906", session, BackgroundTasks())

    assert detail.is_offline_result is True
    assert detail.is_in_collection is False
    assert (await session.get(CachedSet, "76906-1")) is not None
    assert (await session.get(CachedSet, "76906")) is None
