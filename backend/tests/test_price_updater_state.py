"""The batch updater's memory of when it last finished.

`BatchState` is in-memory, but "Dernière actualisation" on the Statistiques screen reads it — so a
restart used to make the app claim the prices had never been refreshed, whatever the database held.
The completion date is written on the way out and has to be read back on the way in.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

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


@pytest.mark.asyncio
async def test_immediate_cancel_cannot_leave_batch_stuck_running() -> None:
    updater = PriceUpdater()
    with patch.object(updater, "_build_queue", new=AsyncMock(return_value=["12345"])):
        assert await updater.start(["12345"]) == "started"
        await updater.cancel_preserving_progress()

    assert updater.state["isRunning"] is False
    assert updater.state["currentSetNum"] is None
    assert updater.state["hasPendingQueue"] is True


def test_source_timeout_is_reported_as_non_fatal_warning() -> None:
    updater = PriceUpdater()

    updater._on_source_progress("amazon", "started")
    assert updater.state["pendingSources"] == ["amazon"]

    updater._on_source_progress("amazon", "timed_out")
    assert updater.state["pendingSources"] == []
    assert updater.state["sourceFailures"] == 1
    assert "Amazon" in str(updater.state["warning"])
    assert updater.state["error"] is None


def test_captcha_is_reported_without_counting_as_source_failure() -> None:
    updater = PriceUpdater()

    updater._on_source_progress("fnac", "started")
    updater._on_source_progress("fnac", "captcha_required")

    assert updater.state["pendingSources"] == []
    assert updater.state["captchaRequiredSources"] == ["fnac"]
    assert updater.state["sourceFailures"] == 0
    assert "CAPTCHA" in str(updater.state["warning"])


@pytest.mark.asyncio
async def test_cancelled_batch_resumes_without_resetting_progress() -> None:
    updater = PriceUpdater()
    second_started = asyncio.Event()
    second_cancelled = asyncio.Event()

    async def first_run(_session, lego_set, **_kwargs):
        if lego_set.set_num == "first":
            return {}
        second_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            second_cancelled.set()

    with (
        patch.object(updater, "_build_queue", new=AsyncMock(return_value=["first", "second"])),
        patch("app.services.price_updater.prices.refresh_set_prices", side_effect=first_run),
        patch("app.services.price_updater.settings.scrape_delay_between_sets", 0),
    ):
        assert await updater.start(["first", "second"]) == "started"
        await asyncio.wait_for(second_started.wait(), timeout=0.5)
        await updater.cancel_preserving_progress()

    await asyncio.wait_for(second_cancelled.wait(), timeout=0.2)
    assert updater.state["done"] == 1
    assert updater.state["total"] == 2
    assert updater.state["hasPendingQueue"] is True

    finish = AsyncMock()
    with (
        patch("app.services.price_updater.prices.refresh_set_prices", new=AsyncMock(return_value={})),
        patch.object(updater, "_finish", new=finish),
    ):
        assert await updater.start() == "started"
        task = updater._task
        assert task is not None
        await task

    assert updater.state["done"] == 2
    assert updater.state["total"] == 2
    assert updater.state["hasPendingQueue"] is False
    assert updater.state["isRunning"] is False
    finish.assert_awaited_once()
