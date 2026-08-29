"""Generic extractor for marketplace search pages.

Every source still keeps its own module for URL and source key, but the extraction logic is shared:
find a product card mentioning LEGO and the set number, reject common accessories/used offers, then
read one price string and parse it as EUR.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..pricing import PriceQuote, PriceSource
from ..rebrickable import LegoSet
from .browser import ScrapeNotFound, load_and_extract, parse_amount, parse_currency

PLAUSIBLE_MAX_AMOUNT = 5000.0

_REJECT_PATTERN = (
    "compatible|pour lego|for lego|"
    "eclairage|éclairage|\\bled\\b|lighting|"
    "non inclus|not included|pas inclus|sans la|"
    "briksmax|vonado|lightailing|occasion|reconditionn"
)


def _readiness_js(card_selector: str, no_result_pattern: str | None) -> str:
    no_result = f"/{no_result_pattern}/i.test(text)" if no_result_pattern else "false"
    selector = json.dumps(card_selector)
    return f"""
(() => {{
  const text = document.body ? document.body.innerText : '';
  if ({no_result}) return true;
  return document.querySelectorAll({selector}).length > 0;
}})()
"""


def _extract_js(
    digits: str,
    card_selector: str,
    no_result_pattern: str | None,
    price_selector: str | None,
    link_selector: str | None,
    title_selector: str | None,
) -> str:
    no_result = f"/{no_result_pattern}/i.test(text)" if no_result_pattern else "false"
    selector = json.dumps(card_selector)
    preferred_price = json.dumps(price_selector)
    preferred_link = json.dumps(link_selector)
    preferred_title = json.dumps(title_selector)
    return f"""
(() => {{
  const text = document.body ? document.body.innerText : '';
  if ({no_result}) return null;
  const cards = Array.from(document.querySelectorAll({selector}));
  const reject = /{_REJECT_PATTERN}/i;
  const setRegex = new RegExp('(^|\\\\D){digits}(\\\\D|$)');
  const priceRegex = /\\d[\\d\\s.,]*\\d(?:[.,]\\d{{2}})\\s*(?:\\u20ac|EUR)/gi;
  for (const card of cards) {{
    const cardText = (card.textContent || '').replace(/\\s+/g, ' ').trim();
    const preferredTitleSelector = {preferred_title};
    const titleElement = preferredTitleSelector ? card.querySelector(preferredTitleSelector) : null;
    const productText = ((titleElement ? titleElement.textContent : cardText) || '')
      .replace(/\\s+/g, ' ').trim();
    if (!productText || !/lego/i.test(productText)) continue;
    if (!setRegex.test(productText)) continue;
    if (reject.test(productText)) continue;

    const preferredPriceSelector = {preferred_price};
    const priced = (preferredPriceSelector ? card.querySelector(preferredPriceSelector) : null)
      || card.querySelector('[itemprop="price"][content], [data-price], .price, [class*="price"]');
    let price = '';
    if (priced) {{
      price =
        (priced.getAttribute('content')
          || priced.getAttribute('data-price')
          || priced.textContent
          || '').trim();
    }}
    if (!price) {{
      const matches = cardText.match(priceRegex);
      if (!matches || !matches.length) continue;
      price = matches[matches.length - 1];
    }}
    const preferredLinkSelector = {preferred_link};
    const linkEl = (preferredLinkSelector ? card.querySelector(preferredLinkSelector) : null)
      || (card.matches('a[href]') ? card : card.querySelector('a[href]'));
    return JSON.stringify({{
      price,
      url: linkEl ? linkEl.href : null,
    }});
  }}
  return null;
}})()
"""


async def fetch_retail_price(
    *,
    lego_set: LegoSet,
    source: PriceSource,
    search_url: str,
    digits: str,
    card_selector: str,
    no_result_pattern: str | None = None,
    price_selector: str | None = None,
    link_selector: str | None = None,
    title_selector: str | None = None,
) -> PriceQuote | None:
    try:
        raw = await load_and_extract(
            search_url,
            readiness_js=_readiness_js(card_selector, no_result_pattern),
            extract_js=_extract_js(
                digits,
                card_selector,
                no_result_pattern,
                price_selector,
                link_selector,
                title_selector,
            ),
            retry_empty_extraction=True,
        )
    except ScrapeNotFound:
        return None

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None

    price_text = payload.get("price")
    amount = parse_amount(price_text) if isinstance(price_text, str) else None
    if amount is None or amount > PLAUSIBLE_MAX_AMOUNT:
        return None

    return PriceQuote(
        source=source,
        amount=amount,
        currency=parse_currency(price_text),
        source_url=payload.get("url"),
        fetched_at=datetime.now(UTC),
    )
