"""What a user action changes locally, with only the third-party client faked."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models import CachedSet, CatalogMinifig, CatalogSet, CatalogTheme, Credential
from app.services import collection_repo
from app.services.pricing import ListCondition
from app.services.rebrickable import LegoSet, SetList, UserSet


def _set(set_num: str) -> LegoSet:
    return LegoSet(
        set_num=set_num,
        name=f"Set {set_num}",
        year=2022,
        theme_id=1,
        num_parts=100,
        set_img_url=None,
        set_url=None,
    )


async def _scan(session, set_num: str) -> None:  # noqa: ANN001 - fixture session
    await collection_repo.cache_set(
        session, _set(set_num), is_in_collection=False, list_id=None, list_name=None, mark_as_scanned=True
    )


LISTS = [SetList(id=1, name="displayed", num_sets=1), SetList(id=2, name="stored", num_sets=0)]


@pytest.fixture
async def owned(session) -> None:  # noqa: ANN001 - fixture session
    await collection_repo.sync_collection(
        session,
        [UserSet(lego_set=_set("10307-1"), quantity=1, include_spares=False, list_id=1)],
        LISTS,
    )


@pytest.fixture
def rebrickable_client():  # noqa: ANN201 - a fake
    fake = AsyncMock()
    with patch("app.routers.collection.rebrickable.client_for", AsyncMock(return_value=fake)):
        yield fake


@pytest.mark.usefixtures("owned")
class TestCollectionActions:
    async def test_removing_a_set_updates_rebrickable_then_the_cache(
        self, client, session, rebrickable_client
    ) -> None:  # noqa: ANN001
        assert (await client.delete("/api/collection/10307-1")).status_code == 200

        rebrickable_client.remove_set_from_collection.assert_awaited_once_with("10307-1")
        row = await collection_repo.cached_set(session, "10307-1")
        assert row is None or row.is_in_collection is False

    async def test_failed_removal_on_rebrickable_keeps_the_set_owned(self, client, session, rebrickable_client) -> None:  # noqa: ANN001, E501
        from app.deps import network_unavailable

        rebrickable_client.remove_set_from_collection.side_effect = network_unavailable()

        assert (await client.delete("/api/collection/10307-1")).status_code == 503
        assert (await collection_repo.cached_set(session, "10307-1")).is_in_collection is True

    async def test_bulk_move_reports_each_failure_and_keeps_going(self, client, session, rebrickable_client) -> None:  # noqa: ANN001, E501
        from app.deps import network_unavailable

        await collection_repo.cache_set(
            session,
            _set("75192-1"),
            is_in_collection=True,
            list_id=1,
            list_name="displayed",
            mark_as_scanned=False,
        )
        rebrickable_client.move_set_to_list.side_effect = [network_unavailable(), None]

        response = await client.post(
            "/api/collection/bulk",
            json={"action": "move", "setNums": ["10307-1", "75192-1"], "listId": 2},
        )

        body = response.json()
        assert [failure["setNum"] for failure in body["failed"]] == ["10307-1"]
        assert body["succeeded"] == ["75192-1"]
        assert (await collection_repo.cached_set(session, "10307-1")).current_list_id == 1
        assert (await collection_repo.cached_set(session, "75192-1")).current_list_name == "stored"

    async def test_list_condition_is_kept_and_read_back(self, client, session) -> None:  # noqa: ANN001
        response = await client.patch("/api/collection/lists/2", json={"condition": "used"})

        assert response.status_code == 200
        assert (await collection_repo.condition_by_list_id(session))[2] is ListCondition.USED


class TestWishlist:
    async def test_lists_only_wanted_sets(self, client, session) -> None:  # noqa: ANN001
        await collection_repo.cache_wishlist_set(session, _set("10307-1"))
        await collection_repo.set_wishlist_status(session, "10307-1", True)
        await _scan(session, "75192-1")

        rows = (await client.get("/api/wishlist")).json()["sets"]

        assert [row["setNum"] for row in rows] == ["10307-1"]

    async def test_sync_follows_brickset_without_creating_rows(self, session) -> None:  # noqa: ANN001
        await collection_repo.cache_wishlist_set(session, _set("10307-1"))
        await collection_repo.set_wishlist_status(session, "10307-1", True)

        await collection_repo.sync_wishlist(session, {"99999-1"})

        assert (await collection_repo.cached_set(session, "10307-1")).is_in_wishlist is False
        assert await collection_repo.cached_set(session, "99999-1") is None
        assert await collection_repo.last_wishlist_sync_at(session) is not None


class TestScanEvents:
    async def test_price_is_edited_and_the_event_removed(self, client, session) -> None:  # noqa: ANN001
        await _scan(session, "10307-1")
        event = await collection_repo.record_scan_event(session, "10307-1", price_seen_eur=20.0)

        patched = await client.patch(f"/api/history/events/{event.id}", json={"priceSeenEur": 18.0})
        assert patched.json()["priceSeenEur"] == 18.0

        assert (await client.delete(f"/api/history/events/{event.id}")).status_code == 200
        assert await collection_repo.scan_events(session, "10307-1") == []


class TestSettings:
    async def test_a_credential_is_reported_but_never_returned(self, client, session) -> None:  # noqa: ANN001
        put = await client.put("/api/settings/credentials/rebrickable-key", json={"apiKey": "s3cret-key"})
        assert put.status_code == 200

        response = await client.get("/api/settings")

        assert response.json()["credentials"]["rebrickableApiKey"] is True
        assert "s3cret-key" not in response.text
        stored = await session.get(Credential, "rebrickable_api_key")
        assert "s3cret-key" not in stored.value_encrypted

    async def test_preferences_round_trip(self, client) -> None:  # noqa: ANN001
        response = await client.patch("/api/settings/preferences", json={"appTheme.brandColor": "blue"})

        assert response.status_code == 200
        preferences = (await client.get("/api/settings")).json()["preferences"]
        assert preferences["appTheme.brandColor"] == "blue"

    async def test_clear_cache_keeps_the_paid_price(self, client, session) -> None:  # noqa: ANN001
        await _scan(session, "10307-1")
        await collection_repo.set_paid_price(session, "10307-1", 12.5)

        assert (await client.post("/api/settings/clear-cache")).status_code == 200

        assert await session.get(CachedSet, "10307-1") is None
        assert await collection_repo.paid_price(session, "10307-1") == 12.5


class TestCatalogue:
    @pytest.fixture(autouse=True)
    async def catalogue(self, session) -> None:  # noqa: ANN001
        session.add(CatalogTheme(theme_id=1, name="Icons", parent_id=None))
        session.add_all(
            [
                CatalogSet(
                    set_num="10307-1",
                    name="Eiffel Tower",
                    year=2022,
                    theme_id=1,
                    num_parts=10001,
                    first_seen_at=datetime(2026, 1, 1),
                ),
                CatalogSet(
                    set_num="10316-1",
                    name="Rivendell",
                    year=2023,
                    theme_id=1,
                    num_parts=6167,
                    first_seen_at=datetime(2026, 2, 1),
                ),
                CatalogMinifig(fig_num="fig-000001", name="Gandalf", num_parts=4),
            ]
        )
        await session.commit()

    async def test_new_sets_are_those_seen_after_the_first_snapshot(self, client) -> None:  # noqa: ANN001
        body = (await client.get("/api/catalog/new-sets")).json()

        assert body["count"] == 1
        assert [row["setNum"] for row in body["results"]] == ["10316-1"]

    async def test_full_catalogue_can_be_searched(self, client) -> None:  # noqa: ANN001
        params = {"includeAll": "true", "search": "eiffel"}
        body = (await client.get("/api/catalog/new-sets", params=params)).json()

        assert [row["setNum"] for row in body["results"]] == ["10307-1"]

    async def test_count_is_the_total_not_the_page_size(self, client) -> None:  # noqa: ANN001
        params = {"includeAll": "true", "limit": 1}
        body = (await client.get("/api/catalog/new-sets", params=params)).json()

        assert body["count"] == 2
        assert len(body["results"]) == 1

    async def test_minifigs_are_listed(self, client) -> None:  # noqa: ANN001
        body = (await client.get("/api/catalog/minifigs", params={"ownedOnly": "false"})).json()

        assert body["count"] == 1
