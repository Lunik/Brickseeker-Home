"""The collection-wide price batch, and the bounded background watch pass.

Two runs, deliberately on **separate tracks**:

* the **manual batch** — started explicitly from Réglages or from a list selection, strictly
  sequential with a delay between sets. That slowness is the design, not a limitation to optimise:
  every set means driving a headless browser through a Cloudflare challenge, and running dozens of
  those concurrently across a whole collection is exactly what gets an IP flagged as abusive.
* the **watch pass** — a scheduler tick over the sets carrying an enabled alert. BrickLink only:
  there is no browser worth spinning up from a background job, and BrickLink is a plain signed API
  call. It never stamps `prices_fetched_at`, because it only asked one source — stamping "every
  source tried" would drop the set out of "Compléter les prix manquants" without lego.com or
  Amazon ever having been asked.

Each guards against the other so the two never overlap, and neither can cancel the other.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..config import settings
from ..db import session_scope
from . import app_settings, collection_repo, notifications, prices
from .pricing import StoreAvailability, resolve_collection_price
from .rebrickable import LegoSet

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchState:
    is_running: bool = False
    done: int = 0
    total: int = 0
    current_set_num: str | None = None
    mode: str | None = None
    last_completed_at: datetime | None = None
    error: str | None = None
    #: The remaining queue, kept so a cancel preserves progress and the next start resumes rather
    #: than restarting from zero.
    queue: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "isRunning": self.is_running,
            "done": self.done,
            "total": self.total,
            "currentSetNum": self.current_set_num,
            "mode": self.mode,
            "lastCompletedAt": self.last_completed_at,
            "error": self.error,
            "hasPendingQueue": bool(self.queue),
        }


class PriceUpdater:
    def __init__(self) -> None:
        self._state = BatchState()
        self._cancel_requested = False
        self._task: asyncio.Task[None] | None = None
        self._watch_running = False

    # --- Manual batch ----------------------------------------------------------------

    @property
    def state(self) -> dict[str, object]:
        return self._state.as_dict()

    @property
    def is_watch_running(self) -> bool:
        return self._watch_running

    async def start(self, set_nums: list[str] | None = None, *, only_missing: bool = False) -> str:
        """Kicks off a run and returns immediately — the UI polls `state`.

        Returns "busy" when another run (or the background pass) is already in flight: starting now
        would silently hijack it.
        """
        if self._state.is_running or self._watch_running:
            return "busy"

        async with session_scope() as session:
            queue = await self._build_queue(session, set_nums, only_missing)

        if not queue:
            self._state.last_completed_at = datetime.now(UTC)
            return "empty"

        self._cancel_requested = False
        self._state = BatchState(
            is_running=True,
            done=0,
            total=len(queue),
            mode="selection" if set_nums else ("missing" if only_missing else "full"),
            last_completed_at=self._state.last_completed_at,
            queue=queue,
        )
        self._task = asyncio.create_task(self._run())
        return "started"

    async def _build_queue(
        self, session, set_nums: list[str] | None, only_missing: bool
    ) -> list[str]:
        # A paused queue is resumed rather than rebuilt, so cancelling mid-collection and coming
        # back doesn't re-scrape everything already done.
        if self._state.queue and not set_nums and not only_missing:
            return list(self._state.queue)

        if set_nums:
            return list(dict.fromkeys(set_nums))

        owned = await collection_repo.owned_sets(session)
        if not only_missing:
            return [row.set_num for row in owned]

        quotes_by_set = await collection_repo.all_cached_prices(session)
        conditions = await collection_repo.condition_by_list_id(session)
        pending: list[str] = []
        for row in owned:
            # "Missing" means unpriced *and* never fully processed: a set that came back empty after
            # every source was asked is definitively unfindable, and re-offering it forever is the
            # loop #194 had to break.
            if row.prices_fetched_at is not None:
                continue
            condition = conditions.get(row.current_list_id) if row.current_list_id else None
            price = resolve_collection_price(
                row.store_price_eur,
                condition,
                StoreAvailability.from_raw(row.store_availability),
                quotes_by_set.get(row.set_num, []),
            )
            if price is None:
                pending.append(row.set_num)
        return pending

    def cancel_preserving_progress(self) -> None:
        """Stops after the set in flight. The remaining queue survives so the next start resumes."""
        self._cancel_requested = True

    async def _run(self) -> None:
        try:
            while self._state.queue and not self._cancel_requested:
                set_num = self._state.queue[0]
                self._state.current_set_num = set_num
                try:
                    async with session_scope() as session:
                        cached = await collection_repo.cached_set(session, set_num)
                        lego_set = (
                            collection_repo.to_lego_set(cached)
                            if cached
                            else LegoSet(
                                set_num=set_num,
                                name=set_num,
                                year=0,
                                theme_id=0,
                                num_parts=0,
                                set_img_url=None,
                                set_url=None,
                            )
                        )
                        await prices.refresh_set_prices(session, lego_set, reconcile=False)
                except Exception:  # noqa: BLE001 - one set failing must not end the batch
                    logger.warning("Échec du rafraîchissement de %s", set_num, exc_info=True)

                self._state.queue.pop(0)
                self._state.done += 1

                if self._state.queue and not self._cancel_requested:
                    await asyncio.sleep(settings.scrape_delay_between_sets)
        finally:
            completed = not self._state.queue
            self._state.is_running = False
            self._state.current_set_num = None
            if completed:
                self._state.last_completed_at = datetime.now(UTC)
                await self._finish(self._state.done)

    async def _finish(self, processed: int) -> None:
        async with session_scope() as session:
            await app_settings.set_setting(
                session, "collectionPriceUpdate.lastCompletedAt", datetime.now(UTC).isoformat()
            )
            await _record_collection_value(session)
            await notifications.notify_batch_complete(session, processed)

    # --- Background watch pass -------------------------------------------------------

    async def run_watch_pass(self, limit: int) -> int:
        """Refreshes up to `limit` overdue watched sets. Returns how many were processed.

        No inter-set delay, deliberately: `BrickLinkClient` already spaces its calls by ≥1s, so a
        set costs ≥2s (new + used). The manual batch's delay exists for the browser scrapes and
        doesn't apply here — adding it would pay the same politeness twice.
        """
        if self._watch_running or self._state.is_running:
            return 0

        self._watch_running = True
        processed = 0
        try:
            async with session_scope() as session:
                targets = await collection_repo.price_watch_targets(session)
                now = datetime.now(UTC)
                due = [
                    target
                    for target in targets
                    if (target.due_at.replace(tzinfo=UTC) if target.due_at.tzinfo is None else target.due_at)
                    <= now
                ][:limit]

                for target in due:
                    try:
                        quotes = await prices.fetch_prices(session, target.lego_set, bricklink_only=True)
                        await collection_repo.cache_prices(
                            session, quotes, target.lego_set.set_num, reconcile=False
                        )
                        # No `mark_prices_fetched` here — only BrickLink was asked.
                        await _evaluate(session, target.lego_set.set_num)
                        await collection_repo.reschedule_watch(session, target.lego_set.set_num)
                        processed += 1
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "Passe de surveillance : échec sur %s", target.lego_set.set_num, exc_info=True
                        )

                if processed:
                    await app_settings.set_setting(
                        session, "backgroundRefresh.lastRunAt", datetime.now(UTC).isoformat()
                    )
                    await app_settings.set_setting(session, "backgroundRefresh.lastRunCount", processed)
        finally:
            self._watch_running = False
        return processed


async def _evaluate(session, set_num: str) -> None:
    from . import alerts

    await alerts.evaluate_alerts(session, set_num)


async def _record_collection_value(session) -> None:
    """Records today's collection value from the freshly-written prices. Idempotent, and the
    repository refuses a reading with worse coverage than one already stored for today."""
    owned = await collection_repo.owned_sets(session)
    if not owned:
        return
    quotes_by_set = await collection_repo.all_cached_prices(session)
    conditions = await collection_repo.condition_by_list_id(session)

    total = 0.0
    priced = 0
    units = 0
    for row in owned:
        units += row.quantity
        condition = conditions.get(row.current_list_id) if row.current_list_id else None
        price = resolve_collection_price(
            row.store_price_eur,
            condition,
            StoreAvailability.from_raw(row.store_availability),
            quotes_by_set.get(row.set_num, []),
        )
        if price is not None:
            priced += 1
            total += price * row.quantity

    await collection_repo.record_collection_value_snapshot(
        session,
        total_value_eur=total,
        sets_count=len(owned),
        units_count=units,
        priced_sets_count=priced,
    )


price_updater = PriceUpdater()
