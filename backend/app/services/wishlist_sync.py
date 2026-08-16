"""Reconciling the local cache against Brickset's wanted list, and the mass CSV import."""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import ApiError
from . import brickset, collection_repo
from .brickset import WishlistImportOutcome
from .rebrickable import client_for as rebrickable_client_for

logger = logging.getLogger(__name__)


async def apply(session: AsyncSession, wanted_set_nums: list[str]) -> int:
    """Reconciles `is_in_wishlist` on every cached row, then creates a row for each wanted set that
    has none.

    The second half is not optional: most wishlisted sets are neither owned nor previously scanned,
    so without it the common case silently vanishes from the count and the Liste cadeaux screen
    despite Brickset reporting it correctly.
    """
    wanted = set(wanted_set_nums)
    await collection_repo.sync_wishlist(session, wanted)

    cached = await collection_repo.cached_set_nums(session)
    missing = [set_num for set_num in wanted_set_nums if set_num not in cached]
    if not missing:
        return 0

    client = await rebrickable_client_for(session)
    enriched = 0
    for set_num in missing:
        try:
            lego_set = await client.fetch_set(set_num)
        except ApiError:
            # A set Rebrickable doesn't have is not worth failing the whole sync over — the
            # wishlist flag is already reconciled, only the catalogue detail is missing.
            continue
        await collection_repo.cache_wishlist_set(session, lego_set)
        enriched += 1
    return enriched


@dataclass(slots=True)
class ImportProgress:
    total: int = 0
    processed: int = 0
    added: int = 0
    already_wanted: int = 0
    not_found: int = 0
    failed: int = 0
    is_running: bool = False
    error: str | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "processed": self.processed,
            "added": self.added,
            "alreadyWanted": self.already_wanted,
            "notFound": self.not_found,
            "failed": self.failed,
            "isRunning": self.is_running,
            "error": self.error,
            "errors": self.errors[:20],
        }


#: Module-level so the UI can poll a running import after the upload request returned.
progress = ImportProgress()


def parse_set_numbers(csv_bytes: bytes) -> list[str]:
    """Reads the set numbers out of a Rebrickable custom-list CSV export.

    Rebrickable's exports vary (column order and header wording have both changed), so the column
    is found by name where a header exists and falls back to the first column otherwise. A bare
    "10307" is normalised to "10307-1": the export drops the variant suffix, while everything else
    in this app keys on the full number.
    """
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("latin-1", errors="replace")

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    column = 0
    body = rows
    if any("set" in cell and ("num" in cell or "number" in cell or cell == "set") for cell in header):
        column = next(
            index
            for index, cell in enumerate(header)
            if "set" in cell and ("num" in cell or "number" in cell or cell == "set")
        )
        body = rows[1:]

    set_nums: list[str] = []
    seen: set[str] = set()
    for row in body:
        if len(row) <= column:
            continue
        raw = row[column].strip()
        if not raw or raw.lower().startswith("set"):
            continue
        normalised = raw if "-" in raw else f"{raw}-1"
        if normalised not in seen:
            seen.add(normalised)
            set_nums.append(normalised)
    return set_nums


async def import_csv(
    session: AsyncSession,
    csv_bytes: bytes,
    on_progress: Callable[[ImportProgress], None] | None = None,
) -> dict[str, object]:
    """Adds every set in the CSV to the Brickset wishlist, one lookup-and-add per set.

    A per-set failure is counted and the batch continues: an import of 150 sets must not be lost
    because Brickset doesn't catalogue one polybag.
    """
    global progress
    set_nums = parse_set_numbers(csv_bytes)
    progress = ImportProgress(total=len(set_nums), is_running=True)

    if not set_nums:
        progress.is_running = False
        progress.error = "Aucun numéro de set trouvé dans ce fichier."
        return progress.as_dict()

    client = await brickset.client_for(session)
    for set_num in set_nums:
        try:
            outcome = await client.add_to_wishlist_if_needed(set_num)
        except ApiError as error:
            progress.failed += 1
            progress.errors.append(f"{set_num} : {error.detail}")
        except Exception as error:  # noqa: BLE001 - one bad set must not abort the batch
            progress.failed += 1
            progress.errors.append(f"{set_num} : {error}")
            logger.warning("Import wishlist — échec inattendu sur %s", set_num, exc_info=True)
        else:
            match outcome:
                case WishlistImportOutcome.ADDED:
                    progress.added += 1
                case WishlistImportOutcome.ALREADY_WANTED:
                    progress.already_wanted += 1
                case WishlistImportOutcome.NOT_FOUND_ON_BRICKSET:
                    progress.not_found += 1
        progress.processed += 1
        if on_progress:
            on_progress(progress)

    # Reflect what was just written into the local cache, so the Liste cadeaux screen shows the
    # imported sets without waiting for the next full sync.
    try:
        wanted = await client.fetch_wishlist_set_numbers()
        await apply(session, wanted)
    except ApiError:
        logger.info("Import terminé mais la resynchronisation immédiate a échoué", exc_info=True)

    progress.is_running = False
    return progress.as_dict()
