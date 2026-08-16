"""The official lego.com retail price.

lego.com sits behind a Cloudflare Managed Challenge. This was verified exhaustively on the iOS
side — `cf-mitigated: challenge`, a "Just a moment..." interstitial, and identical blocks from
several realistic browser User-Agents across several networks. It is not a header or cookie
problem: clearing the challenge requires executing the page's JavaScript. Don't spend time
retrying UA variations against a plain HTTP client; only a real browser engine gets through.

Four end states, all deliberately distinct:

* a price → `StorePrice` with an amount;
* a **retired** set → a real page that still loads, often *with* a residual price;
* **removed from the catalogue** → HTTP 404 once the challenge clears (`SET_NOT_ON_STORE`);
* the challenge never cleared → `TIMED_OUT`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from ..pricing import StoreAvailability, base_set_num
from .browser import (
    ScrapeChallengeUnsolved,
    ScrapeDisabled,
    ScrapeError,
    ScrapeHttpNotFound,
    load_and_extract,
)

TIMEOUT_SECONDS = 30.0


@dataclass(slots=True, frozen=True)
class StorePrice:
    amount: float | None
    currency: str | None
    availability: str | None

    @property
    def status(self) -> StoreAvailability:
        return StoreAvailability.from_raw(self.availability)


class LegoStoreErrorKind(StrEnum):
    TIMED_OUT = "timedOut"
    PAGE_UNAVAILABLE = "pageUnavailable"
    SET_NOT_ON_STORE = "setNotOnStore"
    OFFLINE = "offline"
    DISABLED = "disabled"


_MESSAGES = {
    LegoStoreErrorKind.TIMED_OUT: "Prix indisponible (lego.com n'a pas répondu)",
    LegoStoreErrorKind.PAGE_UNAVAILABLE: "Page lego.com indisponible",
    LegoStoreErrorKind.SET_NOT_ON_STORE: "Ce set n'est plus sur lego.com",
    LegoStoreErrorKind.OFFLINE: "Hors-ligne",
    LegoStoreErrorKind.DISABLED: "Récupération des prix web désactivée",
}


class LegoStoreError(Exception):
    def __init__(self, kind: LegoStoreErrorKind) -> None:
        super().__init__(_MESSAGES[kind])
        self.kind = kind


def store_url(set_num: str) -> str:
    return f"https://www.lego.com/fr-fr/product/{base_set_num(set_num)}"


def instructions_url(set_num: str) -> str:
    """Always offered: the page is a client-rendered shell that answers 200 whether or not the set
    actually has instructions, so there is no way to check without a full page load. lego.com
    handles the "no instructions" case itself."""
    return f"https://www.lego.com/fr-fr/service/building-instructions/{base_set_num(set_num)}"


#: `og:title` exists on every real product page and on none of the challenge interstitials, so a
#: ready page with no `product:price:amount` is a genuinely retired set, not one still loading.
_READINESS_JS = """
(() => {
  const el = document.querySelector('meta[property="og:title"]');
  return !!el && el.getAttribute('content') !== null;
})()
"""

_EXTRACT_JS = """
(() => {
  const get = (prop) => {
    const el = document.querySelector(`meta[property="${prop}"]`);
    return el ? el.getAttribute('content') : null;
  };
  return JSON.stringify({
    amount: get('product:price:amount'),
    currency: get('product:price:currency'),
    availability: get('product:availability')
  });
})()
"""


async def fetch_store_price(set_num: str) -> StorePrice:
    try:
        raw = await load_and_extract(
            store_url(set_num),
            readiness_js=_READINESS_JS,
            extract_js=_EXTRACT_JS,
            timeout=TIMEOUT_SECONDS,
            fails_on_http_404=True,
        )
    except ScrapeHttpNotFound as error:
        raise LegoStoreError(LegoStoreErrorKind.SET_NOT_ON_STORE) from error
    except ScrapeChallengeUnsolved as error:
        raise LegoStoreError(LegoStoreErrorKind.TIMED_OUT) from error
    except ScrapeDisabled as error:
        raise LegoStoreError(LegoStoreErrorKind.DISABLED) from error
    except ScrapeError as error:
        raise LegoStoreError(LegoStoreErrorKind.PAGE_UNAVAILABLE) from error

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise LegoStoreError(LegoStoreErrorKind.PAGE_UNAVAILABLE) from error

    amount_raw = payload.get("amount")
    amount: float | None = None
    if amount_raw is not None:
        try:
            amount = float(str(amount_raw).replace(",", "."))
        except ValueError:
            amount = None

    # The amount is never conditioned on the status: confirmed against real pages, a retired set
    # can keep serving its last price (21335-1 returned "retired" alongside 299.99). Read the
    # status directly; never infer "retired" from a missing amount.
    return StorePrice(
        amount=amount,
        currency=payload.get("currency"),
        availability=payload.get("availability"),
    )
