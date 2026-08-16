# Internal contract — service signatures and the REST surface

The one document backend services, routers and the frontend all code against. If an
implementation and this file disagree, this file is wrong and should be edited — but *only*
alongside the code on both sides of the boundary.

Two conventions hold everywhere:

- **JSON is camelCase**, matching the iOS models the port comes from (`setNum`, `numParts`,
  `isInCollection`). Python stays snake_case internally; Pydantic schemas do the aliasing.
- **A failure the user should read is an `ApiError`** (`deps.py`) carrying the app's own French
  wording. A source that merely has nothing to say (no BrickLink credentials, a scrape that
  timed out) is *omitted*, never an error — see "one bad source shouldn't hide the others".

---

## 1. Services

### `services/throttle.py`

```python
class Throttler:
    def __init__(self, minimum_interval: float) -> None: ...
    async def wait(self) -> None: ...

rebrickable_throttler: Throttler   # settings.rebrickable_min_interval
brickset_throttler: Throttler      # settings.brickset_min_interval
bricklink_throttler: Throttler     # settings.bricklink_min_interval
```

One instance per host. Unrelated hosts have independent rate limits, so a burst to one must not
slow the others.

### `services/rebrickable.py`

```python
BASE_URL = "https://rebrickable.com/api/v3"

@dataclass LegoSet:      set_num, name, year, theme_id, num_parts, set_img_url, set_url
@dataclass UserSet:      lego_set: LegoSet, quantity: int, include_spares: bool, list_id: int | None
@dataclass SetList:      id: int, name: str, num_sets: int
@dataclass MinifigSetEntry:  set_num, name, num_parts, set_img_url, set_url, quantity: int | None
@dataclass SetMinifigEntry:  set_num, name, quantity: int | None, set_img_url
@dataclass Paginated[T]: count: int, next: str | None, previous: str | None, results: list[T]

SetResolution = Found(LegoSet) | Ambiguous(list[LegoSet]) | NotFound   # a small tagged union

class RebrickableClient:
    def __init__(self, api_key: str | None, user_token: str | None) -> None
    async def authenticate(username, password) -> str        # POST /users/_token/ → user_token
    async def fetch_set(set_num) -> LegoSet
    async def search_sets(query, page_size=5) -> list[LegoSet]
    async def resolve_set(set_num) -> SetResolution
    async def fetch_user_set(set_num) -> UserSet | None
    async def fetch_all_user_sets() -> list[UserSet]
    async def add_set_to_list(set_num, list_id) -> None
    async def move_set_to_list(set_num, from_list_id, to_list_id) -> None
    async def remove_set_from_collection(set_num) -> None
    async def update_set_quantity(set_num, list_id, quantity) -> None
    async def fetch_user_set_lists() -> list[SetList]
    async def create_set_list(name) -> SetList
    async def fetch_sets_containing_minifig(fig_num, page_size=30) -> Paginated[MinifigSetEntry]
    async def fetch_minifigs_in_set(set_num, page_size=30) -> Paginated[SetMinifigEntry]
    async def fetch_similar_sets(lego_set, page_size=20) -> Paginated[LegoSet]
    async def fetch_part_external_ids(set_num, is_minifig) -> list[...]   # for BrickLink mapping

async def client_for(session) -> RebrickableClient   # reads credentials, raises missing_credentials
```

**Gotchas that are already paid for — do not rediscover them.** `GET /users/{token}/sets/{set_num}/`
returns the set **nested under a `"set"` key**, and the spares flag is `include_spares`.
`POST /users/{token}/sets/` has **no `list_id`** — targeting a list means
`POST /users/{token}/setlists/{list_id}/sets/`, and a "move" is DELETE from the old list then POST
to the new one (there is no direct endpoint). `add_set_to_list` / `move_set_to_list` /
`update_set_quantity` must **check the HTTP status only and never decode the response body** — that
body is not reliably the nested `Set` shape, and decoding it failed in production on calls that had
already succeeded server-side. Quantity updates use the **list-scoped** `PATCH
/users/{token}/setlists/{list_id}/sets/{set_num}/`, not the global `PUT`, which moves the extra copy
to the default list. `fetch_all_user_sets` is DRF-paginated and `next` is a **full URL**; a set owned
in several lists is **listed once per list**, so callers dedupe by `set_num`. There is **no
custom/wishlist list API** — `setlists` are owned sets only.

`resolve_set` tries `{set_num}-1`, then `{set_num}`, then a 5-result search: 0 → NotFound,
1 → Found, more → Ambiguous.

`fetch_similar_sets` has no dedicated endpoint: it filters `/lego/sets/` by the reference set's
`theme_id` plus a ±40 % `num_parts` window (skipped when `num_parts == 0`), `ordering=-year`. The
reference set matches its own filter and must be excluded by the caller.

### `services/brickset.py`

```python
BASE_URL = "https://brickset.com/api/v3.asmx"
WishlistImportOutcome = "added" | "alreadyWanted" | "notFoundOnBrickset"

class BricksetClient:
    def __init__(self, api_key: str | None, user_hash: str | None) -> None
    async def authenticate(username, password) -> str           # → userHash
    async def wishlist_status(set_num) -> bool
    async def add_to_wishlist(set_num) -> None
    async def remove_from_wishlist(set_num) -> None
    async def fetch_wishlist_set_numbers() -> list[str]         # Rebrickable "10307-1" format
    async def add_to_wishlist_if_needed(set_num) -> WishlistImportOutcome

async def client_for(session) -> BricksetClient
```

Brickset answers **HTTP 200 on failure too** — the outcome is the envelope's `status`/`message`,
so raise `ApiError` from that, not from the status code. Three undocumented wire quirks, all
confirmed live, all load-bearing: `setNumber` must be a bare JSON **string** (`{"setNumber":"10307-1"}`),
not an array — the array form returns `matches: 0` for sets that exist; `wanted`/`want` must be the
integer `1`/`0`, not `true`/`false`, which throws "No valid parameters"; and a 429 comes from
Cloudflare with a `Retry-After` header worth honouring (plus jitter, max 2 retries).

### `services/bricklink.py`

```python
def sign_oauth1(method, url, params, consumer_key, consumer_secret, token, token_secret) -> str

class BrickLinkClient:
    async def get(path, query) -> dict          # raises ApiError on meta.code != 200

async def fetch_prices(session, lego_set) -> list[PriceQuote]
```

Price Guide: `GET /items/{TYPE}/{no}/price` with
`guide_type=sold&new_or_used=N|U&currency_code=EUR&region=europe&vat=Y`.

- `guide_type=sold` (6-month realised sales), **never `stock`** — switching it silently redefines
  every stored history point and deal verdict.
- `region` is **not validated** by BrickLink (`region=BOGUS` → HTTP 200, silently worldwide), while
  `vat` **is** (`vat=BOGUS` → 400). A typo in `region` fails open and quietly restores the old
  worldwide meaning, so never edit that string casually.
- `avg_price` is the headline number. `qty_avg_price` is decoded and deliberately **unused**.
  `min_price`/`max_price` are meaningful only as a pair, `unit_quantity` is the lot count, and
  present-but-`"0.0000"` means absent.
- Decode leniently: everything past `avg_price` is decoration, and a strict decoder would throw
  away the price we display over one unexpected key type.
- Sales (`price_detail[]`) are capped at the 50 most recent and filtered to a 183-day window —
  BrickLink does not honour its own 6-month window and returns years-old outliers. The average is
  **not** recomputed from the filtered rows; the slight disagreement is deliberate.
- BrickLink answers **HTTP 200 on auth failures** too; the real outcome is `meta.code`.

Item resolution: try `SET`/`{set_num}` directly first. Minifigs (`fig-…`) and the rare
differently-filed set fall back to the parts cross-reference (Rebrickable part
`external_ids.BrickLink` → BrickLink part *supersets*, intersected over **printed/discriminant**
parts only → *subsets* composition check ≥ 0.5 overlap, highest overlap wins, ties broken by lowest
catalog id). Abstain — no quote, never a guess — when no candidate clears the bar or the
intersection leaves more than 20 survivors. Hits **and** misses cache in `BrickLinkItemMap`
(misses with their reason, TTL'd) so a collection-wide refresh doesn't re-run this for the ~half of
minifigs that legitimately never resolve.

### `services/scraping/`

```python
# browser.py
async def get_browser() -> Browser              # lazily launched, shared, restarted if crashed
async def shutdown_browser() -> None
async def load_and_extract(url, readiness_js, extract_js, timeout=None,
                           fails_on_http_404=False) -> str   # raises ScrapeError

class ScrapeError(Exception): ...
class ScrapeNotFound(ScrapeError): ...
class ScrapeHttpNotFound(ScrapeError): ...
class ScrapeChallengeUnsolved(ScrapeError): ...

# lego_store.py
@dataclass StorePrice: amount: float | None, currency: str | None, availability: str | None
async def fetch_store_price(set_num) -> StorePrice     # raises LegoStoreError
def store_url(set_num) -> str                          # lego.com/fr-fr/product/{base}
def instructions_url(set_num) -> str

# amazon.py / cdiscount.py
async def fetch_price(lego_set) -> PriceQuote | None
```

`load_and_extract` is the one browser code path: open a page, poll `readiness_js` until truthy
(that is how a Cloudflare challenge clearing is detected), then run `extract_js` and return its
`JSON.stringify` result. Each call gets its own page on the shared browser so independent scrapes
run in parallel; the browser context persists so `cf_clearance` survives between calls.

lego.com readiness is `og:title` present (absent on the challenge interstitial); extraction reads
`product:price:amount`, `product:price:currency`, `product:availability`. A **retired** set keeps a
real page *and often a residual price*, so never infer "retired" from a missing amount — read
availability directly. A set removed from the catalogue 404s once the challenge clears, which is a
**distinct** outcome from a timeout.

Amazon searches `amazon.fr/s?k=LEGO {digits}` and accepts a card only when the title is brand-first
(`^LEGO`), contains the set number, and is not an accessory (rejects `compatible`/`pour LEGO`/
`éclairage`/`LED`/`lighting`/`non inclus`/known lighting-kit brands). Without that filter a
third-party LED kit "compatible avec 10294" is matched as the set.

Cdiscount keys off `a[href*="/f-"]`, reads **`.textContent`** (`.innerText` comes back empty on
virtualised rows), takes the **last** price match in a card (a promo card lists the crossed-out
price first), strips the set reference from the text before the price regex (`"...- 303685,99 €"`
is `30368` + `5,99 €` with no separator), and rejects an implausible amount (> 5000 €) as a
backstop.

### `services/collection_repo.py` — the `LocalRepository` port

Every function takes `session: AsyncSession` first. This module is the **only** place that writes
the collection cache; routers never touch those tables directly.

```python
async def cache_set(session, lego_set, *, is_in_collection, list_id, list_name, mark_as_scanned) -> CachedSet
async def cached_set(session, set_num) -> CachedSet | None
async def owned_sets(session) -> list[CachedSet]
async def scanned_sets(session) -> list[CachedSet]
async def wishlist_sets(session) -> list[CachedSet]
async def counts(session) -> dict           # scannedSets, totalScans, ownedSets, wishlistSets
async def set_collection_status(session, set_num, *, is_in_collection, list_id, list_name) -> None
async def set_wishlist_status(session, set_num, is_in_wishlist) -> None
async def set_quantity(session, set_num, quantity) -> None
async def sync_collection(session, user_sets, lists) -> None
async def sync_wishlist(session, wanted_set_nums: set[str]) -> None
async def cache_wishlist_set(session, lego_set) -> None
async def cached_set_nums(session) -> set[str]
async def cache_set_lists(session, set_lists) -> None
async def cached_set_lists(session) -> list[CachedSetList]
async def condition_by_list_id(session) -> dict[int, ListCondition]
async def set_list_condition(session, list_id, condition) -> None
async def last_full_sync_at(session) -> datetime | None

async def cache_store_price(session, set_num, store_price) -> None
async def mark_prices_fetched(session, set_num) -> None
async def cache_prices(session, quotes, set_num, *, reconcile=False) -> None
async def cached_prices(session, set_num) -> list[PriceQuote]
async def all_cached_prices(session) -> dict[str, list[PriceQuote]]
async def price_history(session, set_num) -> list[PriceHistoryEntry]
async def sold_listings(session, set_num) -> list[SoldListing]

async def paid_price(session, set_num) -> float | None
async def paid_price_by_set_num(session) -> dict[str, float]
async def set_paid_price(session, set_num, paid_price_eur | None) -> None

async def record_scan_event(session, set_num, price_seen_eur=None) -> ScanEvent
async def update_scan_event_price(session, event_id, price_seen_eur) -> None
async def attach_location(session, event_id, lat, lon, place_name) -> None
async def strip_scan_locations(session, set_nums: set[str] | None) -> None
async def scan_events(session, set_num=None) -> list[ScanEvent]
async def delete_scan_event(session, event_id) -> None
async def delete_from_history(session, set_num) -> None

async def price_alerts(session, set_num=None) -> list[PriceAlert]
async def upsert_price_alert(session, ...) -> PriceAlert
async def set_price_alert_enabled(session, alert_id, is_enabled) -> None
async def delete_price_alert(session, alert_id) -> None
async def price_watch_targets(session) -> list[PriceWatchTarget]
async def reschedule_watch(session, set_num) -> None

async def record_collection_value_snapshot(session, *, total_value_eur, sets_count,
                                           units_count, priced_sets_count) -> None
async def collection_value_snapshots(session) -> list[CollectionValueSnapshot]

async def clear_cache(session) -> None
```

Behaviours that are not optional:

- `cache_set` upserts catalogue fields always, but only touches `was_scanned`/`last_scanned_at`
  when `mark_as_scanned` — simply reopening a set must not bump it to the top of History.
- Entering the collection **strips that set's scan locations** and **seeds a purchase record from
  the most recent priced scan** (idempotent: never overwrites a hand-edited price). Seeding is hooked
  into `cache_set`/`set_collection_status` only, **never** `sync_collection` — a set added from the
  Rebrickable website shouldn't inherit a shelf price this install never witnessed.
- `sync_collection` dedupes by `set_num` (first occurrence wins), and for rows that dropped out of
  the collection: `was_scanned` rows lose only their collection status, sync-only rows are deleted.
- `cache_prices(reconcile=True)` deletes cached sources absent from `quotes` — only ever for a
  genuine live fetch. A quote's `sales` list replaces that (set, source)'s sold listings wholesale;
  `sales is None` leaves them alone, `sales == []` clears them.
- `record_price_history` writes at most one row per (set, source, **day**) and trims past 180 days.
- `record_collection_value_snapshot` refuses to write at zero coverage and refuses to replace
  today's row with a **worse-covered** reading; keeps 1460 days.
- `clear_cache` deletes `CachedSet`, `CachedSetList`, `CachedSetPrice`, `SoldListing`,
  `CollectionSyncState` and strips all scan locations — and keeps `ScanEvent`, `SetPurchaseRecord`,
  `PriceAlert`, `PriceHistoryEntry`, `CollectionValueSnapshot`.

### `services/catalog.py`

```python
async def download_sets_catalog(session, progress=None) -> int
async def download_themes(session, force=False) -> int
async def download_minifigs_catalog(session, progress=None) -> int
async def purge_catalog(session, name) -> None
async def catalog_status(session) -> dict
async def lookup_catalog_set(session, set_num) -> LegoSet | None
async def theme_name(session, theme_id) -> str                 # "Thème #{id}" when unknown
async def theme_names(session) -> dict[int, str]
async def is_descendant(session, theme_id, ancestor_id) -> bool
async def non_set_kind(session, theme_id) -> str | None        # merchandise|book|exclusive|catalogArtifact
async def should_hide(session, theme_id, hide_enabled: bool) -> bool
def gunzip(data: bytes) -> bytes
def parse_csv(data: bytes) -> Iterator[list[str]]
```

Sources are Rebrickable's public unauthenticated dumps at `cdn.rebrickable.com/media/downloads/`:
`sets.csv.gz`, `themes.csv.gz`, `minifigs.csv.gz`, `inventories.csv.gz`,
`inventory_minifigs.csv.gz`, `inventory_sets.csv.gz`. No API key, and these must **not** go through
the Rebrickable throttler/auth header — they aren't v3 API calls.

`first_seen_at` on `CatalogSet` is only set on **insert**, never refreshed — it is the honest
"appeared in my catalogue on this date" signal `NewSetsView` sorts on.

The minifig join walks `inventory_sets` so a minifig inside a sub-set of a box (a CMF box contains
12 sub-sets, one minifig each) counts as owned when the box is owned, with quantities multiplied
along the chain.

Non-set identification is **structural** — four named theme sub-trees resolved through `parent_id`
(`Gear`, `Books`, `LEGO Exclusive` roots-only; `Database Sets` at any depth), never a list of ids
and never a `num_parts == 0` or non-numeric-set-number heuristic (both measured and rejected:
541 Books entries ship parts, and `AUTOSHOW-1` is a genuine 28-part promo set). `catalogArtifact`
hides regardless of the user's toggle; the rest follow it. Nothing is hidden until the theme table
has been downloaded — showing a cap is a nuisance, hiding a real set is not.

### `services/prices.py`

```python
async def fetch_prices(session, lego_set, *, bricklink_only=False) -> list[PriceQuote]
async def fetch_store_price(session, set_num) -> StorePrice | None
async def refresh_set_prices(session, lego_set, *, reconcile=True) -> dict
```

All sources in parallel; a source that fails or has no credentials is **omitted, never fatal**. A
minifig (`fig-…`) skips lego.com/Amazon/Cdiscount entirely — it is never sold at retail, so those
would only waste requests and produce misleading "Indisponible" rows. `bricklink_only=True` is the
background-pass mode.

### `services/price_updater.py`

```python
class PriceUpdater:            # module-level singleton `price_updater`
    state -> dict              # isRunning, done, total, currentSetNum, lastCompletedAt, mode
    async def start(set_nums=None, *, only_missing=False) -> str   # "started" | "busy"
    def cancel_preserving_progress() -> None
    async def run_watch_pass(limit) -> int
```

Strictly sequential with `settings.scrape_delay_between_sets` between sets — a whole collection's
worth of concurrent headless browsers is exactly what gets an IP flagged. The watch pass runs on
its **own** track (its own running flag, no persisted queue) so pausing the manual batch can't kill
it and vice versa; each guards against the other so the two never overlap. The watch pass does not
stamp `prices_fetched_at` — it only asked BrickLink, and stamping would drop the set out of
"Compléter les prix manquants" without lego.com/Amazon ever having been asked.

### `services/alerts.py`

```python
async def evaluate_alerts(session, set_num) -> list[PriceAlert]   # the ones that fired
def watched_price(condition, store_price_eur, availability, quotes) -> float | None
def next_due_date() -> datetime                                   # uniform over the next 7 days
```

Reads the just-written cache rather than taking quotes as arguments, so a new price path only has
to call it once. Only quotes fetched within 24 h are trusted — cached prices never expire, so
without that an alert could "notify" a drop off a months-old reading. `newSet` resolves through
`resolve_new_price`; `used` is the BrickLink used quote **alone**, no cross-fallback — an occasion
alert firing off a retail price reports something the user didn't ask about. Fires on the
**crossing** only (`was_below_threshold` False → True) with a 12 h floor between two notifications
for the same alert.

### `services/notifications.py`

```python
async def notify(session, *, kind, title, body, set_num=None) -> None
async def notify_price_alert(session, alert, price, threshold) -> None
async def notify_batch_complete(session, processed_count) -> None
async def subscribe_push(session, subscription) -> None
async def unsubscribe_push(session, endpoint) -> None
async def vapid_public_key(session) -> str     # generated and stored on first call
```

Writes the in-app row **first**, then best-effort Web Push — a browser that never granted
permission still gets the bell. A push that fails with 404/410 removes the dead subscription.

### `services/ocr.py`

```python
async def recognize_text(image_bytes) -> list[str]
def extract_set_numbers(candidates: list[str]) -> list[str]
```

`extract_set_numbers` is a straight port of `SetNumberExtractor`: `\b(\d{4,6})(-\d{1,2})?\b` plus a
labelled `Set No.|Art. Nr.` form, rejecting phone-number shapes, 4-digit values in `1949...2035`
(years), and anything ≥ 12 digits (EAN-13 barcodes read as text). Order-preserving, deduped.

### `services/exports.py`

```python
async def export_collection_csv(session) -> bytes
async def export_collection_pdf(session) -> bytes
```

### `services/image_cache.py`

```python
async def fetch_cached_image(url) -> tuple[bytes, str]     # (payload, content_type)
```

Disk cache keyed by a hash of the URL. Only `cdn.rebrickable.com`/`rebrickable.com` and
`img.bricklink.com` hosts are proxied — an open proxy would be an SSRF hole.

### `services/scheduler.py`

```python
def start_scheduler() -> None
def shutdown_scheduler() -> None
```

APScheduler, one job every `background_refresh_interval_minutes` running
`price_updater.run_watch_pass(settings.background_refresh_batch_size)`, plus a daily session purge.
The watched scope is **only sets carrying an enabled alert** — not the collection, not the gift
list. That restriction is the whole answer to "background polling doesn't scale"; widening it
reopens the decision.

---

## 2. REST surface

All under `/api`. Every route depends on `AuthDep`.

### auth
| Method | Path | Body / Query | Returns |
|---|---|---|---|
| GET | `/auth/status` | — | `{authRequired, authenticated}` |
| POST | `/auth/login` | `{password}` | `{ok: true}` + session cookie |
| POST | `/auth/logout` | — | `{ok: true}` |

### settings
| Method | Path | Body / Query | Returns |
|---|---|---|---|
| GET | `/settings` | — | `{preferences, credentials, catalog, priceUpdate}` |
| PATCH | `/settings/preferences` | partial preferences | preferences |
| PUT | `/settings/credentials/rebrickable-key` | `{apiKey}` | `{ok}` |
| POST | `/settings/link/rebrickable` | `{apiKey, username, password}` | `{ok}` |
| POST | `/settings/unlink/rebrickable` | — | `{ok}` |
| PUT | `/settings/credentials/brickset-key` | `{apiKey}` | `{ok}` |
| POST | `/settings/link/brickset` | `{apiKey, username, password}` | `{ok}` |
| POST | `/settings/unlink/brickset` | — | `{ok}` |
| PUT | `/settings/credentials/bricklink` | 4 OAuth values | `{ok}` |
| DELETE | `/settings/credentials/bricklink` | — | `{ok}` |
| POST | `/settings/clear-cache` | — | `{ok}` |

`credentials` reports **presence only** — never the values back.

### sets
| Method | Path | Returns |
|---|---|---|
| GET | `/sets/resolve?q=` | `{status: found\|ambiguous\|notFound\|offline, set?, candidates?}` |
| GET | `/sets/{setNum}` | full detail: set, collection status, prices, valuation, alerts, scans, availability, nonSetKind |
| GET | `/sets/search?q=&pageSize=` | `{results}` |
| GET | `/sets/{setNum}/minifigs` | `{count, results}` |
| GET | `/sets/{setNum}/similar` | `{results}` |
| GET | `/minifigs/{figNum}/sets` | `{count, results}` |

`/sets/resolve` mirrors the app's cache-first behaviour: a `CachedSet` hit answers immediately;
a live miss falls back to the offline catalogue **only** when the network is the problem, flagging
the result `offline` — an auth or server error is not a connectivity problem and must not be
silently masked.

### collection
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/collection` | — | `{sets, lists, lastSyncedAt, isLinked}` |
| POST | `/collection/sync` | — | `{sets, lists, lastSyncedAt}` |
| POST | `/collection/{setNum}` | `{listId}` | `{status}` |
| DELETE | `/collection/{setNum}` | — | `{status}` |
| PATCH | `/collection/{setNum}` | `{listId?, quantity?}` | `{status}` |
| GET | `/collection/lists` | — | `{lists}` |
| POST | `/collection/lists` | `{name}` | list |
| PATCH | `/collection/lists/{listId}` | `{condition}` | list |
| POST | `/collection/bulk` | `{setNums, action, listId?}` | `{succeeded, failed}` |

Each row carries its resolved price **and** which condition that price represents — a `.used` list
priced off the new chain must say so rather than trusting the nominal list.

### history
| GET | `/history` | `{sets}` — scanned sets with resolved new-price |
| GET | `/history/events?setNum=` | `{events}` |
| POST | `/history/events` | `{setNum, priceSeenEUR?, latitude?, longitude?}` → event |
| PATCH | `/history/events/{id}` | `{priceSeenEUR?, latitude?, longitude?, placeName?}` |
| DELETE | `/history/events/{id}` | `{ok}` |
| DELETE | `/history/{setNum}` | `{ok}` |
| GET | `/history/map` | `{points}` — located scans only |

### wishlist
| GET | `/wishlist` | `{sets, isLinked, lastSyncedAt}` |
| POST | `/wishlist/sync` | `{count}` |
| POST | `/wishlist/{setNum}` | `{ok}` |
| DELETE | `/wishlist/{setNum}` | `{ok}` |
| POST | `/wishlist/import` | CSV upload → `{added, alreadyWanted, notFound, failed, total}` |

The import accepts a Rebrickable custom-list CSV export; it reads the `Set Number` column, tolerates
a missing `-1` suffix, and reports per-set outcomes rather than aborting the batch on the first
set Brickset doesn't catalogue.

### prices
| GET | `/prices/{setNum}` | cached quotes + store price + history + sold listings |
| POST | `/prices/{setNum}/refresh` | live refresh → same shape |
| POST | `/prices/{setNum}/store-refresh` | lego.com only |
| GET | `/prices/batch/status` | updater state |
| POST | `/prices/batch/start` | `{setNums?, onlyMissing?}` → `{status}` |
| POST | `/prices/batch/cancel` | `{ok}` |
| POST | `/prices/deal-verdict` | `{setNum, priceSeen}` → verdict + comparisons |

### alerts
| GET | `/alerts` | `{alerts}` |
| GET | `/alerts/{setNum}` | both conditions for one set |
| PUT | `/alerts` | upsert `{setNum, condition, thresholdEUR?, discountPercent?, isEnabled}` |
| PATCH | `/alerts/{id}` | `{isEnabled}` |
| DELETE | `/alerts/{id}` | `{ok}` |

The percentage's reference is resolved **server-side at creation** (lego.com retail when known,
else the set's current resolved value for that condition) and frozen, with the source named.

### stats
| GET | `/stats` | full `CollectionStats` + value snapshots |
| GET | `/stats/export.csv` | text/csv attachment |
| GET | `/stats/export.pdf` | application/pdf attachment |

### catalog
| GET | `/catalog/status` | per-catalogue downloaded-at + row counts |
| POST | `/catalog/sets/download` | `{ok}` (background task, progress via status) |
| POST | `/catalog/minifigs/download` | `{ok}` |
| DELETE | `/catalog/{name}` | purge |
| GET | `/catalog/themes` | `{themes}` |
| GET | `/catalog/new-sets?…` | filtered/sorted catalogue page + `firstSeenAt` |
| GET | `/catalog/minifigs?…` | owned-minifig gallery with quantities and cached prices |

### scan
| POST | `/scan/ocr` | multipart image → `{candidates, setNums}` |
| POST | `/scan/lookup` | `{setNum, source}` → same shape as `/sets/resolve` + records a `ScanEvent` when `source == "camera"` |

Only a **camera** scan records a `ScanEvent` — manual entry, photo import and a History re-open
carry no "I was standing in a store" meaning.

### images
| GET | `/images?url=` | cached proxy, `Cache-Control: public, max-age=604800` |

### notifications
| GET | `/notifications` | `{notifications, unreadCount}` |
| POST | `/notifications/read` | `{ids?}` → marks read (all when omitted) |
| GET | `/notifications/vapid-key` | `{publicKey}` |
| POST | `/notifications/subscribe` | push subscription JSON |
| POST | `/notifications/unsubscribe` | `{endpoint}` |

---

## 3. Frontend routes

| Path | Screen | iOS counterpart |
|---|---|---|
| `/` | Accueil — stats tiles, scan cluster, sync state | `HomeView` |
| `/scan` | Camera scanner with reticle + OCR polling | `ScannerView` |
| `/collection` | Owned sets: search, filters, sort, multi-select bulk actions | `CollectionView` |
| `/history` | Scanned sets + scan map | `HistoryView` / `ScanMapView` |
| `/wishlist` | Liste cadeaux + CSV import | `WishlistView` |
| `/stats` | Charts, superlatives, exports | `StatisticsView` |
| `/minifigs` | Owned-minifig gallery | `MinifigGalleryView` |
| `/new-sets` | Catalogue browser sorted by first-seen | `NewSetsView` |
| `/alerts` | Price-alert management | `PriceAlertsView` |
| `/settings` | Credentials, theme, catalogue, price batch | `SettingsView` |
| `/onboarding` | First-launch walkthrough | `OnboardingView` |
| set detail | Sheet/modal over any list, swipeable within the list it came from | `SetDetailView` / `SetDetailPagerView` |

UI text is **French**, matching the app. The shared list screen (search bar, filter sheet, sort,
multi-select bottom bar, context menu, `ContentUnavailableView`-style empty state) is one component
reused by Collection/History/Wishlist/NewSets — the same "don't reinvent it" rule the iOS codebase
states for those four screens.
