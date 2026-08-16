"""BrickLink Store API — OAuth 1.0a signing, the Price Guide call, and Rebrickable→BrickLink
item resolution.

Port of `BrickLinkOAuth1.swift`, `BrickLinkClient.swift`, `BrickLinkPriceRepository.swift` and
`BrickLinkMinifigIdStore.swift`. Three properties of this API drive the whole design and none of
them is guessable from the (JS-only, non-static) official docs — they were probed live:

* **HTTP 200 is not the outcome.** An invalid token comes back as HTTP 200 with `meta.code: 401`
  (`TOKEN_IP_MISMATCHED`). `meta.code` is the real status; the transport code only matters for a
  gateway-level 429 that carries no envelope at all.
* **`region` is not validated, `vat` is.** `region=BOGUS` returns HTTP 200 and silently reverts to
  a worldwide average, while `vat=BOGUS` returns HTTP 400. So a typo in `region` *fails open* and
  quietly changes what every stored price means, with no error anywhere. `PRICE_GUIDE_PARAMS` is
  not a string to edit casually.
* **Nothing maps a Rebrickable id to a BrickLink one.** No BrickLink endpoint accepts a Rebrickable
  id and neither catalogue exposes the correspondence, so it is reconstructed from physical part
  composition across the two official APIs. That resolution favours precision over recall
  (~100 % / ~53 % measured on a real collection) and **abstains rather than guessing**: a wrong
  price is worse than no price.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import random
import re
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import ApiError, network_unavailable, not_found, rate_limited, unauthorized
from ..models import BrickLinkItemMap
from ..security import get_bricklink_credentials
from .pricing import PriceQuote, PriceSource, SoldSale, is_minifig
from .rebrickable import LegoSet
from .rebrickable import client_for as rebrickable_client_for
from .throttle import bricklink_throttler

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bricklink.com/api/store/v1"

#: The user-facing catalogue page, offered as the quote's `source_url`. Deliberately *not* an API
#: URL — this is a link the user opens, unrelated to the signed call that produced the number.
CATALOG_ITEM_URL = "https://www.bricklink.com/v2/catalog/catalogitem.page"

#: Every query parameter of the Price Guide call except `new_or_used`.
#:
#: `guide_type=sold` is the 6-month *realised sales* average — never `stock` (current asking
#: prices). Switching it silently redefines every stored `PriceHistoryEntry` and every deal
#: verdict, which is why it lives in a constant rather than at a call site.
#:
#: The other three pin the quote to the French market so BrickLink sits on the same terms as the
#: lego.com/Amazon/Cdiscount rows next to it (euros, VAT in, European sellers) instead of a
#: worldwide ex-VAT average that made the `±%` between the rows meaningless. Measured cost of that
#: choice, worth remembering: samples shrink a lot (`42143-1` new: 51 sales → 28), so
#: `PriceQuote.is_thin_sample` is load-bearing rather than decorative.
#:
#: There is deliberately no `completeness` parameter: it is not a knob this endpoint has
#: (`S`/`C`/`B`/`BOGUS` all return byte-identical data), and it is unnecessary — BrickLink already
#: excludes incomplete lots from the guide. Do not re-add one, and above all do not reach for the
#: *Items For Sale* page to obtain it.
PRICE_GUIDE_PARAMS: dict[str, str] = {
    "guide_type": "sold",
    "currency_code": "EUR",
    "region": "europe",
    "vat": "Y",
}

#: How many recent sales are kept per item+condition. A heavily-traded set returns hundreds of
#: `price_detail[]` rows, re-sent in full on every refresh; the newest ones are also the only ones
#: that say anything about today's price.
MAX_STORED_SALES = 50

#: How far back a sale may be dated and still count as part of the advertised "6 derniers mois".
#: BrickLink does not honour its own window: `75192-1` returned sales dated 2023-10-12 and
#: 2025-05-25 among 22 sales from 2026, the latter at 26,54 € against a 485,78 € median. 183 days
#: rather than a strict six months so a legitimate sale isn't lost to timezone skew at the boundary.
SALES_WINDOW = timedelta(days=183)

#: Cap on how many discriminant parts are intersected — a minifig rarely has more than a few
#: printed parts, and this bounds the BrickLink calls for an edge-case set with many.
MAX_DISCRIMINANT_PARTS = 8

#: Fraction of the item's parts a candidate's own inventory must cover to be accepted.
VERIFY_THRESHOLD = 0.5

#: Above this many survivors, abstain instead of composition-verifying. A "printed" part can be a
#: near-universal print (the classic smiley `3626ap01`, shared by hundreds of minifigs — seen live
#: on `fig-000342`: 407 survivors from that one part), which means it was never discriminant and
#: the verification wouldn't be trustworthy even if it finished. Each check is one throttled
#: BrickLink call, so verifying hundreds would also stall a collection-wide refresh for minutes.
MAX_CANDIDATES_TO_VERIFY = 20

#: How long a failed resolution is remembered before being retried. Not permanent: BrickLink can
#: gain inventory data, and the resolver can improve. Without it, a collection-wide refresh re-runs
#: the whole multi-call cross-reference for the ~half of minifigs that legitimately never resolve.
MISS_TTL = timedelta(days=14)

_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

_API_TYPE_BY_LETTER: dict[str, str] = {
    "S": "SET",
    "M": "MINIFIG",
    "P": "PART",
    "B": "BOOK",
    "G": "GEAR",
    "C": "CATALOG",
    "I": "INSTRUCTION",
    "O": "ORIGINAL_BOX",
    "U": "UNSORTED_LOT",
}

_LETTER_BY_API_TYPE: dict[str, str] = {value: key for key, value in _API_TYPE_BY_LETTER.items()}


@dataclass(slots=True, frozen=True)
class CatalogRef:
    """The single-letter catalogue type BrickLink uses in its URLs (`S`, `M`, `P`, …) plus the id
    within that catalogue — e.g. `S`+`71039-1`, or `M`+`oct033`."""

    type: str
    id: str


class MissReason(StrEnum):
    """Which step of the cross-reference gave up, persisted alongside the miss so a recurring
    unresolved item can be diagnosed from real data instead of guessed at."""

    NO_PARTS = "noParts"
    NO_DISCRIMINANT = "noDiscriminant"
    NO_CANDIDATES = "noCandidates"
    TOO_MANY_CANDIDATES = "tooManyCandidates"
    COMPOSITION_MISMATCH = "compositionMismatch"
    UNKNOWN = "unknown"


class _ResolutionAborted(Exception):
    """A genuine "this item cannot be resolved" — cached as a miss. Transport, auth and throttle
    failures are `ApiError` instead and are never cached, or a blip would suppress a resolvable
    item for the whole TTL."""

    def __init__(self, reason: MissReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


# --------------------------------------------------------------------------------------
# OAuth 1.0a (RFC 5849), HMAC-SHA1 — BrickLink's only supported signature method
# --------------------------------------------------------------------------------------


def _percent_encode(value: str) -> str:
    """RFC 5849 §3.6: unreserved characters only.

    `quote`'s always-safe set is exactly RFC 3986's unreserved set, so `safe=""` *is* the rule —
    the default `safe="/"` would leave slashes raw inside the signed parameter string and produce
    a signature BrickLink rejects.
    """
    return quote(value, safe="")


def sign_oauth1(
    method: str,
    url: str,
    params: Mapping[str, str],
    consumer_key: str,
    consumer_secret: str,
    token: str,
    token_secret: str,
    *,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> str:
    """The `Authorization` header value for one request.

    `params` must list every query parameter that will actually be sent: they are part of the
    signature base string (§3.4.1), so signing one set and sending another yields a 401 that looks
    exactly like bad credentials.
    """
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    # OAuth parameters win a name clash, matching the app — a request parameter called
    # `oauth_token` must not be able to displace the real one out of the signature.
    signed_params = {**dict(params), **oauth_params}

    # §3.4.1.3.2: encode first, then sort on the *encoded* pairs — sorting the raw names gives a
    # different order for anything outside ASCII-alphanumeric.
    normalized = "&".join(
        f"{key}={value}"
        for key, value in sorted(
            (_percent_encode(name), _percent_encode(raw)) for name, raw in signed_params.items()
        )
    )
    base_url = url.split("?", 1)[0]
    base_string = "&".join([method.upper(), _percent_encode(base_url), _percent_encode(normalized)])
    signing_key = f"{_percent_encode(consumer_secret)}&{_percent_encode(token_secret)}"
    digest = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()

    header_params = {**oauth_params, "oauth_signature": base64.b64encode(digest).decode()}
    rendered = ", ".join(
        f'{_percent_encode(name)}="{_percent_encode(value)}"'
        for name, value in sorted(header_params.items())
    )
    return f"OAuth {rendered}"


# --------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------


class BrickLinkClient:
    """Signed GETs against the Store API.

    Owns an `httpx.AsyncClient` unless one is injected, so use it as an async context manager (or
    call `aclose()`); every path in this module does.
    """

    #: Bail out after this many 429 retries rather than retrying forever — one throttled host must
    #: not turn a several-hundred-set price refresh into an infinite loop.
    MAX_RETRIES = 2

    def __init__(self, credentials: Mapping[str, str], *, http: httpx.AsyncClient | None = None) -> None:
        self._credentials = dict(credentials)
        self._owns_http = http is None
        self._http = http if http is not None else httpx.AsyncClient(timeout=_HTTP_TIMEOUT)

    async def __aenter__(self) -> BrickLinkClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def get(self, path: str, query: Mapping[str, str] | None = None) -> Any:
        """The envelope's `data`, or raise. Deliberately untyped: `data` is an object for the price
        guide but an *array* for supersets/subsets."""
        return await self._get(path, dict(query or {}), self.MAX_RETRIES)

    async def _get(self, path: str, query: dict[str, str], retries_left: int) -> Any:
        await bricklink_throttler.wait()

        url = f"{BASE_URL}{path}"
        header = sign_oauth1(
            "GET",
            url,
            query,
            self._credentials["consumer_key"],
            self._credentials["consumer_secret"],
            self._credentials["token"],
            self._credentials["token_secret"],
        )
        # Built by hand with the same encoder the signature uses, so what is signed and what goes
        # on the wire cannot drift apart through a client's own query-encoding conventions.
        query_string = "&".join(
            f"{_percent_encode(name)}={_percent_encode(value)}" for name, value in sorted(query.items())
        )
        request_url = f"{url}?{query_string}" if query_string else url

        try:
            response = await self._http.get(request_url, headers={"Authorization": header})
        except httpx.HTTPError as exc:
            raise network_unavailable() from exc

        # A gateway-level 429 in front of the API may carry no envelope at all, so the transport
        # status is checked before a decode failure could be mistaken for one.
        if response.status_code == 429:
            return await self._retry_or_give_up(path, query, retries_left, response)

        try:
            envelope = response.json()
        except ValueError as exc:
            raise ApiError("Erreur lors du traitement de la réponse", 502) from exc
        if not isinstance(envelope, Mapping):
            raise ApiError("Erreur lors du traitement de la réponse", 502)

        meta = envelope.get("meta")
        meta = meta if isinstance(meta, Mapping) else {}
        code = _lenient_int(meta.get("code"))
        if code is None:
            raise ApiError("Erreur lors du traitement de la réponse", 502)

        if 200 <= code <= 299:
            data = envelope.get("data")
            if data is None:
                raise not_found()
            return data
        if code in (401, 403):
            raise unauthorized()
        if code == 404:
            raise not_found()
        if code == 429:
            return await self._retry_or_give_up(path, query, retries_left, response)
        if 500 <= code <= 599:
            raise ApiError(f"Erreur serveur ({code})", 502)
        detail = meta.get("description") or meta.get("message") or code
        raise ApiError(f"Erreur BrickLink : {detail}")

    async def _retry_or_give_up(
        self, path: str, query: dict[str, str], retries_left: int, response: httpx.Response
    ) -> Any:
        if retries_left <= 0:
            raise rate_limited()
        # BrickLink's own rate-limit signal is an application-level `meta.code: 429` inside an
        # HTTP-200 envelope, which has no reason to carry `Retry-After` the way a gateway 429
        # would — hence the fallback. Jitter so two conditions throttled at the same instant don't
        # retry in lockstep.
        delay = _retry_after(response) or 2.0
        await asyncio.sleep(delay + random.uniform(0, 1.0))
        return await self._get(path, query, retries_left - 1)


def _retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` as plain seconds or an HTTP-date, capped at 30 s so an unexpected header value
    can't stall a caller indefinitely."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(float(raw), 30.0)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return min(max(0.0, (_aware(parsed) - datetime.now(UTC)).total_seconds()), 30.0)


# --------------------------------------------------------------------------------------
# Price Guide
# --------------------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _PriceGuide:
    """The Price Guide payload, decoded field by field.

    Everything past `avg_price` is decoration, and a strict decoder would throw away the price the
    UI displays over one unexpected key type in that decoration — the wrong trade. The shape below
    was verified against a live signed call, but that is one item at one moment, not a contract.
    """

    currency_code: str
    avg_price: float | None
    min_price: float | None
    max_price: float | None
    #: Quantity-weighted average. Decoded to mirror the wire shape and deliberately never read:
    #: promoting it to `PriceQuote.amount` would silently redefine every stored history point and
    #: deal verdict, the same trap as switching `guide_type`.
    qty_avg_price: float | None
    #: Lots behind the guide, i.e. how many *sales* the range spans. `total_quantity` counts
    #: individual items across those lots, which reads as a bigger, more reassuring number than
    #: the sample actually is — decoded, never surfaced.
    unit_quantity: int | None
    total_quantity: int | None
    price_detail: list[Mapping[str, Any]]

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> _PriceGuide:
        detail = payload.get("price_detail")
        return cls(
            currency_code=str(payload.get("currency_code") or "EUR"),
            avg_price=_decimal(payload.get("avg_price")),
            min_price=_decimal(payload.get("min_price")),
            max_price=_decimal(payload.get("max_price")),
            qty_avg_price=_decimal(payload.get("qty_avg_price")),
            unit_quantity=_lenient_int(payload.get("unit_quantity")),
            total_quantity=_lenient_int(payload.get("total_quantity")),
            price_detail=[row for row in detail if isinstance(row, Mapping)]
            if isinstance(detail, list)
            else [],
        )


def _decimal(value: object) -> float | None:
    """Money arrives as a decimal *string*; a number is accepted too rather than assuming."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _lenient_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def _positive(value: float | None) -> float | None:
    """An item with no recorded sale in the window returns `"0.0000"` everywhere instead of
    omitting the field, so present-but-zero means absent."""
    return value if value is not None and value > 0 else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse_ordered_at(raw: object) -> datetime | None:
    """`date_ordered` came back as `2026-05-28T00:18:27.603Z`, but BrickLink documents no format.
    `fromisoformat` accepts the fractional-seconds-less variant through the same call, so dropping
    the milliseconds one day wouldn't silently discard every sale."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return _aware(parsed)


def _sales(details: Sequence[Mapping[str, Any]]) -> list[SoldSale]:
    """`price_detail[]` mapped to the app's own value type, capped and windowed.

    Entries missing a price or a date are dropped rather than guessed at: a sale with no
    `date_ordered` has no x-coordinate, so there is nowhere honest to plot it.

    Note the asymmetry this creates and leave it alone: `amount` stays BrickLink's own `avg_price`,
    which *does* include the stale sales filtered out here, so the scatter and the average disagree
    slightly. Recomputing the average from the surviving rows would swap a documented number for a
    home-made one — inventing a cote. Honest points under an imperfect average beat a fabricated
    consistency.
    """
    cutoff = datetime.now(UTC) - SALES_WINDOW
    sales: list[SoldSale] = []
    for detail in details:
        unit_amount = _positive(_decimal(detail.get("unit_price")))
        ordered_at = _parse_ordered_at(detail.get("date_ordered"))
        if unit_amount is None or ordered_at is None or ordered_at < cutoff:
            continue
        sales.append(
            SoldSale(
                unit_amount=unit_amount,
                quantity=max(1, _lenient_int(detail.get("quantity")) or 1),
                ordered_at=ordered_at,
            )
        )
    # Newest-first to decide which survive the cap, then back to chronological order for storage.
    sales.sort(key=lambda sale: sale.ordered_at, reverse=True)
    return sorted(sales[:MAX_STORED_SALES], key=lambda sale: sale.ordered_at)


async def _fetch_quote(
    client: BrickLinkClient,
    api_type: str,
    item_id: str,
    new_or_used: str,
    source: PriceSource,
    item_url: str,
) -> PriceQuote | None:
    payload = await client.get(
        f"/items/{api_type}/{quote(item_id, safe='')}/price",
        {**PRICE_GUIDE_PARAMS, "new_or_used": new_or_used},
    )
    if not isinstance(payload, Mapping):
        return None

    guide = _PriceGuide.decode(payload)
    amount = _positive(guide.avg_price)
    if amount is None:
        return None

    # The range only means something as a pair: a lone bound renders as "12 € – " and, worse,
    # implies a spread we don't actually know.
    min_amount = _positive(guide.min_price)
    max_amount = _positive(guide.max_price)
    if min_amount is None or max_amount is None:
        min_amount = max_amount = None

    return PriceQuote(
        source=source,
        amount=amount,
        currency=guide.currency_code,
        source_url=item_url,
        fetched_at=datetime.now(UTC),
        min_amount=min_amount,
        max_amount=max_amount,
        lot_count=_lenient_int(_positive(guide.unit_quantity)),
        sales=_sales(guide.price_detail),
    )


async def _quotes_for(client: BrickLinkClient, ref: CatalogRef) -> list[PriceQuote]:
    """Both conditions for one resolved catalogue item."""
    api_type = _API_TYPE_BY_LETTER.get(ref.type)
    if api_type is None:
        return []
    item_url = f"{CATALOG_ITEM_URL}?{ref.type}={ref.id}"

    quotes: list[PriceQuote] = []
    failures: list[ApiError] = []
    for new_or_used, source in (("N", PriceSource.BRICKLINK_NEW), ("U", PriceSource.BRICKLINK_USED)):
        try:
            found = await _fetch_quote(client, api_type, ref.id, new_or_used, source, item_url)
        except ApiError as exc:
            # One condition failing must not cost us the other — the same "one bad source shouldn't
            # hide the others" rule, one level down.
            failures.append(exc)
            continue
        if found is not None:
            quotes.append(found)
    if quotes:
        return quotes

    # Nothing came back. A 404 means BrickLink genuinely doesn't file this item under this ref, and
    # the caller falls through to the cross-reference; anything else is a real failure and must not
    # be dressed up as "no price".
    hard_failure = next((exc for exc in failures if exc.status_code != 404), None)
    if hard_failure is not None:
        raise hard_failure
    return []


# --------------------------------------------------------------------------------------
# Item resolution: Rebrickable id → BrickLink catalogue ref
# --------------------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _Part:
    bl_part_id: str
    is_printed: bool


_PRINTED_ID_RE = re.compile(r"p[brx][0-9]", re.IGNORECASE)
_PART_ID_KEYS = ("bl_part_id", "bricklink_id", "bricklink_part_id", "part_id", "external_id", "no")
_PRINTED_KEYS = ("is_printed", "printed")
_NAME_KEYS = ("name", "part_name")


def _is_printed(bl_id: str, name: str) -> bool:
    """Whether a part is printed/decorated — the only kind specific enough to pin a single item.
    Matches a printed BrickLink id suffix (`973pb3509c01`, `3626px298`) or a Print/Pattern/Decorated
    mention in the Rebrickable part name."""
    if _PRINTED_ID_RE.search(bl_id):
        return True
    lowered = name.lower()
    return any(token in lowered for token in ("print", "pattern", "decorat"))


def _field(entry: object, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if isinstance(entry, Mapping):
            if key in entry:
                return entry[key]
        elif hasattr(entry, key):
            return getattr(entry, key)
    return None


def _coerce_part(entry: object) -> _Part | None:
    """Read one row of `fetch_part_external_ids` structurally.

    The contract elides that row's type (`list[...]`), and the printed/decorated test is BrickLink
    domain knowledge that may equally have stayed on this side of the boundary — so a `(id, bool)`
    pair, a `(id, part_name)` pair, and an object/mapping carrying either are all accepted, and the
    classification is derived here whenever the row doesn't already carry it.
    """
    if isinstance(entry, tuple | list) and len(entry) == 2 and isinstance(entry[0], str):
        bl_part_id, second = entry
        printed = second if isinstance(second, bool) else _is_printed(bl_part_id, str(second or ""))
        return _Part(bl_part_id, bool(printed)) if bl_part_id else None

    bl_part_id = _field(entry, _PART_ID_KEYS)
    if not isinstance(bl_part_id, str) or not bl_part_id:
        return None
    printed = _field(entry, _PRINTED_KEYS)
    if isinstance(printed, bool):
        return _Part(bl_part_id, printed)
    return _Part(bl_part_id, _is_printed(bl_part_id, str(_field(entry, _NAME_KEYS) or "")))


async def _rebrickable_parts(session: AsyncSession, set_num: str, minifig: bool) -> list[_Part]:
    client = await rebrickable_client_for(session)
    try:
        rows = await client.fetch_part_external_ids(set_num, minifig)
    finally:
        # `client_for` hands back a fresh client per call, so if it holds a connection pool this
        # call site is the one that has to give it back.
        closer = getattr(client, "aclose", None)
        if closer is not None:
            await closer()
    parts = (_coerce_part(row) for row in rows or [])
    return [part for part in parts if part is not None]


def _entries(payload: object) -> Iterator[Mapping[str, Any]]:
    """Both supersets and subsets return `data` as an array of match groups, each wrapping
    `entries` whose `item` carries the catalogue `no` and full `type`."""
    if not isinstance(payload, list):
        return
    for group in payload:
        if not isinstance(group, Mapping):
            continue
        entries = group.get("entries")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, Mapping):
                yield entry


async def _supersets(
    client: BrickLinkClient, bl_part_id: str, accepted_types: set[str]
) -> set[CatalogRef]:
    """BrickLink catalogue items of `accepted_types` that contain the given part."""
    payload = await client.get(f"/items/PART/{quote(bl_part_id, safe='')}/supersets")
    refs: set[CatalogRef] = set()
    for entry in _entries(payload):
        item = entry.get("item")
        if not isinstance(item, Mapping):
            continue
        api_type, number = item.get("type"), item.get("no")
        if api_type not in accepted_types or not isinstance(number, str) or not number:
            continue
        letter = _LETTER_BY_API_TYPE.get(str(api_type))
        if letter is not None:
            refs.add(CatalogRef(letter, number))
    return refs


async def _subset_part_numbers(client: BrickLinkClient, ref: CatalogRef) -> set[str]:
    """The BrickLink part numbers that make up a catalogue item, for the composition check."""
    api_type = _API_TYPE_BY_LETTER.get(ref.type)
    if api_type is None:
        return set()
    payload = await client.get(f"/items/{api_type}/{quote(ref.id, safe='')}/subsets")
    numbers: set[str] = set()
    for entry in _entries(payload):
        item = entry.get("item")
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "PART" and isinstance(item.get("no"), str):
            numbers.add(item["no"])
    return numbers


async def _cross_reference(
    session: AsyncSession, client: BrickLinkClient, set_num: str, minifig: bool
) -> CatalogRef:
    """Pin the BrickLink item using only official APIs, in three steps:

    1. Rebrickable — the item's parts, each carrying its BrickLink part id.
    2. BrickLink — intersect the *supersets* of the **printed** parts only. Generic torsos and legs
       are shared across thousands of figures and produce confident false positives.
    3. BrickLink — verify each survivor by composition: its own inventory must cover
       `VERIFY_THRESHOLD` of the item's parts.

    A printed-parts tie is not an automatic abstain: every survivor is verified and the highest
    overlap wins, because a recolour or reissue sharing the same printed combination usually
    separates once each side's *full* inventory is compared. A remaining tie — two candidates
    compositionally identical, e.g. the same design filed twice — resolves to the lowest catalogue
    id rather than abstaining: no part-level signal is left to distinguish them, so a deterministic
    closest match beats no price at all once verification has ruled out everything else.
    """
    parts = await _rebrickable_parts(session, set_num, minifig)
    if not parts:
        raise _ResolutionAborted(MissReason.NO_PARTS)

    discriminant: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part.is_printed and part.bl_part_id not in seen:
            seen.add(part.bl_part_id)
            discriminant.append(part.bl_part_id)
    if not discriminant:
        raise _ResolutionAborted(MissReason.NO_DISCRIMINANT)

    # A Rebrickable *set* number can resolve to a BrickLink minifig (a collectible-minifig box) or
    # to a set; a Rebrickable minifig always resolves to a BrickLink minifig.
    accepted_types = {"MINIFIG"} if minifig else {"MINIFIG", "SET"}

    survivors: set[CatalogRef] | None = None
    for part_id in discriminant[:MAX_DISCRIMINANT_PARTS]:
        try:
            candidates = await _supersets(client, part_id, accepted_types)
        except ApiError as exc:
            # A part BrickLink's catalogue doesn't recognise (a stale Rebrickable mapping) must not
            # abandon the whole item — keep narrowing with the others. Real failures still surface.
            if exc.status_code == 404:
                continue
            raise
        if not candidates:
            continue
        survivors = candidates if survivors is None else survivors & candidates
        if not survivors:
            break

    if not survivors:
        raise _ResolutionAborted(MissReason.NO_CANDIDATES)
    if len(survivors) > MAX_CANDIDATES_TO_VERIFY:
        raise _ResolutionAborted(MissReason.TOO_MANY_CANDIDATES)

    item_parts = {part.bl_part_id for part in parts}
    verified: list[tuple[float, CatalogRef]] = []
    for candidate in sorted(survivors, key=lambda ref: (ref.type, ref.id)):
        try:
            candidate_parts = await _subset_part_numbers(client, candidate)
        except ApiError as exc:
            if exc.status_code != 404:
                raise
            candidate_parts = set()
        overlap = len(item_parts & candidate_parts) / len(item_parts)
        if overlap >= VERIFY_THRESHOLD:
            verified.append((overlap, candidate))

    if not verified:
        raise _ResolutionAborted(MissReason.COMPOSITION_MISMATCH)
    verified.sort(key=lambda pair: (-pair[0], pair[1].id))
    return verified[0][1]


async def _remember(
    session: AsyncSession, set_num: str, ref: CatalogRef | None, reason: MissReason | None
) -> None:
    row = await session.get(BrickLinkItemMap, set_num)
    if row is None:
        row = BrickLinkItemMap(set_num=set_num)
        session.add(row)
    row.bl_type = ref.type if ref is not None else None
    row.bl_id = ref.id if ref is not None else None
    row.miss_reason = None if ref is not None else (reason or MissReason.UNKNOWN).value
    row.recorded_at = datetime.now(UTC)
    await session.commit()


async def _resolve_ref(
    session: AsyncSession, client: BrickLinkClient, set_num: str, minifig: bool
) -> CatalogRef | None:
    """The cached mapping, or one freshly cross-referenced. `None` means "abstained" — never a
    guess, and the reason is persisted with the miss."""
    row = await session.get(BrickLinkItemMap, set_num)
    if row is not None:
        # A hit is permanent: BrickLink never reassigns a catalogue id.
        if row.bl_type and row.bl_id:
            return CatalogRef(row.bl_type, row.bl_id)
        if row.miss_reason and _aware(row.recorded_at) > datetime.now(UTC) - MISS_TTL:
            return None

    try:
        ref = await _cross_reference(session, client, set_num, minifig)
    except _ResolutionAborted as abort:
        logger.info("BrickLink : %s non résolu (%s)", set_num, abort.reason.value)
        await _remember(session, set_num, None, abort.reason)
        return None
    await _remember(session, set_num, ref, None)
    return ref


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


async def fetch_prices(session: AsyncSession, lego_set: LegoSet) -> list[PriceQuote]:
    """BrickLink's new and used quotes for one item, or `[]` when it has nothing to say.

    Unconfigured credentials return `[]` rather than raising: BrickLink is then simply one more
    source with no opinion, and the price card shows the others. An unresolvable item returns `[]`
    too. Transport, auth and rate-limit failures do raise — the aggregator omits the source, but
    the distinction between "abstained" and "broke" is worth keeping.
    """
    credentials = await get_bricklink_credentials(session)
    if credentials is None:
        return []

    set_num = lego_set.set_num
    minifig = is_minifig(set_num)

    async with BrickLinkClient(credentials) as client:
        # Most Rebrickable set numbers are usable as BrickLink's own `SET` number — try that before
        # spending the multi-call cross-reference. A failure here is not fatal: the rare set
        # BrickLink files under another type falls through to resolution, which surfaces any real
        # error on its own calls.
        if not minifig:
            try:
                quotes = await _quotes_for(client, CatalogRef("S", set_num))
            except ApiError as exc:
                logger.debug("BrickLink : SET/%s indisponible (%s)", set_num, exc.detail)
                quotes = []
            if quotes:
                return quotes

        ref = await _resolve_ref(session, client, set_num, minifig)
        if ref is None:
            return []
        return await _quotes_for(client, ref)
