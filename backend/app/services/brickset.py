"""Brickset v3 API — the storage backend for the gift list.

Rebrickable can't host a wishlist: its `setlists` represent sets you actually *own*, confirmed
against the live API and site. Brickset's separate `wanted` flag is what this uses instead. This
client deliberately never touches Brickset's `owned` flag — ownership stays Rebrickable's.

Brickset answers **HTTP 200 on failure too**: the real outcome is the envelope's `status`/`message`,
not the status code. Three undocumented wire quirks, each confirmed live, each load-bearing:

* `setNumber` must be a bare JSON *string*. The array form the reference Java client implies
  returns `matches: 0` for sets that plainly exist.
* `wanted`/`want` must be the integer `1`/`0`. A JSON boolean throws "No valid parameters".
* A 429 comes from Cloudflare in front of Brickset, with a `Retry-After` worth honouring.
"""

from __future__ import annotations

import asyncio
import json
import random
from enum import StrEnum
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import ApiError, missing_credentials, network_unavailable
from ..security import CredentialKey, get_credential
from .throttle import brickset_throttler

BASE_URL = "https://brickset.com/api/v3.asmx"

LOGIN_PATH = "/login"
GET_SETS_PATH = "/getSets"
SET_COLLECTION_PATH = "/setCollection"

MAX_RETRIES = 2
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class WishlistImportOutcome(StrEnum):
    """Per-set result of the mass import. `NOT_FOUND_ON_BRICKSET` is an expected outcome — some
    polybags and GWPs simply aren't catalogued there — not a failure that should abort the batch."""

    ADDED = "added"
    ALREADY_WANTED = "alreadyWanted"
    NOT_FOUND_ON_BRICKSET = "notFoundOnBrickset"


class BricksetClient:
    def __init__(self, api_key: str | None, user_hash: str | None) -> None:
        self._api_key = api_key
        self._user_hash = user_hash

    # --- Transport -------------------------------------------------------------------

    async def _call(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        api_key: str | None = None,
        user_hash: str | None = None,
        retries_left: int = MAX_RETRIES,
    ) -> dict[str, Any]:
        key = api_key or self._api_key
        if not key:
            raise missing_credentials("Clé API Brickset non configurée")

        body = dict(params or {})
        body["apiKey"] = key
        hash_value = user_hash if user_hash is not None else self._user_hash
        if hash_value:
            body["userHash"] = hash_value

        await brickset_throttler.wait()
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(f"{BASE_URL}{path}", data=body)
        except httpx.HTTPError as error:
            raise network_unavailable() from error

        if response.status_code == 429:
            delay = _retry_after(response)
            if retries_left > 0 and delay is not None:
                # Jitter so several calls rate-limited at the same instant don't wake in lockstep
                # and trip the same limit again — seen live with a burst of concurrent requests.
                await asyncio.sleep(delay + random.uniform(0, 1.5))
                return await self._call(
                    path, params, api_key=key, user_hash=hash_value, retries_left=retries_left - 1
                )
            raise ApiError("Trop de requêtes Brickset, réessaie dans un instant.", 429)

        if response.status_code >= 400:
            raise network_unavailable()

        try:
            envelope = response.json()
        except json.JSONDecodeError as error:
            raise ApiError("Erreur lors du traitement de la réponse Brickset") from error

        if not isinstance(envelope, dict) or envelope.get("status") != "success":
            message = (envelope or {}).get("message") if isinstance(envelope, dict) else None
            raise ApiError(f"Erreur Brickset : {message or 'erreur inconnue'}")
        return envelope

    def _require_hash(self) -> str:
        if not self._user_hash:
            raise missing_credentials("Compte Brickset non lié")
        return self._user_hash

    # --- Auth ------------------------------------------------------------------------

    async def authenticate(self, username: str, password: str) -> str:
        """Exchanges credentials for a userHash. The password is used here and nowhere else."""
        envelope = await self._call(LOGIN_PATH, {"username": username, "password": password})
        user_hash = envelope.get("hash")
        if not user_hash:
            raise ApiError("Brickset n'a pas renvoyé de session")
        self._user_hash = str(user_hash)
        return self._user_hash

    # --- Wishlist --------------------------------------------------------------------

    async def _fetch_set(self, set_num: str) -> dict[str, Any] | None:
        """Resolves a Rebrickable-format number to Brickset's own entry, or None when Brickset
        doesn't catalogue it."""
        envelope = await self._call(
            GET_SETS_PATH,
            {"params": json.dumps({"setNumber": set_num})},
            user_hash=self._require_hash(),
        )
        sets = envelope.get("sets") or []
        return sets[0] if sets else None

    async def wishlist_status(self, set_num: str) -> bool:
        entry = await self._fetch_set(set_num)
        if entry is None:
            return False
        return bool((entry.get("collection") or {}).get("wanted"))

    async def add_to_wishlist(self, set_num: str) -> None:
        await self._set_wanted(set_num, True)

    async def remove_from_wishlist(self, set_num: str) -> None:
        await self._set_wanted(set_num, False)

    async def _set_wanted(self, set_num: str, wanted: bool) -> None:
        entry = await self._fetch_set(set_num)
        if entry is None:
            raise ApiError("Ce set n'existe pas sur Brickset", 404)
        await self._set_collection_want(int(entry["setID"]), wanted)

    async def _set_collection_want(self, set_id: int, wanted: bool) -> None:
        # Pre-serialised as 0/1 by hand rather than via a JSON boolean: Brickset's own docs don't
        # cover this wire format, and `true` reliably fails.
        await self._call(
            SET_COLLECTION_PATH,
            {"SetID": str(set_id), "params": json.dumps({"want": 1 if wanted else 0})},
            user_hash=self._require_hash(),
        )

    async def fetch_wishlist_set_numbers(self) -> list[str]:
        """Every wanted set, in Rebrickable "10307-1" format. Brickset splits that into `number`
        and `numberVariant`, which are rejoined here."""
        user_hash = self._require_hash()
        page = 1
        page_size = 100
        set_nums: list[str] = []
        while True:
            envelope = await self._call(
                GET_SETS_PATH,
                {"params": json.dumps({"wanted": 1, "pageSize": page_size, "pageNumber": page})},
                user_hash=user_hash,
            )
            sets = envelope.get("sets") or []
            # Stops on a genuinely empty page rather than comparing the count against the page size,
            # so this doesn't undercount if Brickset ever caps the effective size below what's asked.
            if not sets:
                break
            for entry in sets:
                number = entry.get("number")
                variant = entry.get("numberVariant")
                if number is not None and variant is not None:
                    set_nums.append(f"{number}-{variant}")
            page += 1
        return set_nums

    async def add_to_wishlist_if_needed(self, set_num: str) -> WishlistImportOutcome:
        """Resolve-and-add in a single lookup, so an N-set import costs N calls rather than 2N."""
        entry = await self._fetch_set(set_num)
        if entry is None:
            return WishlistImportOutcome.NOT_FOUND_ON_BRICKSET
        if (entry.get("collection") or {}).get("wanted"):
            return WishlistImportOutcome.ALREADY_WANTED
        await self._set_collection_want(int(entry["setID"]), True)
        return WishlistImportOutcome.ADDED


def _retry_after(response: httpx.Response) -> float | None:
    """Cloudflare sends plain integer seconds; the spec also allows an HTTP date. Capped at 60s so
    an unexpected value can't stall a caller."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(float(raw), 60.0)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        target = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    from datetime import UTC, datetime

    delta = (target - datetime.now(UTC)).total_seconds()
    return min(max(delta, 0.0), 60.0)


async def client_for(session: AsyncSession) -> BricksetClient:
    return BricksetClient(
        api_key=await get_credential(session, CredentialKey.BRICKSET_API_KEY),
        user_hash=await get_credential(session, CredentialKey.BRICKSET_USER_HASH),
    )


async def is_linked(session: AsyncSession) -> bool:
    return await get_credential(session, CredentialKey.BRICKSET_USER_HASH) is not None
