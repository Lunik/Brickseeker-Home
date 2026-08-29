"""Resolve an exact retailer product through its official sitemap, then read its structured price.

Some Proximis storefronts expose reliable product sitemaps but silently ignore query parameters on
their rendered search page. Downloading those sitemaps once per process is cheaper and more precise
than pretending an empty search page means the retailer has no offer.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from html import unescape
from urllib.parse import urlparse

import httpx

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .browser import ScrapeError, ScrapeNotFound, load_and_extract, parse_amount

_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_CACHE_TTL_SECONDS = 24 * 60 * 60
_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
_PRODUCT_SITEMAP_MARKER = "Rbs_Catalog_Product."
_catalog_cache: dict[str, tuple[float, tuple[str, ...]]] = {}
_catalog_lock = asyncio.Lock()


def _locations(payload: str) -> list[str]:
    return [unescape(match.group(1).strip()) for match in _LOC_RE.finditer(payload)]


def _contains_set_number(url: str, digits: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", url) is not None


async def _read_text(client: httpx.AsyncClient, url: str) -> str:
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ScrapeError(f"Sitemap marchand indisponible : {url} ({error})") from error
    return response.text


async def _product_urls(index_url: str, expected_host: str) -> tuple[str, ...]:
    now = time.monotonic()
    cached = _catalog_cache.get(index_url)
    if cached is not None and cached[0] > now:
        return cached[1]

    async with _catalog_lock:
        cached = _catalog_cache.get(index_url)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"Accept-Encoding": "gzip"},
        ) as client:
            index = await _read_text(client, index_url)
            sitemap_urls = [
                url for url in _locations(index) if _PRODUCT_SITEMAP_MARKER in url
            ]
            product_urls: list[str] = []
            for sitemap_url in sitemap_urls:
                payload = await _read_text(client, sitemap_url)
                product_urls.extend(
                    url
                    for url in _locations(payload)
                    if urlparse(url).hostname == expected_host and "lego" in url.lower()
                )

        resolved = tuple(dict.fromkeys(product_urls))
        _catalog_cache[index_url] = (
            time.monotonic() + _CACHE_TTL_SECONDS,
            resolved,
        )
        return resolved


def _readiness_js(digits: str) -> str:
    encoded = json.dumps(digits)
    return f"""
(() => {{
  const text = document.body ? document.body.innerText : '';
  if (!text.includes({encoded})) return false;
  if (document.querySelector('[itemprop="price"][content]')) return true;
  return Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
    .some((script) => (script.textContent || '').includes('"Product"'));
}})()
"""


def _extract_js(digits: str) -> str:
    encoded = json.dumps(digits)
    return f"""
(() => {{
  const text = document.body ? document.body.innerText : '';
  if (!text.includes({encoded})) return null;

  const priceMeta = document.querySelector('[itemprop="price"][content]');
  if (priceMeta) {{
    const currencyMeta = document.querySelector('[itemprop="priceCurrency"][content]');
    const availability = document.querySelector('[itemprop="availability"]');
    return JSON.stringify({{
      price: priceMeta.getAttribute('content'),
      currency: currencyMeta ? currencyMeta.getAttribute('content') : 'EUR',
      availability: availability
        ? (availability.getAttribute('content') || availability.getAttribute('href')
          || availability.textContent || '')
        : null,
      url: location.href
    }});
  }}

  const visit = (value) => {{
    if (!value || typeof value !== 'object') return null;
    if (Array.isArray(value)) {{
      for (const entry of value) {{
        const found = visit(entry);
        if (found) return found;
      }}
      return null;
    }}
    const types = Array.isArray(value['@type']) ? value['@type'] : [value['@type']];
    if (types.includes('Product')) {{
      const productText = `${{value.name || ''}} ${{value.url || ''}}`;
      if (productText.includes({encoded})) {{
        const offers = Array.isArray(value.offers) ? value.offers : [value.offers];
        const offer = offers.find((entry) => entry && (entry.price || entry.lowPrice));
        if (offer) {{
          return {{
            price: String(offer.price || offer.lowPrice),
            currency: offer.priceCurrency || 'EUR',
            availability: offer.availability || null,
            url: value.url || location.href
          }};
        }}
      }}
    }}
    for (const entry of Object.values(value)) {{
      const found = visit(entry);
      if (found) return found;
    }}
    return null;
  }};

  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {{
    try {{
      const found = visit(JSON.parse(script.textContent || 'null'));
      if (found) return JSON.stringify(found);
    }} catch (_) {{
      // Ignore one malformed analytics block; another JSON-LD block may hold the product.
    }}
  }}
  return null;
}})()
"""


async def fetch_sitemap_product_price(
    *,
    lego_set: LegoSet,
    source: PriceSource,
    sitemap_index_url: str,
    expected_host: str,
) -> PriceQuote | None:
    digits = set_digits(lego_set.set_num)
    urls = await _product_urls(sitemap_index_url, expected_host)
    product_url = next((url for url in urls if _contains_set_number(url, digits)), None)
    if product_url is None:
        return None

    try:
        raw = await load_and_extract(
            product_url,
            readiness_js=_readiness_js(digits),
            extract_js=_extract_js(digits),
        )
    except ScrapeNotFound:
        return None

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None

    amount = parse_amount(str(payload.get("price") or ""))
    if amount is None or amount > 5000:
        return None
    availability = str(payload.get("availability") or "").lower()
    if any(status in availability for status in ("outofstock", "soldout", "discontinued")):
        return None
    return PriceQuote(
        source=source,
        amount=amount,
        currency=str(payload.get("currency") or "EUR"),
        source_url=str(payload.get("url") or product_url),
        fetched_at=datetime.now(UTC),
    )
