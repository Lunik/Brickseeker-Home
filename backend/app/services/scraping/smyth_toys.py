"""Smyths Toys France price from its public autocomplete catalogue."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .browser import ScrapeError, parse_amount, parse_currency

_API_ENDPOINT = "https://www.smythstoys.com/api/fr/fr-fr/search/auto-complete"
_ORIGIN = "https://www.smythstoys.com"
_STOREFRONT_PREFIX = "/fr/fr-fr"
_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_PLAUSIBLE_MAX_AMOUNT = 5000.0


def _source_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    parsed = urlparse(raw)
    if parsed.scheme:
        if parsed.scheme != "https" or parsed.hostname != "www.smythstoys.com":
            return None
        return raw
    if raw.startswith("//"):
        return None
    path = f"/{raw.lstrip('/')}"
    if path.startswith(f"{_STOREFRONT_PREFIX}/"):
        return f"{_ORIGIN}{path}"
    return f"{_ORIGIN}{_STOREFRONT_PREFIX}{path}"


def _quote_from_payload(payload: object, digits: str) -> PriceQuote | None:
    if not isinstance(payload, Mapping):
        raise ScrapeError("Réponse Smyths Toys invalide")
    products = payload.get("products")
    if not isinstance(products, list):
        raise ScrapeError("Catalogue Smyths Toys invalide")

    exact_number = re.compile(rf"(?<!\d){re.escape(digits)}(?!\d)")
    for product in products:
        if not isinstance(product, Mapping):
            continue
        name = product.get("name")
        if not isinstance(name, str) or not name.casefold().startswith("lego "):
            continue
        if not exact_number.search(name):
            continue
        prices = product.get("prices")
        price_text = prices.get("price") if isinstance(prices, Mapping) else None
        if not isinstance(price_text, str):
            continue
        amount = parse_amount(price_text)
        if amount is None or amount <= 0 or amount > _PLAUSIBLE_MAX_AMOUNT:
            continue
        return PriceQuote(
            source=PriceSource.SMYTH_TOYS,
            amount=amount,
            currency=parse_currency(price_text),
            source_url=_source_url(product.get("url")),
            fetched_at=datetime.now(UTC),
        )
    return None


async def fetch_price(lego_set: LegoSet) -> PriceQuote | None:
    digits = set_digits(lego_set.set_num)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                _API_ENDPOINT,
                params={"text": digits},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ScrapeError(f"Catalogue Smyths Toys indisponible : {error}") from error
    return _quote_from_payload(payload, digits)
