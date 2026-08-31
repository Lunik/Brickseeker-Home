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

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import session_scope
from . import app_settings, collection_repo, notifications, prices
from .pricing import StoreAvailability, resolve_collection_price, source_display_name
from .rebrickable import LegoSet

logger = logging.getLogger(__name__)
_FINALIZATION_TIMEOUT_SECONDS = 30.0


@dataclass(slots=True)
class BatchState:
    is_running: bool = False
    done: int = 0
    total: int = 0
    failed: int = 0
    source_failures: int = 0
    current_set_num: str | None = None
    current_set_started_at: datetime | None = None
    last_progress_at: datetime | None = None
    pending_sources: list[str] = field(default_factory=list)
    captcha_required_sources: list[str] = field(default_factory=list)
    phase: str | None = None
    cancel_requested: bool = False
    mode: str | None = None
    last_completed_at: datetime | None = None
    warning: str | None = None
    error: str | None = None
    #: The remaining queue, kept so a cancel preserves progress and the next start resumes rather
    #: than restarting from zero.
    queue: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "isRunning": self.is_running,
            "done": self.done,
            "total": self.total,
            "failed": self.failed,
            "sourceFailures": self.source_failures,
            "currentSetNum": self.current_set_num,
            "currentSetStartedAt": self.current_set_started_at,
            "lastProgressAt": self.last_progress_at,
            "pendingSources": list(self.pending_sources),
            "captchaRequiredSources": list(self.captcha_required_sources),
            "phase": self.phase,
            "cancelRequested": self.cancel_requested,
            "mode": self.mode,
            "lastCompletedAt": self.last_completed_at,
            "warning": self.warning,
            "error": self.error,
            "hasPendingQueue": bool(self.queue),
        }


class PriceUpdater:
    def __init__(self) -> None:
        self._state = BatchState()
        self._cancel_requested = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._watch_running = False
        self._run_id = 0

    @property
    def _task(self) -> asyncio.Task[None] | None:
        return next(iter(self._tasks), None)

    # --- Manual batch ----------------------------------------------------------------

    @property
    def state(self) -> dict[str, object]:
        return self._state.as_dict()

    @property
    def is_watch_running(self) -> bool:
        return self._watch_running

    async def restore(self, session: AsyncSession) -> None:
        """Reloads the last completion time from storage at startup.

        `BatchState` lives in memory, but the completion time is what Statistiques prints under the
        estimated value — so without this, every restart of the container told the user their prices
        had never been refreshed, whatever the database said.
        """
        if self._state.last_completed_at is not None:
            return
        stored = await app_settings.get_setting(session, "collectionPriceUpdate.lastCompletedAt")
        if not isinstance(stored, str):
            return
        try:
            self._state.last_completed_at = datetime.fromisoformat(stored)
        except ValueError:
            # A hand-edited or pre-format value is not worth failing a boot over.
            logger.warning("Date de dernière actualisation illisible : %r", stored)

    async def start(self, set_nums: list[str] | None = None, *, only_missing: bool = False) -> str:
        """Kicks off a run and returns immediately — the UI polls `state`."""
        resuming = bool(self._state.queue) and not set_nums and not only_missing

        previous_done = self._state.done
        previous_total = self._state.total
        previous_failed = self._state.failed
        previous_source_failures = self._state.source_failures
        previous_captcha_sources = list(self._state.captcha_required_sources)
        previous_mode = self._state.mode
        previous_completed_at = self._state.last_completed_at
        previous_warning = self._state.warning

        self._run_id += 1
        self._cancel_requested = False

        try:
            async with session_scope() as session:
                queue = await self._build_queue(session, set_nums, only_missing)
        except BaseException as error:
            if not self._tasks:
                self._state.is_running = False
                self._state.phase = None
            self._state.error = str(error)
            raise

        if not queue:
            if not self._tasks:
                self._state.is_running = False
                self._state.phase = None
                self._state.last_completed_at = datetime.now(UTC)
                self._state.last_progress_at = self._state.last_completed_at
            return "empty"

        mode = previous_mode if resuming else (
            "selection" if set_nums else ("missing" if only_missing else "full")
        )

        if not self._tasks:
            done = previous_done if resuming else 0
            total = max(previous_total, done + len(queue)) if resuming else len(queue)
            now = datetime.now(UTC)
            self._state = BatchState(
                is_running=True,
                done=done,
                total=total,
                failed=previous_failed if resuming else 0,
                source_failures=previous_source_failures if resuming else 0,
                captcha_required_sources=previous_captcha_sources if resuming else [],
                phase="fetching",
                mode=mode,
                last_completed_at=previous_completed_at,
                warning=previous_warning if resuming else None,
                last_progress_at=now,
                queue=list(queue),
            )
        else:
            for item in queue:
                if item not in self._state.queue:
                    self._state.queue.append(item)
            self._state.total = self._state.done + len(self._state.queue) + (1 if self._state.current_set_num else 0)
            self._state.is_running = True
            self._state.phase = "fetching"
            self._state.last_progress_at = datetime.now(UTC)

        if self._cancel_requested:
            if not self._tasks:
                self._state.is_running = False
                self._state.phase = None
            return "cancelled"
        if self._tasks:
            # A worker is already draining `self._state.queue`, which the branch above just grew —
            # it will pick up these sets on its own. Spawning a second `_run` here would have two
            # loops popping the same list concurrently: sets scraped twice, others skipped, and the
            # "one set at a time" politeness the manual batch exists for broken in the process.
            return "started"
        task = asyncio.create_task(self._run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
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

    async def cancel_preserving_progress(self) -> None:
        """Cancels the in-flight set now; its queue entry survives so the next start resumes it."""
        if not self._state.is_running and not self._tasks:
            return
        self._cancel_requested = True
        cancelled_run_id = self._run_id
        self._state.cancel_requested = True
        self._state.phase = "cancelling"
        self._state.last_progress_at = datetime.now(UTC)

        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        if self._run_id == cancelled_run_id:
            self._state.is_running = False
            self._state.current_set_num = None
            self._state.current_set_started_at = None
            self._state.pending_sources.clear()
            self._state.phase = None
            self._state.cancel_requested = False
            self._state.last_progress_at = datetime.now(UTC)
            self._cancel_requested = False

    async def shutdown(self) -> None:
        await self.cancel_preserving_progress()

    async def _run(self) -> None:
        current_task = asyncio.current_task()
        completed = False
        try:
            while self._state.queue and not self._cancel_requested:
                set_num = self._state.queue[0]
                self._state.current_set_num = set_num
                self._state.current_set_started_at = datetime.now(UTC)
                self._state.last_progress_at = self._state.current_set_started_at
                self._state.pending_sources.clear()
                self._state.phase = "fetching"
                logger.info(
                    "Actualisation des prix de %s (%s/%s)",
                    set_num,
                    self._state.done + 1,
                    self._state.total,
                )
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
                        await prices.refresh_set_prices(
                            session,
                            lego_set,
                            reconcile=False,
                            on_progress=self._on_source_progress,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 - one set failing must not end the batch
                    self._state.failed += 1
                    self._state.warning = f"{set_num} n'a pas pu être actualisé : {error}"
                    logger.warning("Échec du rafraîchissement de %s", set_num, exc_info=True)

                self._state.queue.pop(0)
                self._state.done += 1
                self._state.current_set_num = None
                self._state.current_set_started_at = None
                self._state.pending_sources.clear()
                self._state.last_progress_at = datetime.now(UTC)

                if self._state.queue and not self._cancel_requested:
                    self._state.phase = "waiting"
                    await asyncio.sleep(settings.scrape_delay_between_sets)

            completed = not self._state.queue
            if completed:
                completed_at = datetime.now(UTC)
                self._state.last_completed_at = completed_at
                self._state.last_progress_at = completed_at
                self._state.phase = "finalizing"
                try:
                    async with asyncio.timeout(_FINALIZATION_TIMEOUT_SECONDS):
                        await self._finish(self._state.done, completed_at)
                except TimeoutError:
                    self._state.error = (
                        "Les prix sont à jour, mais la finalisation a dépassé 30 s."
                    )
                    logger.warning("Finalisation du lot abandonnée après 30 s")
                except Exception as error:  # noqa: BLE001 - fetched prices must remain usable
                    self._state.error = f"Prix à jour, finalisation incomplète : {error}"
                    logger.warning("Finalisation du lot de prix échouée", exc_info=True)
        except asyncio.CancelledError:
            logger.info("Actualisation des prix interrompue, progression conservée")
            raise
        except Exception as error:  # noqa: BLE001 - never leave the public state stuck on running
            self._state.error = f"Lot interrompu : {error}"
            logger.exception("Le lot de prix s'est arrêté de façon inattendue")
        finally:
            if not self._tasks or len(self._tasks) <= 1:
                self._state.is_running = False
                self._state.current_set_num = None
                self._state.current_set_started_at = None
                self._state.pending_sources.clear()
                self._state.phase = None
                self._state.cancel_requested = False
                self._state.last_progress_at = datetime.now(UTC)
                self._cancel_requested = False

    def _on_source_progress(self, source: str, status: prices.SourceProgressStatus) -> None:
        self._state.last_progress_at = datetime.now(UTC)
        if status == "started":
            if source not in self._state.pending_sources:
                self._state.pending_sources.append(source)
            return

        if source in self._state.pending_sources:
            self._state.pending_sources.remove(source)
        if status == "captcha_required":
            if source not in self._state.captcha_required_sources:
                self._state.captcha_required_sources.append(source)
            label = "BrickLink" if source == "bricklink" else source_display_name(source)
            self._state.warning = (
                f"{label} demande un CAPTCHA ; actualisez ce set manuellement pour le résoudre."
            )
            return
        if status not in ("failed", "timed_out"):
            return

        self._state.source_failures += 1
        label = "BrickLink" if source == "bricklink" else source_display_name(source)
        reason = "a dépassé son délai" if status == "timed_out" else "a échoué"
        self._state.warning = f"{label} {reason} ; le lot continue."

    async def _finish(self, processed: int, completed_at: datetime) -> None:
        async with session_scope() as session:
            await app_settings.set_setting(
                session, "collectionPriceUpdate.lastCompletedAt", completed_at.isoformat()
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
        if self._watch_running:
            return 0

        async with session_scope() as session:
            # The Réglages switch is a real kill switch, not a stored preference nobody reads: the
            # env var decides whether the job is scheduled at all, this decides whether a granted
            # tick does any work.
            if not await app_settings.get_setting(session, "backgroundRefresh.enabled"):
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
