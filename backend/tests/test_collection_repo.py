"""The rules `AGENTS.md` calls non-negotiable, checked against a real database."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import (
    CachedSet,
    CachedSetList,
    CachedSetPrice,
    CollectionValueSnapshot,
    PriceHistoryEntry,
    ScanEvent,
    SetPurchaseRecord,
)
from app.services import alerts, collection_repo, notifications
from app.services.pricing import ListCondition, PriceQuote, PriceSource
from app.services.rebrickable import LegoSet, SetList, UserSet


def lego_set(set_num: str = "10307-1", name: str = "Eiffel Tower") -> LegoSet:
    return LegoSet(
        set_num=set_num, name=name, year=2022, theme_id=1, num_parts=100, set_img_url=None, set_url=None
    )


def user_set(set_num: str, list_id: int = 1, quantity: int = 1) -> UserSet:
    return UserSet(lego_set=lego_set(set_num), quantity=quantity, include_spares=False, list_id=list_id)


LISTS = [SetList(id=1, name="displayed", num_sets=1), SetList(id=2, name="stored", num_sets=0)]


async def scan(session, set_num: str = "10307-1") -> None:  # noqa: ANN001 - fixture session
    await collection_repo.cache_set(
        session,
        lego_set(set_num),
        is_in_collection=False,
        list_id=None,
        list_name=None,
        mark_as_scanned=True,
    )


class TestSyncCollection:
    async def test_creates_owned_rows_with_list_and_quantity(self, session) -> None:  # noqa: ANN001
        await collection_repo.sync_collection(session, [user_set("10307-1", quantity=3)], LISTS)

        row = await collection_repo.cached_set(session, "10307-1")
        assert (row.is_in_collection, row.current_list_name, row.quantity, row.was_scanned) == (
            True,
            "displayed",
            3,
            False,
        )
        assert await collection_repo.last_full_sync_at(session) is not None

    async def test_set_in_several_lists_keeps_its_first_list(self, session) -> None:  # noqa: ANN001
        await collection_repo.sync_collection(
            session, [user_set("10307-1", list_id=2), user_set("10307-1", list_id=1)], LISTS
        )

        assert (await collection_repo.cached_set(session, "10307-1")).current_list_name == "stored"

    async def test_scanned_flag_survives_a_sync(self, session) -> None:  # noqa: ANN001
        await scan(session)

        await collection_repo.sync_collection(session, [user_set("10307-1")], LISTS)

        row = await collection_repo.cached_set(session, "10307-1")
        assert row.was_scanned is True
        assert row.is_in_collection is True

    async def test_scanned_set_leaving_the_collection_stays_in_history(self, session) -> None:  # noqa: ANN001
        await scan(session)
        await collection_repo.sync_collection(session, [user_set("10307-1")], LISTS)

        await collection_repo.sync_collection(session, [], LISTS)

        row = await collection_repo.cached_set(session, "10307-1")
        assert (row.is_in_collection, row.current_list_id, row.was_scanned) == (False, None, True)

    async def test_sync_only_set_leaving_the_collection_is_deleted(self, session) -> None:  # noqa: ANN001
        await collection_repo.sync_collection(session, [user_set("10307-1")], LISTS)

        await collection_repo.sync_collection(session, [], LISTS)

        assert await collection_repo.cached_set(session, "10307-1") is None

    async def test_owning_a_set_erases_where_it_was_scanned(self, session) -> None:  # noqa: ANN001
        await scan(session)
        event = await collection_repo.record_scan_event(session, "10307-1", price_seen_eur=None)
        event.latitude, event.longitude = 48.85, 2.35
        await session.commit()

        await collection_repo.sync_collection(session, [user_set("10307-1")], LISTS)

        await session.refresh(event)
        assert (event.latitude, event.longitude) == (None, None)


class TestClearCache:
    async def test_purges_what_can_be_downloaded_again(self, session) -> None:  # noqa: ANN001
        await collection_repo.sync_collection(session, [user_set("10307-1")], LISTS)
        await collection_repo.cache_prices(
            session, [PriceQuote(source=PriceSource.AMAZON, amount=30.0)], "10307-1", reconcile=True
        )

        await collection_repo.clear_cache(session)

        for model in (CachedSet, CachedSetList, CachedSetPrice):
            assert (await session.execute(select(model))).scalars().first() is None
        assert await collection_repo.last_full_sync_at(session) is None

    async def test_keeps_what_exists_nowhere_else(self, session) -> None:  # noqa: ANN001
        await scan(session)
        event = await collection_repo.record_scan_event(session, "10307-1", price_seen_eur=20.0)
        event.latitude, event.longitude = 48.85, 2.35
        await session.commit()
        await collection_repo.set_paid_price(session, "10307-1", 15.0)
        await collection_repo.upsert_price_alert(
            session, "10307-1", ListCondition.NEW, threshold_eur=10.0
        )
        await collection_repo.record_price_history(session, "10307-1", "amazon", 30.0, "EUR")
        session.add(
            CollectionValueSnapshot(
                day_key="2026-03-01",
                captured_at=datetime(2026, 3, 1),
                total_value_eur=100.0,
                sets_count=1,
                units_count=1,
                priced_sets_count=1,
            )
        )
        await session.commit()

        await collection_repo.clear_cache(session)

        assert await collection_repo.paid_price(session, "10307-1") == 15.0
        assert len(await collection_repo.price_alerts(session)) == 1
        for model in (SetPurchaseRecord, PriceHistoryEntry, CollectionValueSnapshot):
            assert (await session.execute(select(model))).scalars().first() is not None
        kept = (await session.execute(select(ScanEvent))).scalars().one()
        await session.refresh(kept)
        assert kept.price_seen_eur == 20.0
        assert kept.latitude is None


class TestDeleteFromHistory:
    async def test_owned_set_only_loses_the_scanned_flag(self, session) -> None:  # noqa: ANN001
        await scan(session)
        await collection_repo.sync_collection(session, [user_set("10307-1")], LISTS)

        await collection_repo.delete_from_history(session, "10307-1")

        row = await collection_repo.cached_set(session, "10307-1")
        assert (row.is_in_collection, row.was_scanned) == (True, False)

    async def test_unowned_set_goes_with_its_scan_events(self, session) -> None:  # noqa: ANN001
        await scan(session)
        await collection_repo.record_scan_event(session, "10307-1", price_seen_eur=None)

        await collection_repo.delete_from_history(session, "10307-1")

        assert await collection_repo.cached_set(session, "10307-1") is None
        assert await collection_repo.scan_events(session, "10307-1") == []


class TestCachePrices:
    async def test_reconcile_removes_a_source_that_went_silent(self, session) -> None:  # noqa: ANN001
        await scan(session)
        both = [
            PriceQuote(source=PriceSource.AMAZON, amount=30.0),
            PriceQuote(source=PriceSource.CDISCOUNT, amount=25.0),
        ]
        await collection_repo.cache_prices(session, both, "10307-1", reconcile=True)

        await collection_repo.cache_prices(session, both[:1], "10307-1", reconcile=True)

        quotes = await collection_repo.cached_prices(session, "10307-1")
        assert [quote.source for quote in quotes] == [PriceSource.AMAZON]

    async def test_partial_write_keeps_the_other_sources(self, session) -> None:  # noqa: ANN001
        await scan(session)
        await collection_repo.cache_prices(
            session, [PriceQuote(source=PriceSource.AMAZON, amount=30.0)], "10307-1", reconcile=False
        )

        await collection_repo.cache_prices(
            session, [PriceQuote(source=PriceSource.CDISCOUNT, amount=25.0)], "10307-1", reconcile=False
        )

        assert len((await collection_repo.all_cached_prices(session))["10307-1"]) == 2

    async def test_history_keeps_one_reading_per_day_and_source(self, session) -> None:  # noqa: ANN001
        await collection_repo.record_price_history(session, "10307-1", "amazon", 30.0, "EUR")
        await collection_repo.record_price_history(session, "10307-1", "amazon", 31.0, "EUR")
        await session.commit()

        assert len(await collection_repo.price_history(session, "10307-1")) == 1


class TestPaidPrice:
    async def test_null_clears_it(self, session) -> None:  # noqa: ANN001
        await collection_repo.set_paid_price(session, "10307-1", 15.0)
        assert await collection_repo.paid_price_by_set_num(session) == {"10307-1": 15.0}

        await collection_repo.set_paid_price(session, "10307-1", None)

        assert await collection_repo.paid_price(session, "10307-1") is None


class TestAlertEvaluation:
    @pytest.fixture
    async def alert(self, session):  # noqa: ANN001, ANN201 - fixture session, ORM row
        await scan(session)
        return await collection_repo.upsert_price_alert(
            session, "10307-1", ListCondition.USED, threshold_eur=20.0
        )

    @staticmethod
    async def price_at(session, amount: float) -> None:  # noqa: ANN001
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        quote = PriceQuote(source=PriceSource.BRICKLINK_USED, amount=amount, fetched_at=fetched_at)
        await collection_repo.cache_prices(session, [quote], "10307-1", reconcile=True)

    async def test_fires_when_the_threshold_is_crossed(self, session, alert) -> None:  # noqa: ANN001
        await self.price_at(session, 19.0)

        assert await alerts.evaluate_alerts(session, "10307-1") == [alert]
        rows, unread = await notifications.list_notifications(session)
        assert (len(rows), unread) == (1, 1)

    async def test_stays_quiet_above_the_threshold(self, session, alert) -> None:  # noqa: ANN001
        await self.price_at(session, 21.0)

        assert await alerts.evaluate_alerts(session, "10307-1") == []
        assert alert.last_observed_price_eur == 21.0

    async def test_fires_once_while_the_price_stays_low(self, session, alert) -> None:  # noqa: ANN001
        await self.price_at(session, 19.0)
        await alerts.evaluate_alerts(session, "10307-1")

        await self.price_at(session, 18.0)

        assert await alerts.evaluate_alerts(session, "10307-1") == []

    async def test_disabled_alert_never_fires(self, session, alert) -> None:  # noqa: ANN001
        await collection_repo.set_price_alert_enabled(session, alert.id, False)
        await self.price_at(session, 19.0)

        assert await alerts.evaluate_alerts(session, "10307-1") == []
