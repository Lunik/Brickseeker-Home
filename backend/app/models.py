"""SQLite schema — a direct port of the iOS app's SwiftData `@Model` classes, plus the tables
that replace iOS-only storage (Keychain → `Credential`, UserDefaults → `AppSetting`, the on-disk
JSON catalogue snapshots → `CatalogSet`/`CatalogTheme`/`CatalogMinifig`).

Two doctrines carried over verbatim from the app, because everything downstream depends on them:

* **Hand-entered data outlives the caches.** `clear_cache()` (Réglages → "vider le cache") wipes
  `CachedSet`/`CachedSetList`/`CachedSetPrice`/`SoldListing`/`CollectionSyncState` only.
  `ScanEvent`, `SetPurchaseRecord`, `PriceAlert`, `PriceHistoryEntry` and
  `CollectionValueSnapshot` survive: a threshold, a paid price or a past day's valuation cannot
  be re-fetched from anywhere.
* **`CachedSet.was_scanned` is why a row exists**, not what it is: `True` for sets the user
  actually scanned (feeds History), `False` for rows that only exist from a collection sync
  (feeds Collection). A set can be both.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------------------
# Catalogue + collection cache
# --------------------------------------------------------------------------------------


class CachedSet(Base):
    """One set the user has scanned, owns, or wishlisted. Port of SwiftData `CachedSet`."""

    __tablename__ = "cached_sets"

    set_num: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), default="")
    year: Mapped[int] = mapped_column(Integer, default=0)
    theme_id: Mapped[int] = mapped_column(Integer, default=0)
    num_parts: Mapped[int] = mapped_column(Integer, default=0)
    set_img_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    last_scanned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    was_scanned: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_in_collection: Mapped[bool] = mapped_column(Boolean, default=False)
    current_list_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_list_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    store_price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    store_availability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    store_price_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Stamped once every source has been tried for this set, price found or not — the "already
    #: looked everywhere" flag that stops "Compléter les prix manquants" looping forever (#194).
    prices_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_in_wishlist: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_cached_sets_collection", "is_in_collection"),
        Index("ix_cached_sets_scanned", "was_scanned"),
        Index("ix_cached_sets_wishlist", "is_in_wishlist"),
    )


class CachedSetList(Base):
    """A Rebrickable Set List, plus the local per-list `condition` annotation that decides which
    price source values the sets inside it (neuf → retail chain, occasion → BrickLink used)."""

    __tablename__ = "cached_set_lists"

    list_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    num_sets: Mapped[int] = mapped_column(Integer, default=0)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    condition: Mapped[str] = mapped_column(String(16), default="newSet")


class CollectionSyncState(Base):
    __tablename__ = "collection_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_wishlist_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------------------
# Scans (append-only history, hand-entered prices)
# --------------------------------------------------------------------------------------


class ScanEvent(Base):
    """One real camera scan. Location fields only ever populated when the user opted in, and
    stripped (never the row) once the set joins the collection — "in which store did I see this
    deal" is moot once it's bought."""

    __tablename__ = "scan_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_num: Mapped[str] = mapped_column(String(64), index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    place_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    #: What the user typed in the "quel prix as-tu vu ?" prompt. Never backfilled from an online
    #: price — this field means "seen with my own eyes", nothing else.
    price_seen_eur: Mapped[float | None] = mapped_column(Float, nullable=True)


class SetPurchaseRecord(Base):
    """What the user actually paid. Deliberately its own table, not a `CachedSet` column: cache
    clears and collection syncs destroy `CachedSet` rows, and a hand-typed price must survive."""

    __tablename__ = "set_purchase_records"

    set_num: Mapped[str] = mapped_column(String(64), primary_key=True)
    paid_price_eur: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------------------


class CachedSetPrice(Base):
    """Latest quote per (set, source), for display. Never expires (#244) — a price stays visible
    until a newer fetch overwrites it in place; `fetched_at` only drives refresh policy and the
    "this is getting old" caption."""

    __tablename__ = "cached_set_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_num: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    min_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    lot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("set_num", "source", name="uq_price_set_source"),)


class SoldListing(Base):
    """One completed BrickLink sale (`price_detail[]`). Written as a wholesale replace per
    (set, source) — BrickLink re-sends its whole 6-month window each refresh, so appending would
    multiply the same sale once per refresh. Pure cache: cleared by `clear_cache()`."""

    __tablename__ = "sold_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_num: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32))
    unit_amount: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    ordered_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PriceHistoryEntry(Base):
    """Append-only, one row per (set, source, day). Survives `clear_cache()` — the price-evolution
    chart is the whole point of recording it, and a past reading can't be re-fetched."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_num: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class CollectionValueSnapshot(Base):
    """One day's reading of what the whole collection is worth. `priced_sets_count` is stored, not
    derived: it's what makes the row trustworthy — a thin-coverage reading understates the
    collection and the chart greys it rather than plotting a crash that never happened."""

    __tablename__ = "collection_value_snapshots"

    day_key: Mapped[str] = mapped_column(String(10), primary_key=True)  # "YYYY-MM-DD"
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    total_value_eur: Mapped[float] = mapped_column(Float)
    sets_count: Mapped[int] = mapped_column(Integer)
    units_count: Mapped[int] = mapped_column(Integer)
    priced_sets_count: Mapped[int] = mapped_column(Integer)


class PriceAlert(Base):
    """"Préviens-moi si ce set descend sous X" — one threshold, one set, one condition (neuf *or*
    occasion, never both: they're priced by different sources and a single alert covering the pair
    couldn't say which one crossed). Carries its own copy of the set's identity because an alert
    outlives its `CachedSet` row."""

    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_num: Mapped[str] = mapped_column(String(64), index=True)
    condition: Mapped[str] = mapped_column(String(16))  # newSet | used
    set_name: Mapped[str] = mapped_column(String(512), default="")
    set_img_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    threshold_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Frozen at creation — re-resolving it on every evaluation would let the threshold drift with
    #: the market. lego.com retail when known, else the set's current resolved value.
    reference_price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_source_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    #: Notification fires on the *crossing* (False → True) only, never on every refresh that finds
    #: the price still low.
    was_below_threshold: Mapped[bool] = mapped_column(Boolean, default=False)
    last_observed_price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Drawn uniformly over the coming 7 days so watched sets spread out instead of all coming due
    #: at once, and re-drawn after every pass.
    next_refresh_due: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("set_num", "condition", name="uq_alert_set_condition"),)


# --------------------------------------------------------------------------------------
# Local catalogue snapshots (replace the iOS on-disk JSON stores)
# --------------------------------------------------------------------------------------


class CatalogSet(Base):
    """Rebrickable's `sets.csv.gz` dump, so identification works with no Rebrickable API call.
    `first_seen_at` is when *this* install first saw the set number in a downloaded snapshot —
    the honest "new set" signal `NewSetsView` sorts on."""

    __tablename__ = "catalog_sets"

    set_num: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(512))
    year: Mapped[int] = mapped_column(Integer, default=0, index=True)
    theme_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    num_parts: Mapped[int] = mapped_column(Integer, default=0)
    set_img_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class CatalogTheme(Base):
    """`themes.csv.gz` — id → name plus the `parent_id` hierarchy the non-set sub-tree filter
    walks (Gear / Books / LEGO Exclusive / Database Sets)."""

    __tablename__ = "catalog_themes"

    theme_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CatalogMinifig(Base):
    __tablename__ = "catalog_minifigs"

    fig_num: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(512))
    num_parts: Mapped[int] = mapped_column(Integer, default=0)
    img_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    containing_sets: Mapped[list[CatalogMinifigSet]] = relationship(
        back_populates="minifig", cascade="all, delete-orphan", lazy="selectin"
    )


class CatalogMinifigSet(Base):
    """The minifig ↔ set pivot, quantity included, with nested sub-sets already walked up to their
    ancestors (a CMF box contains sub-sets that each contain one minifig — owning the box owns
    them all)."""

    __tablename__ = "catalog_minifig_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fig_num: Mapped[str] = mapped_column(
        String(64), ForeignKey("catalog_minifigs.fig_num", ondelete="CASCADE"), index=True
    )
    set_num: Mapped[str] = mapped_column(String(64), index=True)
    quantity_per_set: Mapped[int] = mapped_column(Integer, default=1)
    #: Row order within a minifig — the first entry is the one `year`/`theme_id` are derived from.
    position: Mapped[int] = mapped_column(Integer, default=0)

    minifig: Mapped[CatalogMinifig] = relationship(back_populates="containing_sets")


class CatalogState(Base):
    """One row per downloadable catalogue ("sets", "themes", "minifigs"): when it was downloaded
    and how many rows it holds, so Réglages can report state without counting the table."""

    __tablename__ = "catalog_state"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Free-form progress/error surface for the UI while a download runs.
    status: Mapped[str | None] = mapped_column(String(512), nullable=True)


class BrickLinkItemMap(Base):
    """Rebrickable id → BrickLink catalog (type, id), resolved once by the parts cross-reference
    and cached forever. Misses are cached too, with the step that aborted, so a collection-wide
    refresh doesn't re-run the multi-call resolution for the ~half of minifigs that legitimately
    don't resolve."""

    __tablename__ = "bricklink_item_map"

    set_num: Mapped[str] = mapped_column(String(64), primary_key=True)
    bl_type: Mapped[str | None] = mapped_column(String(4), nullable=True)
    bl_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: NULL on a hit; the `MissReason` slug on a miss.
    miss_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------------------
# App state that iOS kept outside the database
# --------------------------------------------------------------------------------------


class AppSetting(Base):
    """Replaces `UserDefaults`. JSON-encoded values so a bool/number/string all round-trip."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Credential(Base):
    """Replaces the Keychain. Values are Fernet-encrypted with a key derived from
    `BRICKSEEKER_SECRET_KEY` — so a stolen `brickseeker.db` alone doesn't hand over the user's
    Rebrickable/Brickset/BrickLink credentials.

    The three-state read the iOS app needed (present / absent / undetermined) collapses to two
    here: a server-side read either finds the row or doesn't. There's no locked-device case, so
    "non configuré" copy is safe whenever the row is missing.
    """

    __tablename__ = "credentials"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_encrypted: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """In-app notification log — the self-hosted stand-in for `UNUserNotificationCenter`. Web Push
    delivers the same payload to subscribed browsers; this table is what the bell icon reads, so
    the feature still works for a user who never granted push permission."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))  # priceAlert | batchComplete | catalog
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    set_num: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    endpoint: Mapped[str] = mapped_column(Text, primary_key=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Session(Base):
    """Opaque session token for the optional password gate."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
