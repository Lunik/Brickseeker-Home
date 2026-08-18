"""Rebrickable v3 client — port of the iOS `NetworkClient` + `RebrickableEndpoint` +
`RebrickableRepository` trio.

Two credentials, and they are not interchangeable (AGENTS.md, "Auth model"): the **API key** is a
static header (`Authorization: key …`) required by nearly every endpoint, and the **user token**
is a path segment for the collection endpoints, obtained once from username + password. There is
no endpoint that derives the key from a login — don't try to simplify that away again.

Rebrickable's own swagger omits response and form-body schemas, so every shape below was verified
against the live API or the community spec. The ones that cost a production bug are commented at
their call site; treat them as findings, not preferences.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import quote

import httpx
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import (
    ApiError,
    forbidden,
    missing_credentials,
    network_unavailable,
    not_found,
    rate_limited,
    unauthorized,
)
from ..security import CredentialKey, get_credential
from .throttle import rebrickable_throttler

BASE_URL = "https://rebrickable.com/api/v3"

#: Generous enough for the slower list endpoints, bounded so one hung call can't hold a whole
#: collection sync open.
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


# --------------------------------------------------------------------------------------
# Wire models
# --------------------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class LegoSet:
    set_num: str
    name: str
    year: int
    theme_id: int
    num_parts: int
    set_img_url: str | None
    set_url: str | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> LegoSet:
        return cls(
            set_num=str(payload["set_num"]),
            name=str(payload.get("name") or ""),
            year=int(payload.get("year") or 0),
            theme_id=int(payload.get("theme_id") or 0),
            num_parts=int(payload.get("num_parts") or 0),
            set_img_url=_optional_str(payload.get("set_img_url")),
            set_url=_optional_str(payload.get("set_url")),
        )


@dataclass(slots=True, frozen=True)
class UserSet:
    """One row of the user's collection. The `LegoSet` arrives **nested under a `"set"` key**, not
    flat, and the spares flag is `include_spares` (not `inc_spares`)."""

    lego_set: LegoSet
    quantity: int
    include_spares: bool
    list_id: int | None

    @property
    def set_num(self) -> str:
        return self.lego_set.set_num

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> UserSet:
        nested = payload["set"]
        if not isinstance(nested, Mapping):
            raise TypeError("set")
        list_id = payload.get("list_id")
        return cls(
            lego_set=LegoSet.from_payload(nested),
            quantity=int(payload.get("quantity") or 0),
            include_spares=bool(payload.get("include_spares")),
            list_id=int(list_id) if list_id is not None else None,
        )


@dataclass(slots=True, frozen=True)
class SetList:
    id: int
    name: str
    num_sets: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SetList:
        return cls(
            id=int(payload["id"]),
            name=str(payload.get("name") or ""),
            num_sets=int(payload.get("num_sets") or 0),
        )


@dataclass(slots=True, frozen=True)
class MinifigSetEntry:
    """One entry of `/lego/minifigs/{fig_num}/sets/` — the sets a minifig has appeared in.

    `quantity` is optional because this particular list isn't documented to carry one, unlike
    sibling endpoints nesting a near-identical set shape; the UI shows "×N" only when it arrives.
    There is no `theme_id` here and adding one would be wishful: verified live, the key never
    comes, which is why callers needing a theme cross-reference the offline catalogue instead.
    """

    set_num: str
    name: str
    num_parts: int
    set_img_url: str | None
    set_url: str | None
    quantity: int | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> MinifigSetEntry:
        quantity = payload.get("quantity")
        return cls(
            set_num=str(payload["set_num"]),
            name=str(payload.get("name") or ""),
            num_parts=int(payload.get("num_parts") or 0),
            set_img_url=_optional_str(payload.get("set_img_url")),
            set_url=_optional_str(payload.get("set_url")),
            quantity=int(quantity) if quantity is not None else None,
        )


@dataclass(slots=True, frozen=True)
class SetMinifigEntry:
    """One entry of `/lego/sets/{set_num}/minifigs/` — the minifigs a set contains.

    The reverse side of the same pivot, but **not** the same shape: confirmed live after the
    assumption that Rebrickable serialises both directions identically shipped a silent decode
    failure on every response. This side sends no `num_parts`/`set_url`, and the minifig's name
    arrives as `set_name`.
    """

    set_num: str
    name: str
    quantity: int | None
    set_img_url: str | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SetMinifigEntry:
        quantity = payload.get("quantity")
        return cls(
            set_num=str(payload["set_num"]),
            name=str(payload.get("set_name") or ""),
            quantity=int(quantity) if quantity is not None else None,
            set_img_url=_optional_str(payload.get("set_img_url")),
        )


@dataclass(slots=True, frozen=True)
class Paginated[T]:
    count: int
    next: str | None
    previous: str | None
    results: list[T]


@dataclass(slots=True, frozen=True)
class PartExternalId:
    """One (inventory part → BrickLink part id) pair, with the printed flag already derived.

    `is_printed` lives here rather than on the BrickLink side because the evidence is Rebrickable's
    — the part's own name and number — and having one owner keeps the two catalogues' consumers
    from drifting on what counts as a discriminant part.
    """

    bl_part_id: str
    is_printed: bool
    part_num: str = ""
    name: str = ""


@dataclass(slots=True, frozen=True)
class Found:
    lego_set: LegoSet
    status: ClassVar[str] = "found"


@dataclass(slots=True, frozen=True)
class Ambiguous:
    candidates: list[LegoSet]
    status: ClassVar[str] = "ambiguous"


@dataclass(slots=True, frozen=True)
class NotFound:
    status: ClassVar[str] = "notFound"


#: The `status` class attribute is the exact string `/sets/resolve` reports, so the router never
#: re-derives a vocabulary the iOS `SetResolution` enum already fixed.
SetResolution = Found | Ambiguous | NotFound


# --------------------------------------------------------------------------------------
# Decoding helpers
# --------------------------------------------------------------------------------------


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _decoding_error() -> ApiError:
    """The app's own wording for a response that didn't have the shape we expect. When this shows
    up, suspect a Rebrickable shape change first — never a network or auth problem."""
    return ApiError("Erreur lors du traitement de la réponse", status.HTTP_502_BAD_GATEWAY)


def _decode[T](payload: Any, build: Callable[[Mapping[str, Any]], T]) -> T:
    if not isinstance(payload, Mapping):
        raise _decoding_error()
    try:
        return build(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise _decoding_error() from exc


def _decode_page[T](payload: Any, build: Callable[[Mapping[str, Any]], T]) -> Paginated[T]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("results"), list):
        raise _decoding_error()
    try:
        return Paginated(
            count=int(payload.get("count") or 0),
            next=_optional_str(payload.get("next")),
            previous=_optional_str(payload.get("previous")),
            results=[_decode(item, build) for item in payload["results"]],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _decoding_error() from exc


def _seg(value: str) -> str:
    """Path-segment encoding — a set number reaches this module straight from user input and must
    not be able to reshape the URL."""
    return quote(value, safe="")


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise _decoding_error() from exc


def _server_error(code: int) -> ApiError:
    return ApiError(f"Erreur serveur ({code})", status.HTTP_502_BAD_GATEWAY)


def _raise_for_status(response: httpx.Response) -> None:
    """Rebrickable reports failure through the HTTP status (unlike Brickset and BrickLink, which
    answer 200 and hide the outcome in the envelope), so the code alone is authoritative here."""
    code = response.status_code
    if 200 <= code < 300:
        return
    if code == status.HTTP_401_UNAUTHORIZED:
        raise unauthorized()
    if code == status.HTTP_403_FORBIDDEN:
        raise forbidden()
    if code == status.HTTP_404_NOT_FOUND:
        raise not_found()
    if code == status.HTTP_429_TOO_MANY_REQUESTS:
        raise rate_limited()
    if code >= 500:
        raise _server_error(code)
    raise ApiError("Une erreur inconnue est survenue")


#: A printed/decorated part carries a `pb`/`pr`/`px` + digit marker in its number (`973pb3509c01`,
#: `3626px298`) — the same convention in both catalogues' numbering.
_PRINTED_NUMBER = re.compile(r"p[brx][0-9]", re.IGNORECASE)
_PRINTED_WORDS = ("print", "pattern", "decorat")


def _is_printed(bl_part_id: str, part_num: str, name: str) -> bool:
    if _PRINTED_NUMBER.search(bl_part_id) or _PRINTED_NUMBER.search(part_num):
        return True
    lowered = name.lower()
    return any(word in lowered for word in _PRINTED_WORDS)


# --------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------


class RebrickableClient:
    def __init__(self, api_key: str | None, user_token: str | None) -> None:
        self._api_key = api_key
        self._user_token = user_token

    # --- Auth ------------------------------------------------------------------------

    async def authenticate(self, username: str, password: str) -> str:
        """Exchanges username + password for the user token, using the API key this client was
        built with. The password is used here and nowhere else — it is never stored."""
        if not self._api_key:
            raise missing_credentials("Clé API Rebrickable non configurée")
        payload = _json(
            await self._request(
                "POST", f"{BASE_URL}/users/_token/", data={"username": username, "password": password}
            )
        )
        token = payload.get("user_token") if isinstance(payload, Mapping) else None
        if not token:
            raise _decoding_error()
        # Kept on the instance so a "Lier mon compte" flow can sync straight after linking.
        self._user_token = str(token)
        return self._user_token

    def _require_token(self) -> str:
        """The collection endpoints carry the user token in the path.

        There is deliberately no silent re-authentication when it expires (HTTP 403): the password
        was never stored, so nothing here could refresh the token. The 403 surfaces and the user
        re-runs "Lier mon compte" — don't add a retry that can only ever fail.
        """
        if not self._user_token:
            raise missing_credentials("Compte Rebrickable non lié")
        return self._user_token

    # --- Catalogue -------------------------------------------------------------------

    async def fetch_set(self, set_num: str) -> LegoSet:
        return _decode(await self._get(f"/lego/sets/{_seg(set_num)}/"), LegoSet.from_payload)

    async def search_sets(self, query: str, page_size: int = 5) -> list[LegoSet]:
        payload = await self._get("/lego/sets/", {"search": query, "page_size": str(page_size)})
        return _decode_page(payload, LegoSet.from_payload).results

    async def resolve_set(self, set_num: str) -> SetResolution:
        """`{set_num}-1` first: the `-1` variant is what a scanned box number almost always means,
        and trying the bare number first would miss it."""
        for candidate in (f"{set_num}-1", set_num):
            found = await self._fetch_set_or_none(candidate)
            if found is not None:
                return Found(found)
        results = await self.search_sets(set_num, page_size=5)
        if not results:
            return NotFound()
        if len(results) == 1:
            return Found(results[0])
        return Ambiguous(results)

    async def _fetch_set_or_none(self, set_num: str) -> LegoSet | None:
        # Any failure falls through to the search step, exactly as the app's `try?` did: a genuine
        # auth/network problem hits the same wall there and surfaces from that call instead.
        try:
            return await self.fetch_set(set_num)
        except ApiError:
            return None

    async def fetch_similar_sets(self, lego_set: LegoSet, page_size: int = 20) -> Paginated[LegoSet]:
        """Rebrickable has no "similar sets" endpoint (`/alternates/` is MOC alternate builds, a
        different concept), so this is the plain `/lego/sets/` list filtered to the reference set's
        theme and a ±40 % parts window.

        The window is skipped when `num_parts` is 0 — a handful of catalogue entries carry no part
        count, and `min_parts=max_parts=0` would match only other zero-part entries. `ordering=-year`
        merely decides which sets land in this single page; the caller re-sorts by size proximity,
        and must drop the reference set, which always matches a filter derived from itself.
        """
        params = {
            "theme_id": str(lego_set.theme_id),
            "page_size": str(page_size),
            "ordering": "-year",
        }
        if lego_set.num_parts > 0:
            params["min_parts"] = str(math.floor(lego_set.num_parts * 0.6))
            params["max_parts"] = str(math.ceil(lego_set.num_parts * 1.4))
        return _decode_page(await self._get("/lego/sets/", params), LegoSet.from_payload)

    async def fetch_sets_containing_minifig(
        self, fig_num: str, page_size: int = 30
    ) -> Paginated[MinifigSetEntry]:
        """One page only, no pagination loop: a popular minifig appears in hundreds of sets and the
        UI shows a capped gallery — `count` is what feeds the "et N sets supplémentaires" note."""
        payload = await self._get(f"/lego/minifigs/{_seg(fig_num)}/sets/", {"page_size": str(page_size)})
        return _decode_page(payload, MinifigSetEntry.from_payload)

    async def fetch_minifigs_in_set(self, set_num: str, page_size: int = 30) -> Paginated[SetMinifigEntry]:
        payload = await self._get(f"/lego/sets/{_seg(set_num)}/minifigs/", {"page_size": str(page_size)})
        return _decode_page(payload, SetMinifigEntry.from_payload)

    async def fetch_part_external_ids(self, set_num: str, is_minifig: bool) -> list[PartExternalId]:
        """The item's inventory parts, each carrying its BrickLink part id — step 1 of the
        BrickLink catalog cross-reference.

        One page of 100, deliberately not a pagination walk: a minifig has a handful of parts, and
        for the edge-case sets that need this the discriminant printed parts are among the first
        too. In this inventory context `external_ids.BrickLink` is a flat array of part-number
        strings — a different shape from `/lego/parts/{num}/`, which nests `ext_ids`/`ext_descrs`.
        """
        category = "minifigs" if is_minifig else "sets"
        payload = await self._get(
            f"/lego/{category}/{_seg(set_num)}/parts/",
            {"inc_part_details": "1", "page_size": "100"},
        )
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, list):
            raise _decoding_error()

        parts: list[PartExternalId] = []
        for entry in results:
            part = entry.get("part") if isinstance(entry, Mapping) else None
            if not isinstance(part, Mapping):
                continue
            external = part.get("external_ids")
            bl_ids = external.get("BrickLink") if isinstance(external, Mapping) else None
            # A part BrickLink's catalogue doesn't know is ordinary, not an error — it just can't
            # contribute to the cross-reference.
            if not isinstance(bl_ids, list):
                continue
            part_num = str(part.get("part_num") or "")
            name = str(part.get("name") or "")
            for bl_id in bl_ids:
                if not bl_id:
                    continue
                parts.append(
                    PartExternalId(
                        bl_part_id=str(bl_id),
                        is_printed=_is_printed(str(bl_id), part_num, name),
                        part_num=part_num,
                        name=name,
                    )
                )
        return parts

    # --- Collection ------------------------------------------------------------------

    async def fetch_user_set(self, set_num: str) -> UserSet | None:
        token = self._require_token()
        try:
            payload = await self._get(f"/users/{_seg(token)}/sets/{_seg(set_num)}/")
        except ApiError as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                return None  # "not in the collection", not a failure.
            raise
        return _decode(payload, UserSet.from_payload)

    async def fetch_all_user_sets(self) -> list[UserSet]:
        """The whole collection, DRF-paginated.

        A set owned in several Set Lists comes back **once per list** — documented behaviour, not a
        bug. Callers assuming one list per set (`collection_repo.sync_collection`) dedupe by
        `set_num`, keeping the first occurrence.
        """
        token = self._require_token()
        collected: list[UserSet] = []
        url = f"{BASE_URL}/users/{_seg(token)}/sets/"
        params: dict[str, str] | None = {"page_size": "100"}
        visited: set[str] = set()
        while True:
            page = _decode_page(_json(await self._request("GET", url, params=params)), UserSet.from_payload)
            collected.extend(page.results)
            # `next` is a full URL, not a page number — don't re-derive page params from it. It is
            # echoed back by the server and our Authorization header follows it wherever it points,
            # so a foreign or repeating URL ends the walk instead of leaking the key or looping.
            following = page.next
            if not following or not following.startswith(BASE_URL) or following in visited:
                return collected
            visited.add(following)
            url, params = following, None

    async def add_set_to_list(self, set_num: str, list_id: int) -> None:
        """`POST /users/{token}/sets/` has no `list_id` — targeting a list means posting to the
        list itself.

        The response body is **not** decoded: it doesn't reliably carry the nested `Set` shape, and
        decoding it failed in production on adds that had already succeeded server-side. Only the
        status is trusted; callers re-read real state via `fetch_user_set`.
        """
        token = self._require_token()
        await self._request(
            "POST",
            f"{BASE_URL}/users/{_seg(token)}/setlists/{list_id}/sets/",
            data={"set_num": set_num, "quantity": "1"},
        )

    async def move_set_to_list(self, set_num: str, from_list_id: int, to_list_id: int) -> None:
        """No endpoint changes a set's list directly, so a move is DELETE from the old list then
        POST to the new one. Same "status only, never decode the body" rule as `add_set_to_list`."""
        token = self._require_token()
        await self._request(
            "DELETE", f"{BASE_URL}/users/{_seg(token)}/setlists/{from_list_id}/sets/{_seg(set_num)}/"
        )
        await self.add_set_to_list(set_num, to_list_id)

    async def remove_set_from_collection(self, set_num: str) -> None:
        token = self._require_token()
        await self._request("DELETE", f"{BASE_URL}/users/{_seg(token)}/sets/{_seg(set_num)}/")

    async def update_set_quantity(self, set_num: str, list_id: int, quantity: int) -> None:
        """List-scoped PATCH, **not** the global `PUT /users/{token}/sets/{set_num}/`: that one
        applies across every Set List and puts the extra copy in the *default* list rather than the
        one the set is in (a set in "sealed" jumped to "displayed" on increment). Body not decoded,
        same reason as `add_set_to_list`.
        """
        token = self._require_token()
        await self._request(
            "PATCH",
            f"{BASE_URL}/users/{_seg(token)}/setlists/{list_id}/sets/{_seg(set_num)}/",
            data={"quantity": str(quantity)},
        )

    async def fetch_user_set_lists(self) -> list[SetList]:
        """Set Lists are lists of sets the user actually **owns** — there is no custom/wishlist list
        API on Rebrickable (checked against the live API, and a wishlist built on this was reverted
        once already). The gift list lives on Brickset instead."""
        token = self._require_token()
        payload = await self._get(f"/users/{_seg(token)}/setlists/")
        return _decode_page(payload, SetList.from_payload).results

    async def create_set_list(self, name: str) -> SetList:
        token = self._require_token()
        response = await self._request(
            "POST", f"{BASE_URL}/users/{_seg(token)}/setlists/", data={"name": name}
        )
        return _decode(_json(response), SetList.from_payload)

    # --- Transport -------------------------------------------------------------------

    async def _get(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        return _json(await self._request("GET", BASE_URL + path, params=params))

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        await rebrickable_throttler.wait()
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"key {self._api_key}"
        # A client per call, not one held on the instance: `client_for` already builds a client per
        # request, nothing owns a shutdown hook to close a long-lived one, and with a ≥1 s throttle
        # between calls a kept-alive connection buys nothing.
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
                response = await client.request(method, url, params=params, data=data, headers=headers)
        except httpx.RequestError as exc:
            raise network_unavailable() from exc
        _raise_for_status(response)
        return response


async def client_for(session: AsyncSession) -> RebrickableClient:
    """The API key gates every endpoint, so its absence is refused up front; the user token gates
    only the collection calls and is checked by those (`_require_token`) — reading a set's details
    must keep working on an install that never linked an account."""
    api_key = await get_credential(session, CredentialKey.REBRICKABLE_API_KEY)
    if not api_key:
        raise missing_credentials("Clé API Rebrickable non configurée")
    user_token = await get_credential(session, CredentialKey.REBRICKABLE_USER_TOKEN)
    return RebrickableClient(api_key=api_key, user_token=user_token)
