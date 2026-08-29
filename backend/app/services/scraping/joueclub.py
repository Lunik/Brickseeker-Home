"""JouéClub price resolved through its current official product sitemaps."""

from __future__ import annotations

from urllib.parse import quote_plus

from ..pricing import PriceQuote, PriceSource, set_digits
from ..rebrickable import LegoSet
from .product_sitemap import fetch_sitemap_product_price
from .retail_search import fetch_retail_price

_SITEMAP_INDEX = "https://www.joueclub.fr/Assets/Rbs/Seo/sitemap-index.xml"
_CARD_SELECTOR = (
    "li.product-item, [data-item-id], .product-carousel-item, "
    "[data-rbs-catalog-product-list-item-add-to-cart-buttons-v3]"
)
_NO_RESULT_PATTERN = "aucun\\s+r[ée]sultat|0\\s+r[ée]sultat|aucun\\s+produit"


async def fetch_price(lego_set: LegoSet) -> PriceQuote | None:
    quote = await fetch_sitemap_product_price(
        lego_set=lego_set,
        source=PriceSource.JOUECLUB,
        sitemap_index_url=_SITEMAP_INDEX,
        expected_host="www.joueclub.fr",
    )
    if quote is not None:
        return quote
    digits = set_digits(lego_set.set_num)
    query = quote_plus(digits)
    return await fetch_retail_price(
        lego_set=lego_set,
        source=PriceSource.JOUECLUB,
        search_url=(
            "https://www.joueclub.fr/contenu/"
            f"resultat-de-recherche-produits.html?searchText={query}"
        ),
        digits=digits,
        card_selector=_CARD_SELECTOR,
        no_result_pattern=_NO_RESULT_PATTERN,
        price_selector=".price-with-taxes .price-value",
        link_selector="a.product__title-card[href], a.product-item__link[href]",
        title_selector="a.product__title-card, .product-item__title",
    )
