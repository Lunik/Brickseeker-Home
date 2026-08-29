"""Amazon.fr price, read off a search results page.

Amazon has no per-product URL keyed by LEGO set number, so this searches `LEGO {digits}` and reads
the price off the first card that looks like the genuine set. It is the least reliable source in
the app — Amazon's bot detection is the most aggressive — and any failure here simply omits the
Amazon quote rather than blocking the others.

The acceptance filter is the load-bearing part and must not be loosened: without it, a third-party
LED kit titled "compatible avec 10294" was matched as the set itself. A card qualifies only when
the title is brand-first (`^LEGO`), contains the set number, and is not an accessory.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .browser import ScrapeNotFound, load_and_extract, parse_amount, parse_currency

#: Also matches the CAPTCHA interstitial so a challenged page resolves immediately as "no quote"
#: instead of polling until the timeout.
_READINESS_JS = """
(() => {
  const text = document.body ? document.body.innerText : '';
  if (/Enter the characters|Saisissez les caract\\u00e8res/i.test(text)) return true;
  return document.querySelectorAll('[data-component-type="s-search-result"]').length > 0;
})()
"""


def _extract_js(digits: str) -> str:
    return f"""
(() => {{
  const text = document.body ? document.body.innerText : '';
  if (/Enter the characters|Saisissez les caract\\u00e8res/i.test(text)) return null;
  const cards = Array.from(document.querySelectorAll('[data-component-type="s-search-result"]'));
  // Third-party accessories that merely reference a set number — most often LED lighting kits
  // "compatible avec"/"pour LEGO", which never include the set itself.
  const reject = /compatible|pour lego|for lego|\\u00e9clairage|eclairage|\\bled\\b|lighting|non inclus|not included|pas inclus|sans la|briksmax|vonado|lightailing/i;
  for (const card of cards) {{
    const titleEl = card.querySelector('h2');
    const title = (titleEl ? titleEl.textContent : '').trim();
    if (!/^lego\\b/i.test(title)) continue;
    if (title.indexOf('{digits}') === -1) continue;
    if (reject.test(title)) continue;
    const priceEl = card.querySelector('.a-price .a-offscreen');
    if (!priceEl) continue;
    const linkEl = card.querySelector('h2 a') || card.querySelector('a.a-link-normal');
    return JSON.stringify({{
      price: priceEl.textContent.trim(),
      url: linkEl ? linkEl.href : null
    }});
  }}
  return null;
}})()
"""


async def fetch_price(lego_set: LegoSet) -> PriceQuote | None:
    digits = set_digits(lego_set.set_num)
    url = f"https://www.amazon.fr/s?k=LEGO+{digits}"

    try:
        raw = await load_and_extract(url, readiness_js=_READINESS_JS, extract_js=_extract_js(digits))
    except ScrapeNotFound:
        return None

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None

    price_text = payload.get("price")
    amount = parse_amount(price_text) if price_text else None
    if amount is None:
        return None

    return PriceQuote(
        source=PriceSource.AMAZON,
        amount=amount,
        currency=parse_currency(price_text),
        source_url=payload.get("url"),
        fetched_at=datetime.now(UTC),
    )
