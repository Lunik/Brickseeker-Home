"""La Grande Récré price resolved through its official product sitemap."""

from __future__ import annotations

from urllib.parse import quote_plus

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .product_sitemap import fetch_sitemap_product_price
from .retail_search import fetch_retail_price

_SITEMAP_INDEX = "https://www.lagranderecre.fr/Assets/Rbs/Seo/sitemap-index.xml"
_CARD_SELECTOR = ".thumbnail-product"
_NO_RESULT_PATTERN = "aucun\\s+r[ée]sultat|0\\s+r[ée]sultat|aucun\\s+produit"


async def fetch_price(lego_set: LegoSet) -> PriceQuote | None:
    quote = await fetch_sitemap_product_price(
        lego_set=lego_set,
        source=PriceSource.LA_GRANDE_RECRE,
        sitemap_index_url=_SITEMAP_INDEX,
        expected_host="www.lagranderecre.fr",
    )
    if quote is not None:
        return quote
    digits = set_digits(lego_set.set_num)
    query = quote_plus(digits)
    return await fetch_retail_price(
        lego_set=lego_set,
        source=PriceSource.LA_GRANDE_RECRE,
        search_url=(
            "https://www.lagranderecre.fr/"
            f"resultat-d-une-recherche-produits.html?searchText={query}"
        ),
        digits=digits,
        card_selector=_CARD_SELECTOR,
        no_result_pattern=_NO_RESULT_PATTERN,
        price_selector=".price-with-taxes .price-value",
        link_selector="a.product-name[href]",
        title_selector="a.product-name",
    )
