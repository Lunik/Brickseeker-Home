"""Cultura price from the retailer's public Magento GraphQL catalogue.

The catalogue sits behind a Cloudflare challenge that refuses a bare HTTP client (`403`), so the
query runs **inside a page of the shared browser**, same-origin, the way the site's own front end
does it. A challenge then surfaces as `ScrapeBlocked` and reaches the interactive popup like any
other browser-backed retailer; once validated, the clearance cookie is reused.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .browser import ScrapeError, ScrapeNotFound, load_and_extract

_HOME = "https://www.cultura.com/"
_ENDPOINT = "/m2/graphql"
_QUERY = """
query Products($search: String!) {
  products(search: $search, pageSize: 5) {
    items {
      name
      url_key
      price_range {
        minimum_price {
          final_price {
            value
            currency
          }
        }
      }
    }
  }
}
"""
#: The interstitial keeps the page title/body of its own; real content only after it clears.
_READINESS_JS = """
(() => {
  const text = document.body ? document.body.innerText : '';
  return document.readyState !== 'loading'
    && !/Un instant|Vérification de sécurité/i.test(text)
    && text.trim().length > 0;
})()
"""


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _quote_from_payload(payload: object, digits: str) -> PriceQuote | None:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    products = data.get("products") if isinstance(data, Mapping) else None
    items = products.get("items") if isinstance(products, Mapping) else None
    if not isinstance(items, list):
        if isinstance(payload, Mapping) and payload.get("errors"):
            raise ScrapeError("Cultura GraphQL a refusé la recherche")
        return None

    exact_number = re.compile(rf"(?<!\d){re.escape(digits)}(?!\d)")
    for item in items:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "")
        if not exact_number.search(name):
            continue
        price_range = item.get("price_range")
        minimum = (
            price_range.get("minimum_price") if isinstance(price_range, Mapping) else None
        )
        final = minimum.get("final_price") if isinstance(minimum, Mapping) else None
        if not isinstance(final, Mapping):
            continue
        amount = _number(final.get("value"))
        if amount is None or amount <= 0 or amount > 5000:
            continue
        url_key = item.get("url_key")
        return PriceQuote(
            source=PriceSource.CULTURA,
            amount=amount,
            currency=str(final.get("currency") or "EUR"),
            title=name,
            source_url=(
                f"https://www.cultura.com/p-{url_key}.html"
                if isinstance(url_key, str) and url_key
                else f"https://www.cultura.com/search/results?search_query=LEGO+{digits}"
            ),
            fetched_at=datetime.now(UTC),
        )
    return None


def _extract_js(digits: str) -> str:
    request = json.dumps({"query": _QUERY, "variables": {"search": digits}})
    return f"""
(async () => {{
  const response = await fetch({json.dumps(_ENDPOINT)}, {{
    method: 'POST',
    headers: {{ 'content-type': 'application/json' }},
    body: {json.dumps(request)},
  }});
  if (!response.ok) throw new Error('HTTP ' + response.status);
  return await response.text();
}})()
"""


async def fetch_price(lego_set: LegoSet) -> PriceQuote | None:
    digits = set_digits(lego_set.set_num)
    try:
        raw = await load_and_extract(
            _HOME, readiness_js=_READINESS_JS, extract_js=_extract_js(digits)
        )
    except ScrapeNotFound:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise ScrapeError("Réponse Cultura illisible") from error
    return _quote_from_payload(payload, digits)
