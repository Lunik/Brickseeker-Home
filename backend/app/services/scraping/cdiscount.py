"""Cdiscount price, same shape as the Amazon scraper.

Cdiscount sits behind its own JS bot challenge, and exposes no `data-component-type`-style test
hook for result cards — so this keys off the one stable thing its product pages share: a
`/f-<categoryId>-<sku>.html` URL segment, which wraps the whole card (title, rating, price).

Three failure modes were found only by running against the live site, and each fix must survive:

* `.innerText` reads back **empty** on this list's virtualised rows — a WebKit/Chromium quirk
  `.textContent` doesn't have.
* A promo card carries **two** prices back to back — crossed-out original, "-N%" badge, then the
  real one (`"239,99 €-8%219,99 €"`). Taking the first match silently returns the pre-discount
  price, so this takes the **last**.
* Title, reference and price share one flattened string with no delimiter, so the reference digits
  can sit directly against the price digits (`"...- 303685,99 €"` is `30368` + `5,99 €`). The regex
  cannot be tightened to reject that shape — Cdiscount doesn't consistently thousands-separate its
  own prices either (`"1174,00 €"`, four digits, no separator, confirmed live) — so the reference
  is **stripped from the text before** the price regex runs, with a plausibility ceiling as a
  backstop.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import quote_plus

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .browser import ScrapeNotFound, load_and_extract, parse_amount, parse_currency

#: No standard retail LEGO set costs this much. Above it, the extractor read something that isn't
#: a price — most often the set number bleeding into the digits.
PLAUSIBLE_MAX_AMOUNT = 5000.0

_READINESS_JS = """
(() => {
  const text = document.body ? document.body.innerText : '';
  if (/aucun r\\u00e9sultat/i.test(text)) return true;
  return document.querySelectorAll('a[href*="/f-"]').length > 0;
})()
"""


def _extract_js(digits: str) -> str:
    return f"""
(() => {{
  const text = document.body ? document.body.innerText : '';
  if (/aucun r\\u00e9sultat/i.test(text)) return null;
  const links = Array.from(document.querySelectorAll('a[href*="/f-"]'));
  // Amazon's accessory list plus occasion/reconditionné: Cdiscount's marketplace mixes used goods
  // into "neuf" results more than Amazon does.
  const reject = /compatible|pour lego|for lego|\\u00e9clairage|eclairage|\\bled\\b|lighting|non inclus|not included|pas inclus|sans la|briksmax|vonado|lightailing|occasion|reconditionn/i;
  const priceRegex = /\\d[\\d\\s]*,\\d{{2}}\\s*\\u20ac/g;
  for (const link of links) {{
    const cardText = (link.textContent || '').trim();
    if (cardText.toLowerCase().indexOf('lego') === -1) continue;
    if (cardText.indexOf('{digits}') === -1) continue;
    if (reject.test(cardText)) continue;
    const priceText = cardText.split('{digits}').join(' ');
    const matches = priceText.match(priceRegex);
    if (!matches || !matches.length) continue;
    return JSON.stringify({{ price: matches[matches.length - 1], url: link.href }});
  }}
  return null;
}})()
"""


async def fetch_price(lego_set: LegoSet) -> PriceQuote | None:
    digits = set_digits(lego_set.set_num)
    url = f"https://www.cdiscount.com/search/10/{quote_plus(f'LEGO {digits}')}.html"

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
    if amount is None or amount > PLAUSIBLE_MAX_AMOUNT:
        return None

    return PriceQuote(
        source=PriceSource.CDISCOUNT,
        amount=amount,
        currency=parse_currency(price_text),
        source_url=payload.get("url"),
        fetched_at=datetime.now(UTC),
    )
