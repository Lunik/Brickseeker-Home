"""The batch updater's memory of when it last finished.

`BatchState` is in-memory, but "Dernière actualisation" on the Statistiques screen reads it — so a
restart used to make the app claim the prices had never been refreshed, whatever the database held.
The completion date is written on the way out and has to be read back on the way in.
"""

from __future__ import annotations

import pytest

from app.db import init_db, session_scope
from app.services import app_settings
from app.services.price_updater import PriceUpdater

SETTING = "collectionPriceUpdate.lastCompletedAt"


@pytest.fixture(autouse=True)
async def _database() -> None:
    """These are the only tests here that touch storage, so they create it themselves."""
    await init_db()


@pytest.mark.asyncio
async def test_restore_recovers_the_stored_completion_date() -> None:
    async with session_scope() as session:
        await app_settings.set_setting(session, SETTING, "2026-08-17T09:30:00+00:00")

    updater = PriceUpdater()  # a fresh process knows nothing
    assert updater.state["lastCompletedAt"] is None

    async with session_scope() as session:
        await updater.restore(session)

    restored = updater.state["lastCompletedAt"]
    assert restored is not None
    assert restored.isoformat() == "2026-08-17T09:30:00+00:00"


@pytest.mark.asyncio
async def test_restore_survives_an_unreadable_stored_value() -> None:
    """A hand-edited or pre-format value must not take the whole boot down with it."""
    async with session_scope() as session:
        await app_settings.set_setting(session, SETTING, "pas une date")

    updater = PriceUpdater()
    async with session_scope() as session:
        await updater.restore(session)

    assert updater.state["lastCompletedAt"] is None


@pytest.mark.asyncio
async def test_restore_never_overwrites_a_run_that_just_finished() -> None:
    """Restoring is a startup concern; a live value is newer than anything on disk."""
    async with session_scope() as session:
        await app_settings.set_setting(session, SETTING, "2020-01-01T00:00:00+00:00")

    updater = PriceUpdater()
    async with session_scope() as session:
        await updater.restore(session)
        first = updater.state["lastCompletedAt"]
        await app_settings.set_setting(session, SETTING, "2026-08-17T09:30:00+00:00")
        await updater.restore(session)

    assert updater.state["lastCompletedAt"] == first
