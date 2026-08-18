"""The in-process scheduler.

Replaces iOS's `BGAppRefreshTask`, which the system granted at its own discretion. A server is
always running, so the cadence here is honest: one tick per interval, each processing a bounded
number of overdue sets.

The watched scope stays **only the sets carrying an enabled alert** — not the collection, not the
gift list. That restriction is the entire answer to "background polling doesn't scale"; widening it
reopens the decision, and would also mean refreshing numbers no screen displays.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import settings
from ..db import session_scope
from ..security import purge_expired_sessions
from .price_updater import price_updater

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _watch_tick() -> None:
    try:
        processed = await price_updater.run_watch_pass(settings.background_refresh_batch_size)
        if processed:
            logger.info("Passe de surveillance : %s set(s) rafraîchi(s)", processed)
    except Exception:  # noqa: BLE001 - a failed tick must not kill the scheduler
        logger.warning("Passe de surveillance échouée", exc_info=True)


async def _purge_sessions() -> None:
    try:
        async with session_scope() as session:
            await purge_expired_sessions(session)
    except Exception:  # noqa: BLE001
        logger.warning("Purge des sessions échouée", exc_info=True)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _watch_tick,
        IntervalTrigger(minutes=settings.background_refresh_interval_minutes),
        id="price-watch",
        # A tick that overruns must not stack: the next one is skipped rather than queued, and
        # `run_watch_pass` refuses to start anyway while one is in flight.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _purge_sessions,
        CronTrigger(hour=3, minute=17),
        id="session-purge",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Planificateur démarré (surveillance des prix toutes les %s min)",
        settings.background_refresh_interval_minutes,
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
