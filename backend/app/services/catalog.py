"""The offline catalogue — Rebrickable's public CSV dumps, downloaded on demand into SQLite.

Ports `OfflineCatalogStore`, `OfflineMinifigCatalogStore`, `ThemeNameStore` and `NonSetFilter`.
Four things about it are load-bearing:

* **The dumps are not the v3 API.** `cdn.rebrickable.com/media/downloads/` is public and
  unauthenticated, so these downloads deliberately carry no API key and skip
  `rebrickable_throttler` — throttling a static CDN would only slow the one call a user is
  watching a progress bar for, while stealing budget from the real API.
* **`first_seen_at` is written on INSERT and never refreshed.** It is this install's honest
  "appeared in my catalogue on this date" signal, which is what *Nouveaux sets* sorts on;
  Rebrickable itself publishes no such field. The rule lives in `_SETS_UPSERT`'s `set_` clause:
  the column simply isn't in it.
* **Non-set identification is structural.** Four named theme sub-trees walked through
  `parent_id`, never a list of ids — see `_NON_SET_SUBTREES`.
* **The download is a background task**, so a failure has no request to be raised into. Every
  entry point mirrors its progress *and its errors* into `CatalogState.status` as a small JSON
  document — `{"state": "running"|"error", "progress": 0..1, "message": "…"}` — which is what
  `GET /catalog/status` polls. `status` is `NULL` when nothing is in flight.

Unlike the iOS port there is no gzip container hand-parsing and no ISIZE alignment care: Python's
`gzip` reads the container natively. The CSV tolerance *is* still needed — the dumps really are
CRLF-terminated with RFC 4180 quoting, and the iOS port once lost every line break to a naive
split and parsed zero rows without erroring.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import zlib
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Table, delete, func, select
from sqlalchemy.dialects.sqlite import Insert as SqliteInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..deps import ApiError, network_unavailable
from ..models import (
    CatalogMinifig,
    CatalogMinifigSet,
    CatalogSet,
    CatalogState,
    CatalogTheme,
    utcnow,
)
from .rebrickable import LegoSet

logger = logging.getLogger(__name__)

CDN_BASE = "https://cdn.rebrickable.com/media/downloads"

#: Which dump files each downloadable catalogue owns — also what `purge_catalog` sweeps off disk.
_DUMP_FILES: dict[str, tuple[str, ...]] = {
    "sets": ("sets.csv.gz",),
    "themes": ("themes.csv.gz",),
    "minifigs": (
        "minifigs.csv.gz",
        "inventories.csv.gz",
        "inventory_minifigs.csv.gz",
        "inventory_sets.csv.gz",
    ),
}
_CATALOGS: tuple[str, ...] = tuple(_DUMP_FILES)

#: Generous read window: the CDN is fast but a phone tethering in a shop is not, and a download
#: that dies at 80 % costs the whole file (there is no resume here, unlike the iOS version).
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
#: Rows per executemany. Big enough that ~28k sets is a couple of dozen round trips, small enough
#: that a progress tick still happens often enough to look alive.
_DB_CHUNK_ROWS = 1000

#: Mirrors `ThemeNameStore.staleAfter`. The table is ~700 rows of ~5 KB and LEGO adds a handful of
#: themes a year, so this one refreshes itself instead of waiting for an explicit user action.
_THEMES_STALE_AFTER = timedelta(days=30)

#: Cycle guard for the sub-set containment walk. Real data is a shallow DAG (box → bag), never
#: circular; this only stops a corrupt dump from recursing forever.
_MAX_NESTING_DEPTH = 10

#: `(kind, theme name, roots only)` — the whole non-set filter, as four names.
#:
#: Roots-only is the stricter rule and the default: a nested theme can share a name with an
#: unrelated branch, and "Gears" (a Universal Building Set sub-theme, about actual cogs) must never
#: resolve to the "Gear" merchandise root. "Database Sets" can't use it because it legitimately
#: sits under "Other"; its name is distinctive enough to match at any depth.
#:
#: Two other shapes of signal were measured against the real dumps and rejected — don't reintroduce
#: either: `num_parts == 0` (541 of the 1 440 Books entries *do* ship parts, and legitimate sets
#: ship none), and "a non-numeric set number is never a real product" (2 554 entries match,
#: including 80 Star Wars ones; `AUTOSHOW-1` is a genuine 28-part promo set).
_NON_SET_SUBTREES: tuple[tuple[str, str, bool], ...] = (
    ("catalogArtifact", "Database Sets", False),
    ("merchandise", "Gear", True),
    ("book", "Books", True),
    ("exclusive", "LEGO Exclusive", True),
)


# --------------------------------------------------------------------------------------
# gzip / CSV
# --------------------------------------------------------------------------------------


def gunzip(data: bytes) -> bytes:
    """Inflate a dump held in memory.

    The download path streams straight off disk instead (see `_Dump`); this is the in-memory
    equivalent for callers that already hold the bytes. Its only real job beyond `gzip.decompress`
    is turning a truncated body or an HTML error page into a message the UI can show.
    """
    try:
        return gzip.decompress(data)
    except (OSError, EOFError, zlib.error) as exc:
        raise ApiError("Fichier catalogue illisible (archive corrompue)") from exc


def parse_csv(data: bytes) -> Iterator[list[str]]:
    """Records of an uncompressed dump, header row dropped.

    `csv.reader` over a stream opened with `newline=""` is what makes this tolerant of the dumps'
    real shape — CRLF endings, a `,` inside a quoted set name, a `"` escaped as `""` — without the
    line-splitting-then-field-splitting the iOS port had to hand-roll.
    """
    stream = io.StringIO(data.decode("utf-8-sig", errors="replace"), newline="")
    reader = csv.reader(stream)
    next(reader, None)  # header
    return (row for row in reader if row)


class _Dump:
    """A gzipped dump opened for streaming, read as `column name → value`.

    Header-driven rather than positional: Rebrickable has added columns to these dumps before, and
    a positional parser turns that into silently wrong data rather than an error.

    `fraction` is measured on the *compressed* file — the uncompressed size isn't known until the
    last byte is read. It runs slightly ahead of the rows actually yielded because `GzipFile` reads
    the raw file in blocks, which is the right direction for a progress bar to be wrong in.
    """

    def __init__(self, path: Path) -> None:
        self._size = max(path.stat().st_size, 1)
        self._raw = path.open("rb")
        self._gz = gzip.GzipFile(fileobj=self._raw)
        self._text = io.TextIOWrapper(self._gz, encoding="utf-8-sig", errors="replace", newline="")
        self._reader = csv.DictReader(self._text)

    def __enter__(self) -> _Dump:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def columns(self) -> list[str]:
        return self._reader.fieldnames or []

    @property
    def fraction(self) -> float:
        return min(self._raw.tell() / self._size, 1.0)

    def rows(self) -> Iterator[dict[str, str | Any]]:
        yield from self._reader

    def close(self) -> None:
        self._text.close()
        self._raw.close()


def _open_dump(path: Path, filename: str, required: Sequence[str]) -> _Dump:
    """Opens a dump and refuses one whose header isn't the file we asked for — the CDN serving an
    error page shouldn't import as an empty catalogue."""
    try:
        dump = _Dump(path)
        missing = [column for column in required if column not in dump.columns]
    except (OSError, EOFError, zlib.error) as exc:
        raise ApiError(f"Fichier catalogue illisible ({filename})") from exc
    if missing:
        dump.close()
        raise ApiError(f"Format inattendu pour {filename} (colonnes manquantes : {', '.join(missing)})")
    return dump


def _int(raw: str | None, default: int = 0) -> int:
    try:
        return int((raw or "").strip())
    except ValueError:
        return default


def _utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything compared against them here is UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# --------------------------------------------------------------------------------------
# CatalogState: progress, completion, failure
# --------------------------------------------------------------------------------------


async def _state_row(session: AsyncSession, name: str) -> CatalogState:
    row = await session.get(CatalogState, name)
    if row is None:
        row = CatalogState(name=name, row_count=0)
        session.add(row)
    return row


class _Progress:
    """Fans one 0..1 fraction out to the caller's callback and to `CatalogState.status`.

    The status row is the only channel a background download has: the request that started it
    returned long ago, so an error written here is the difference between a visible failure and a
    progress bar that stops at 63 % forever.

    Reports are throttled to whole percentage points. `httpx` yields chunks hundreds of times a
    second on a fast connection and every one of them would otherwise be a SQLite commit — the same
    flood the iOS delegate's `lastReportedFraction` guard exists to stop.
    """

    def __init__(
        self, session: AsyncSession, name: str, callback: Callable[[float], None] | None
    ) -> None:
        self._session = session
        self._name = name
        self._callback = callback
        self._last = -1.0
        self._message = ""

    async def report(self, fraction: float, message: str) -> None:
        value = min(max(fraction, 0.0), 1.0)
        if value - self._last < 0.01 and value < 1.0 and message == self._message:
            return
        self._last = value
        self._message = message
        if self._callback is not None:
            self._callback(value)
        await self._write({"state": "running", "progress": round(value, 3), "message": message})

    async def done(self, downloaded_at: datetime, row_count: int) -> None:
        if self._callback is not None:
            self._callback(1.0)
        row = await _state_row(self._session, self._name)
        row.downloaded_at = downloaded_at
        row.row_count = row_count
        row.status = None
        await self._session.commit()

    async def failed(self, error: BaseException) -> None:
        # The failure may have left the session mid-transaction; the status write is the one thing
        # that still has to land.
        await self._session.rollback()
        detail = error.detail if isinstance(error, ApiError) else str(error) or type(error).__name__
        await self._write({"state": "error", "message": str(detail)[:300]})

    async def _write(self, payload: dict[str, Any]) -> None:
        row = await _state_row(self._session, self._name)
        row.status = json.dumps(payload, ensure_ascii=False)
        await self._session.commit()


async def _fetch_dump(
    filename: str,
    dest: Path,
    reporter: _Progress,
    span: tuple[float, float],
    message: str,
) -> None:
    """Streams one dump to `dest`, reporting bytes across `span` of the overall bar.

    Written to a sibling `.part` and renamed on success, so a half-downloaded file is never handed
    to the parser.
    """
    settings.ensure_dirs()
    part = dest.with_name(dest.name + ".part")
    start, end = span
    try:
        async with (
            httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client,
            client.stream("GET", f"{CDN_BASE}/{filename}") as response,
        ):
            response.raise_for_status()
            total = _int(response.headers.get("content-length"))
            written = 0
            with part.open("wb") as handle:
                async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK_BYTES):
                    handle.write(chunk)
                    written += len(chunk)
                    if total > 0:
                        await reporter.report(start + (end - start) * (written / total), message)
        part.replace(dest)
    except httpx.HTTPStatusError as exc:
        part.unlink(missing_ok=True)
        raise ApiError(f"Catalogue indisponible ({exc.response.status_code})", 502) from exc
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise network_unavailable() from exc


def _upsert(table: Table, keys: Sequence[str], updated: Sequence[str]) -> SqliteInsert:
    stmt = sqlite_insert(table)
    return stmt.on_conflict_do_update(
        index_elements=list(keys),
        set_={column: getattr(stmt.excluded, column) for column in updated},
    )


#: `first_seen_at` is absent from the updated columns *on purpose* — that omission is the entire
#: "stamped on insert, never refreshed" rule the Nouveaux sets ordering rests on.
_SETS_UPSERT = _upsert(
    CatalogSet.__table__, ["set_num"], ["name", "year", "theme_id", "num_parts", "set_img_url"]
)
_THEMES_UPSERT = _upsert(CatalogTheme.__table__, ["theme_id"], ["name", "parent_id"])


async def _insert_chunks(session: AsyncSession, statement: Any, rows: Sequence[dict[str, Any]]) -> None:
    for start in range(0, len(rows), _DB_CHUNK_ROWS):
        await session.execute(statement, list(rows[start : start + _DB_CHUNK_ROWS]))


async def _count(session: AsyncSession, model: type[Any]) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


# --------------------------------------------------------------------------------------
# sets.csv
# --------------------------------------------------------------------------------------


async def download_sets_catalog(
    session: AsyncSession, progress: Callable[[float], None] | None = None
) -> int:
    """Downloads `sets.csv.gz` and merges it into `CatalogSet`. Returns the table's row count."""
    reporter = _Progress(session, "sets", progress)
    dest = settings.catalog_dir / "sets.csv.gz"
    try:
        await reporter.report(0.0, "Téléchargement du catalogue…")
        # One ~5 KB GET, and without it the non-set filter resolves nothing and the Réglages
        # toggle does visibly nothing. Best-effort: the sets dump is what the user asked for.
        try:
            await download_themes(session)
        except Exception:
            logger.warning("Thèmes non rafraîchis pendant le téléchargement du catalogue", exc_info=True)
        await _fetch_dump("sets.csv.gz", dest, reporter, (0.0, 0.9), "Téléchargement du catalogue…")
        count = await _import_sets(session, dest, reporter)
    except BaseException as exc:
        await reporter.failed(exc)
        raise
    finally:
        dest.unlink(missing_ok=True)
    return count


async def _import_sets(session: AsyncSession, path: Path, reporter: _Progress) -> int:
    # One instant shared by every row this download inserts, so the first-ever download stamps the
    # whole catalogue identically — `catalog_status`'s `initialSyncAt` is `MIN(first_seen_at)`, and
    # that equality is what lets Nouveaux sets exclude the initial ~28k-set import instead of
    # flooding the screen with it on day one.
    now = utcnow()
    seen: set[str] = set()
    chunk: list[dict[str, Any]] = []

    with _open_dump(path, "sets.csv", ("set_num", "name")) as dump:
        for row in dump.rows():
            set_num = (row.get("set_num") or "").strip()
            # First occurrence wins on a duplicate set_num, matching sync_collection's dedup rule.
            if not set_num or set_num in seen:
                continue
            seen.add(set_num)
            image = (row.get("img_url") or "").strip()
            chunk.append(
                {
                    "set_num": set_num,
                    "name": row.get("name") or "",
                    "year": _int(row.get("year")),
                    "theme_id": _int(row.get("theme_id")),
                    "num_parts": _int(row.get("num_parts")),
                    "set_img_url": image or None,
                    "first_seen_at": now,
                }
            )
            if len(chunk) >= _DB_CHUNK_ROWS:
                await session.execute(_SETS_UPSERT, chunk)
                await session.commit()
                chunk = []
                await reporter.report(0.9 + 0.1 * dump.fraction, "Import du catalogue…")

    if chunk:
        await session.execute(_SETS_UPSERT, chunk)
    await session.commit()

    # Sets that vanished from the dump are deliberately kept: an offline lookup that still answers
    # beats one that doesn't, and a truncated download must never be able to empty the catalogue.
    count = await _count(session, CatalogSet)
    await reporter.done(now, count)
    return count


# --------------------------------------------------------------------------------------
# themes.csv
# --------------------------------------------------------------------------------------


async def download_themes(session: AsyncSession, force: bool = False) -> int:
    """Refreshes the theme table when it's missing or older than 30 days; a no-op otherwise.

    Unlike the sets/minifigs catalogues this one isn't a deliberate user action — it's tiny, it
    barely changes, and every theme name and non-set verdict in the app depends on it — so callers
    may invoke it unconditionally.
    """
    state = await session.get(CatalogState, "themes")
    if (
        not force
        and state is not None
        and state.row_count > 0
        and state.downloaded_at is not None
        and utcnow() - _utc(state.downloaded_at) < _THEMES_STALE_AFTER
    ):
        return state.row_count

    reporter = _Progress(session, "themes", None)
    dest = settings.catalog_dir / "themes.csv.gz"
    try:
        await reporter.report(0.0, "Téléchargement des thèmes…")
        await _fetch_dump("themes.csv.gz", dest, reporter, (0.0, 0.9), "Téléchargement des thèmes…")
        count = await _import_themes(session, dest, reporter)
    except BaseException as exc:
        await reporter.failed(exc)
        raise
    finally:
        dest.unlink(missing_ok=True)
    return count


async def _import_themes(session: AsyncSession, path: Path, reporter: _Progress) -> int:
    rows: list[dict[str, Any]] = []
    with _open_dump(path, "themes.csv", ("id", "name")) as dump:
        for row in dump.rows():
            theme_id = _int(row.get("id"), -1)
            if theme_id < 0:
                continue
            parent = (row.get("parent_id") or "").strip()
            rows.append(
                {
                    "theme_id": theme_id,
                    "name": row.get("name") or "",
                    # Absent for the ~150 top-level themes; "no parent" is how a root is
                    # recognised, so an unparseable value must stay NULL rather than become 0.
                    "parent_id": int(parent) if parent.isdigit() else None,
                }
            )
    if not rows:
        raise ApiError("Table des thèmes vide — l'ancienne est conservée")

    now = utcnow()
    await _insert_chunks(session, _THEMES_UPSERT, rows)
    await session.commit()
    count = await _count(session, CatalogTheme)
    await reporter.done(now, count)
    _invalidate_themes()
    return count


# --------------------------------------------------------------------------------------
# minifigs.csv + the inventory join
# --------------------------------------------------------------------------------------


async def download_minifigs_catalog(
    session: AsyncSession, progress: Callable[[float], None] | None = None
) -> int:
    """Downloads the four minifig dumps and rebuilds `CatalogMinifig`/`CatalogMinifigSet`.

    Not incremental, unlike the sets catalogue: there is no `first_seen_at` to preserve here, and a
    wholesale replace is the only way a minifig that lost a containing set upstream loses it here.
    """
    reporter = _Progress(session, "minifigs", progress)
    paths = {name: settings.catalog_dir / name for name in _DUMP_FILES["minifigs"]}
    try:
        state = await session.get(CatalogState, "sets")
        if state is None or state.downloaded_at is None:
            # A minifig has no year or theme of its own — both are read off a containing set, so
            # the sets catalogue is a prerequisite, not an optional extra.
            await reporter.report(0.0, "Téléchargement du catalogue des sets…")
            await download_sets_catalog(session, _scaled(progress, 0.0, 0.4))
        await reporter.report(0.4, "Téléchargement des minifigs…")

        spans = ((0.40, 0.55), (0.55, 0.70), (0.70, 0.85), (0.85, 0.90))
        for filename, span in zip(_DUMP_FILES["minifigs"], spans, strict=True):
            await _fetch_dump(filename, paths[filename], reporter, span, "Téléchargement des minifigs…")

        await reporter.report(0.9, "Association des minifigs aux sets…")
        minifigs, pivots = await _join_minifigs(session, paths)
        count = await _persist_minifigs(session, minifigs, pivots, reporter)
    except BaseException as exc:
        await reporter.failed(exc)
        raise
    finally:
        for path in paths.values():
            path.unlink(missing_ok=True)
    return count


def _scaled(
    callback: Callable[[float], None] | None, start: float, end: float
) -> Callable[[float], None] | None:
    if callback is None:
        return None
    return lambda fraction: callback(start + (end - start) * fraction)


async def _join_minifigs(
    session: AsyncSession, paths: dict[str, Path]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Joins the four dumps into minifig rows plus their (minifig, set, quantity) pivot rows.

    `inventory_sets.csv` is what makes a CMF box work: `71051-13` lists no minifig of its own, only
    12 sub-sets `71051-1`…`71051-12` that each contain one. Without walking that nesting, owning
    the box never counted as owning anything inside it.
    """
    # inventories.csv: id,version,set_num — any version will do, since whether a minifig appears in
    # a set doesn't depend on which parts-list revision is referenced.
    set_num_by_inventory: dict[str, str] = {}
    with _open_dump(paths["inventories.csv.gz"], "inventories.csv", ("id", "set_num")) as dump:
        for row in dump.rows():
            set_num_by_inventory[row.get("id") or ""] = row.get("set_num") or ""

    # inventory_sets.csv: child set_num → its immediate parents and how many copies of the child
    # one parent holds.
    parents_by_child: dict[str, list[tuple[str, int]]] = {}
    with _open_dump(
        paths["inventory_sets.csv.gz"], "inventory_sets.csv", ("inventory_id", "set_num")
    ) as dump:
        for row in dump.rows():
            parent = set_num_by_inventory.get(row.get("inventory_id") or "")
            child = row.get("set_num") or ""
            if not parent or not child:
                continue
            parents_by_child.setdefault(child, []).append((parent, _int(row.get("quantity"), 1)))

    # Every ancestor of a set with the quantity one copy of that set implies of each — memoized,
    # since every bag in a CMF box shares the same chain.
    ancestor_cache: dict[str, list[tuple[str, int]]] = {}

    def ancestors(set_num: str, depth: int = 0) -> list[tuple[str, int]]:
        cached = ancestor_cache.get(set_num)
        if cached is not None:
            return cached
        parents = parents_by_child.get(set_num)
        if not parents or depth >= _MAX_NESTING_DEPTH:
            return []
        walked: list[tuple[str, int]] = []
        for parent_num, parent_quantity in parents:
            walked.append((parent_num, parent_quantity))
            walked.extend(
                (grandparent, parent_quantity * quantity)
                for grandparent, quantity in ancestors(parent_num, depth + 1)
            )
        ancestor_cache[set_num] = walked
        return walked

    # inventory_minifigs.csv: fig_num → containing sets, file order preserved (the set holding the
    # minifig directly, then its ancestors), deduped by (fig_num, set_num).
    containing: dict[str, list[tuple[str, int]]] = {}
    seen: set[tuple[str, str]] = set()
    with _open_dump(
        paths["inventory_minifigs.csv.gz"], "inventory_minifigs.csv", ("inventory_id", "fig_num")
    ) as dump:
        for row in dump.rows():
            set_num = set_num_by_inventory.get(row.get("inventory_id") or "")
            fig_num = row.get("fig_num") or ""
            if not set_num or not fig_num:
                continue
            quantity = _int(row.get("quantity"), 1)
            candidates = [(set_num, quantity)]
            candidates.extend(
                (ancestor, quantity * multiplier) for ancestor, multiplier in ancestors(set_num)
            )
            for candidate_num, candidate_quantity in candidates:
                if (fig_num, candidate_num) in seen:
                    continue
                seen.add((fig_num, candidate_num))
                containing.setdefault(fig_num, []).append((candidate_num, candidate_quantity))

    facts = await _set_facts(session)
    minifigs: list[dict[str, Any]] = []
    pivots: list[dict[str, Any]] = []
    with _open_dump(paths["minifigs.csv.gz"], "minifigs.csv", ("fig_num", "name")) as dump:
        for row in dump.rows():
            fig_num = (row.get("fig_num") or "").strip()
            if not fig_num:
                continue
            sets = containing.get(fig_num, [])
            # The first containing set wins outright — no attempt to pick a "representative" one.
            year, theme_id = facts.get(sets[0][0], (None, None)) if sets else (None, None)
            image = (row.get("img_url") or "").strip()
            minifigs.append(
                {
                    "fig_num": fig_num,
                    "name": row.get("name") or "",
                    "num_parts": _int(row.get("num_parts")),
                    "img_url": image or None,
                    "theme_id": theme_id,
                    "year": year,
                }
            )
            # Built here rather than from `containing` directly: a pivot row for a fig_num absent
            # from minifigs.csv would violate the foreign key.
            pivots.extend(
                {
                    "fig_num": fig_num,
                    "set_num": set_num,
                    "quantity_per_set": quantity,
                    "position": position,
                }
                for position, (set_num, quantity) in enumerate(sets)
            )
    return minifigs, pivots


async def _set_facts(session: AsyncSession) -> dict[str, tuple[int | None, int | None]]:
    """`set_num → (year, theme_id)` for the whole local catalogue — one query instead of ~15k."""
    rows = await session.execute(select(CatalogSet.set_num, CatalogSet.year, CatalogSet.theme_id))
    return {set_num: (year, theme_id) for set_num, year, theme_id in rows.all()}


async def _persist_minifigs(
    session: AsyncSession,
    minifigs: Sequence[dict[str, Any]],
    pivots: Sequence[dict[str, Any]],
    reporter: _Progress,
) -> int:
    now = utcnow()
    # Replace and insert in one transaction: the gallery is read straight off these tables and
    # must never observe them half-empty.
    await session.execute(delete(CatalogMinifigSet))
    await session.execute(delete(CatalogMinifig))
    await _insert_chunks(session, sqlite_insert(CatalogMinifig.__table__), minifigs)
    await _insert_chunks(session, sqlite_insert(CatalogMinifigSet.__table__), pivots)
    await session.commit()
    count = await _count(session, CatalogMinifig)
    await reporter.done(now, count)
    return count


# --------------------------------------------------------------------------------------
# Purge + status
# --------------------------------------------------------------------------------------


async def purge_catalog(session: AsyncSession, name: str) -> None:
    """Drops one downloaded catalogue, reverting to "no offline fallback" until it's fetched again.

    Purging `sets` also drops every `first_seen_at`, which is intended: a purge-then-redownload is
    a genuine fresh start and should re-establish a new baseline rather than treat the next
    download as a "later" sync against a snapshot that no longer exists.
    """
    if name not in _DUMP_FILES:
        raise ApiError(f"Catalogue inconnu : {name}")

    if name == "sets":
        await session.execute(delete(CatalogSet))
    elif name == "themes":
        await session.execute(delete(CatalogTheme))
    else:
        await session.execute(delete(CatalogMinifigSet))
        await session.execute(delete(CatalogMinifig))

    state = await session.get(CatalogState, name)
    if state is not None:
        await session.delete(state)
    await session.commit()

    if name == "themes":
        _invalidate_themes()
    for filename in _DUMP_FILES[name]:
        (settings.catalog_dir / filename).unlink(missing_ok=True)
        (settings.catalog_dir / f"{filename}.part").unlink(missing_ok=True)


async def catalog_status(session: AsyncSession) -> dict[str, Any]:
    """What Réglages reports: one uniform block per catalogue, plus the first-sync baseline.

    `initialSyncAt` is `MIN(first_seen_at)` — every set of the first-ever download shares one
    instant, so a set is genuinely *new* only when its `firstSeenAt` is strictly after this.
    Deriving it beats storing it: a purge resets it for free.
    """
    rows = (await session.execute(select(CatalogState))).scalars().all()
    states = {row.name: row for row in rows}
    payload: dict[str, Any] = {}
    for name in _CATALOGS:
        state = states.get(name)
        payload[name] = {
            "downloadedAt": state.downloaded_at if state else None,
            "rowCount": state.row_count if state else 0,
            "status": _decode_status(state.status if state else None),
        }
    payload["initialSyncAt"] = (
        await session.execute(select(func.min(CatalogSet.first_seen_at)))
    ).scalar_one_or_none()
    return payload


def _decode_status(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"state": "error", "message": raw}


# --------------------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------------------


async def lookup_catalog_set(session: AsyncSession, set_num: str) -> LegoSet | None:
    """The offline fallback for set identification.

    Tries the `-1` variant first, like `resolve_set` does live: most numbers read off a box omit
    the suffix Rebrickable's catalogue actually keys on. Collection status and prices are
    deliberately absent from the snapshot and stay live-only.
    """
    for candidate in (f"{set_num}-1", set_num):
        row = await session.get(CatalogSet, candidate)
        if row is not None:
            return LegoSet(
                set_num=row.set_num,
                name=row.name,
                year=row.year,
                theme_id=row.theme_id,
                num_parts=row.num_parts,
                set_img_url=row.set_img_url,
                set_url=None,
            )
    return None


# --------------------------------------------------------------------------------------
# Theme tree — names, hierarchy, non-set kinds
# --------------------------------------------------------------------------------------


class _ThemeCache:
    """The theme table in memory, plus what's derived from it.

    Every lookup would otherwise scan ~700 rows, and the non-set filter runs once per set on
    screens listing thousands. Keyed by a generation counter bumped on each download/purge —
    an exact key, unlike comparing table sizes.
    """

    __slots__ = ("generation", "kinds", "names", "parents", "roots")

    def __init__(self, generation: int, names: dict[int, str], parents: dict[int, int]) -> None:
        self.generation = generation
        self.names = names
        self.parents = parents
        self.roots: list[tuple[str, int]] = _subtree_roots(names, parents)
        #: theme_id → kind, including `None` for "this is a real set" so a resolved theme is never
        #: walked twice. Bounded by the theme table, not by the catalogue's 28 000 sets.
        self.kinds: dict[int, str | None] = {}


_theme_generation = 0
_theme_cache: _ThemeCache | None = None


def _invalidate_themes() -> None:
    global _theme_generation
    _theme_generation += 1


def _subtree_roots(names: dict[int, str], parents: dict[int, int]) -> list[tuple[str, int]]:
    roots: list[tuple[str, int]] = []
    for kind, theme_name, roots_only in _NON_SET_SUBTREES:
        matches = sorted(
            theme_id
            for theme_id, name in names.items()
            if name == theme_name and not (roots_only and theme_id in parents)
        )
        # Roots-only takes the lowest id; the any-depth rule hides every match rather than guessing
        # which one was meant — a second theme Rebrickable ever names "Database Sets" would be
        # database sets too.
        roots.extend((kind, theme_id) for theme_id in (matches[:1] if roots_only else matches))
    return roots


async def _themes(session: AsyncSession) -> _ThemeCache:
    global _theme_cache
    cached = _theme_cache
    if cached is not None and cached.generation == _theme_generation:
        return cached
    # Read the generation *before* the query: if a download bumps it while we're loading, this
    # snapshot is stamped stale and the next caller reloads.
    generation = _theme_generation
    rows = (await session.execute(select(CatalogTheme))).scalars().all()
    cache = _ThemeCache(
        generation,
        {row.theme_id: row.name for row in rows},
        {row.theme_id: row.parent_id for row in rows if row.parent_id is not None},
    )
    _theme_cache = cache
    return cache


async def theme_name(session: AsyncSession, theme_id: int) -> str:
    """The single definition of the "no table yet" fallback — it used to exist at four call sites."""
    return (await _themes(session)).names.get(theme_id) or f"Thème #{theme_id}"


async def theme_names(session: AsyncSession) -> dict[int, str]:
    return dict((await _themes(session)).names)


async def is_descendant(session: AsyncSession, theme_id: int, ancestor_id: int) -> bool:
    """Whether `theme_id` is `ancestor_id` itself or sits anywhere below it.

    False while the hierarchy isn't loaded — a filter built on this then hides nothing, which is
    the safe direction to fail in. The walk is bounded by the number of known parent links (no
    chain can be longer) so a corrupt dump can't loop forever.
    """
    themes = await _themes(session)
    if theme_id not in themes.names:
        return False
    if theme_id == ancestor_id:
        return True
    current = theme_id
    for _ in range(len(themes.parents)):
        parent = themes.parents.get(current)
        if parent is None:
            return False
        if parent == ancestor_id:
            return True
        current = parent
    return False


async def non_set_kind(session: AsyncSession, theme_id: int) -> str | None:
    """Why this theme isn't a set — `merchandise`, `book`, `exclusive`, `catalogArtifact` — or
    `None` if it is one. Independent of the user's toggle, so a scanned cap can still be badged
    while the filter is off."""
    themes = await _themes(session)
    if theme_id in themes.kinds:
        return themes.kinds[theme_id]
    resolved: str | None = None
    for kind, root_id in themes.roots:
        if await is_descendant(session, theme_id, root_id):
            resolved = kind
            break
    themes.kinds[theme_id] = resolved
    return resolved


async def should_hide(session: AsyncSession, theme_id: int, hide_enabled: bool) -> bool:
    """The predicate the discovery screens filter on.

    Catalogue artifacts go whatever the preference says — they aren't products, so there's no
    reading of the toggle under which someone wants "Database Set for 1307-1" proposed to them.
    Everything else is the user's choice, and nothing at all is hidden until the theme table has
    been downloaded: showing a cap is a nuisance, hiding a real set isn't.
    """
    kind = await non_set_kind(session, theme_id)
    if kind is None:
        return False
    return True if kind == "catalogArtifact" else hide_enabled
