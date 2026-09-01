from __future__ import annotations

import pytest

from app.services.pricing import PriceSource
from app.services.scraping import smyth_toys
from app.services.scraping.browser import ScrapeError


def test_french_catalogue_returns_the_current_exact_set_price() -> None:
    payload = {
        "products": [
            {
                "code": "wrong",
                "name": "LEGO Marvel 176345 Accessoire",
                "prices": {"price": "9,99€"},
                "url": "/wrong",
            },
            {
                "code": "259088",
                "name": "LEGO Marvel 76345 Buste du Docteur Doom",
                "prices": {"price": "44,99€", "rrpPrice": "49,99€"},
                "url": (
                    "/jouets/lego/lego-marvel-super-heroes/"
                    "lego-marvel-76345-buste-du-docteur-doom/p/259088"
                ),
            },
        ]
    }

    quote = smyth_toys._quote_from_payload(payload, "76345")

    assert quote is not None
    assert quote.source is PriceSource.SMYTH_TOYS
    assert quote.amount == 44.99
    assert quote.currency == "EUR"
    assert quote.source_url == (
        "https://www.smythstoys.com/fr/fr-fr/jouets/lego/lego-marvel-super-heroes/"
        "lego-marvel-76345-buste-du-docteur-doom/p/259088"
    )


def test_catalogue_rejects_non_lego_products_and_invalid_prices() -> None:
    payload = {
        "products": [
            {
                "name": "Compatible avec LEGO 76345",
                "prices": {"price": "4,99€"},
                "url": "/accessory",
            },
            {
                "name": "LEGO Marvel 76345 Buste du Docteur Doom",
                "prices": {"price": "indisponible"},
                "url": "/product",
            },
        ]
    }

    assert smyth_toys._quote_from_payload(payload, "76345") is None


def test_malformed_catalogue_is_a_source_failure_not_a_false_miss() -> None:
    with pytest.raises(ScrapeError, match="Catalogue Smyths Toys invalide"):
        smyth_toys._quote_from_payload({"unexpected": []}, "76345")


def test_product_url_cannot_leave_the_smyths_host() -> None:
    assert smyth_toys._source_url("https://attacker.test/product") is None
