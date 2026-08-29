"""King Jouet price from search results."""

from __future__ import annotations

from urllib.parse import quote_plus

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .retail_search import fetch_retail_price

_CARD_SELECTOR = (
    "[data-product-ref], [data-product-id], .product-card, .product-item, "
    "[itemprop*='Product']"
)
_NO_RESULT_PATTERN = "aucun\\s+r[ée]sultat|0\\s+r[ée]sultat"


async def fetch_price(lego_set: LegoSet) -> PriceQuote | None:
    digits = set_digits(lego_set.set_num)
    query = quote_plus(digits)
    url = f"https://www.king-jouet.com/jeux-jouets/page1.htm?search={query}"
    return await fetch_retail_price(
        lego_set=lego_set,
        source=PriceSource.KING_JOUET,
        search_url=url,
        digits=digits,
        card_selector=_CARD_SELECTOR,
        no_result_pattern=_NO_RESULT_PATTERN,
        price_selector=".font-bold.text-primary",
        link_selector="a.pci-link[href]",
        title_selector=".pci-title",
    )
