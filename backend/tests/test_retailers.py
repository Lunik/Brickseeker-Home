from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.rebrickable import LegoSet
from app.services.scraping import joueclub, king_jouet, la_grande_recre

SET = LegoSet("11512-1", "Golden Pothos", 2026, 1, 0, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "expected_url"),
    [
        (
            la_grande_recre,
            "https://www.lagranderecre.fr/"
            "resultat-d-une-recherche-produits.html?searchText=11512",
        ),
        (
            joueclub,
            "https://www.joueclub.fr/contenu/"
            "resultat-de-recherche-produits.html?searchText=11512",
        ),
    ],
)
async def test_proximis_search_fallback_uses_exact_number(
    module, expected_url: str
) -> None:
    search = AsyncMock(return_value=None)
    with (
        patch.object(
            module,
            "fetch_sitemap_product_price",
            new=AsyncMock(return_value=None),
        ),
        patch.object(module, "fetch_retail_price", new=search),
    ):
        await module.fetch_price(SET)

    assert search.await_args.kwargs["search_url"] == expected_url
    assert search.await_args.kwargs["price_selector"] == (
        ".price-with-taxes .price-value"
    )


@pytest.mark.asyncio
async def test_king_jouet_uses_current_search_route_and_price_selector() -> None:
    search = AsyncMock(return_value=None)
    with patch.object(king_jouet, "fetch_retail_price", new=search):
        await king_jouet.fetch_price(SET)

    assert search.await_args.kwargs["search_url"] == (
        "https://www.king-jouet.com/jeux-jouets/page1.htm?search=11512"
    )
    assert search.await_args.kwargs["price_selector"] == ".font-bold.text-primary"
