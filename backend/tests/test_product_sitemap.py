from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.pricing import PriceSource
from app.services.rebrickable import LegoSet
from app.services.scraping import cultura, product_sitemap


def test_locations_decodes_xml_and_exact_set_number_does_not_match_ean() -> None:
    payload = """
    <urlset>
      <url><loc>https://example.test/lego-76924-car-5702017583976.html?a=1&amp;b=2</loc></url>
    </urlset>
    """

    assert product_sitemap._locations(payload) == [
        "https://example.test/lego-76924-car-5702017583976.html?a=1&b=2"
    ]
    assert product_sitemap._contains_set_number(payload, "76924") is True
    assert product_sitemap._contains_set_number(payload, "75839") is False


@pytest.mark.asyncio
async def test_product_catalog_keeps_only_lego_urls_on_expected_host() -> None:
    index_url = "https://example.test/sitemap-index.xml"
    product_sitemap._catalog_cache.clear()
    with patch.object(
        product_sitemap,
        "_read_text",
        new=AsyncMock(
            side_effect=[
                """
                <sitemapindex>
                  <sitemap><loc>https://example.test/Rbs_Catalog_Product.1.xml</loc></sitemap>
                  <sitemap><loc>https://example.test/Rbs_Brand_Brand.1.xml</loc></sitemap>
                </sitemapindex>
                """,
                """
                <urlset>
                  <url><loc>https://example.test/toys/lego-city-60400.html</loc></url>
                  <url><loc>https://example.test/toys/other-60400.html</loc></url>
                  <url><loc>https://attacker.test/toys/lego-city-60400.html</loc></url>
                </urlset>
                """,
            ]
        ),
    ):
        urls = await product_sitemap._product_urls(index_url, "example.test")

    assert urls == ("https://example.test/toys/lego-city-60400.html",)


@pytest.mark.asyncio
async def test_fetch_sitemap_product_price_reads_exact_product() -> None:
    lego_set = LegoSet("76924-1", "Mercedes-AMG", 2024, 1, 808, None, None)
    product_url = "https://example.test/lego-speed-champions-76924-car.html"

    with (
        patch.object(
            product_sitemap,
            "_product_urls",
            new=AsyncMock(return_value=(product_url,)),
        ),
        patch.object(
            product_sitemap,
            "load_and_extract",
            new=AsyncMock(
                return_value=(
                    '{"price":"49.99","currency":"EUR",'
                    '"url":"https://example.test/lego-speed-champions-76924-car.html"}'
                )
            ),
        ),
    ):
        quote = await product_sitemap.fetch_sitemap_product_price(
            lego_set=lego_set,
            source=PriceSource.JOUECLUB,
            sitemap_index_url="https://example.test/sitemap-index.xml",
            expected_host="example.test",
        )

    assert quote is not None
    assert quote.amount == 49.99
    assert quote.source is PriceSource.JOUECLUB
    assert quote.source_url == product_url


def test_cultura_graphql_matches_exact_set_number_and_final_price() -> None:
    payload = {
        "data": {
            "products": {
                "items": [
                    {
                        "name": "Un accessoire pour 1769240",
                        "url_key": "wrong",
                        "price_range": {
                            "minimum_price": {
                                "final_price": {"value": 9.99, "currency": "EUR"}
                            }
                        },
                    },
                    {
                        "name": "LEGO 76924 Mercedes-AMG",
                        "url_key": "tbd-sc-6-2024-10555973",
                        "price_range": {
                            "minimum_price": {
                                "final_price": {"value": 49.99, "currency": "EUR"}
                            }
                        },
                    },
                ]
            }
        }
    }

    quote = cultura._quote_from_payload(payload, "76924")

    assert quote is not None
    assert quote.amount == 49.99
    assert quote.source is PriceSource.CULTURA
    assert quote.source_url == "https://www.cultura.com/p-tbd-sc-6-2024-10555973.html"
