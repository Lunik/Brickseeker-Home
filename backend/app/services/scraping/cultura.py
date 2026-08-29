"""Cultura price from the retailer's public Magento GraphQL catalogue."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .browser import ScrapeError

_ENDPOINT = "https://www.cultura.com/m2/graphql"
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
_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


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
            source_url=(
                f"https://www.cultura.com/p-{url_key}.html"
                if isinstance(url_key, str) and url_key
                else f"https://www.cultura.com/search/results?search_query=LEGO+{digits}"
            ),
            fetched_at=datetime.now(UTC),
        )
    return None


async def fetch_price(lego_set: LegoSet) -> PriceQuote | None:
    digits = set_digits(lego_set.set_num)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(
                _ENDPOINT,
                json={"query": _QUERY, "variables": {"search": digits}},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ScrapeError(f"Cultura GraphQL indisponible : {error}") from error
    return _quote_from_payload(payload, digits)
