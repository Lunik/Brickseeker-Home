"""Tests for the price-resolution kernel.

The kernel is the one piece where a subtle porting error would be invisible in the UI and wrong
everywhere at once — a set's row, the collection total, the CSV export and the alert threshold all
read from these functions. Each test below pins a decision the iOS app made deliberately (and, in
several cases, reverted to once already), not merely "the code does what it does".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.pricing import (
    ListCondition,
    PriceQuote,
    PriceSource,
    StoreAvailability,
    ValuationBasis,
    base_set_num,
    best_amazon_or_cdiscount,
    best_deal,
    evaluate_deal,
    is_minifig,
    make_valuation,
    most_expensive_amazon_or_cdiscount,
    percent_vs_store,
    resolve_collection_price,
    resolve_collection_price_condition,
    resolve_minifig_price,
    resolve_new_price,
    resolve_wishlist_price,
    resolve_wishlist_price_condition,
)
from app.services.scraping.browser import parse_amount


def quote(source: PriceSource, amount: float, **kwargs: object) -> PriceQuote:
    return PriceQuote(source=source, amount=amount, fetched_at=datetime.now(UTC), **kwargs)  # type: ignore[arg-type]


AMAZON_30 = quote(PriceSource.AMAZON, 30.0)
CDISCOUNT_25 = quote(PriceSource.CDISCOUNT, 25.0)
BL_NEW_40 = quote(PriceSource.BRICKLINK_NEW, 40.0)
BL_USED_20 = quote(PriceSource.BRICKLINK_USED, 20.0)


class TestMarketplacePair:
    """Amazon and Cdiscount are one comparison point everywhere except the detail screen."""

    def test_buying_takes_the_cheaper(self) -> None:
        assert best_amazon_or_cdiscount([AMAZON_30, CDISCOUNT_25]) == 25.0

    def test_valuing_takes_the_pricier(self) -> None:
        # The collection's total must not dip because one marketplace was cheaper that day.
        assert most_expensive_amazon_or_cdiscount([AMAZON_30, CDISCOUNT_25]) == 30.0

    def test_a_lone_quote_is_used_whichever_side_it_is(self) -> None:
        assert best_amazon_or_cdiscount([AMAZON_30]) == 30.0
        assert best_amazon_or_cdiscount([CDISCOUNT_25]) == 25.0
        assert best_amazon_or_cdiscount([BL_NEW_40]) is None


class TestNewPriceChain:
    def test_retail_wins_when_available(self) -> None:
        assert resolve_new_price(50.0, StoreAvailability.AVAILABLE, [AMAZON_30, BL_NEW_40]) == 50.0

    def test_retired_skips_retail_to_the_market(self) -> None:
        # lego.com keeps serving a residual price for sets it no longer sells; reporting that as
        # the set's price is what issue #243 fixed.
        assert resolve_new_price(50.0, StoreAvailability.RETIRED, [AMAZON_30, CDISCOUNT_25]) == 25.0

    @pytest.mark.parametrize(
        "availability", [StoreAvailability.OUT_OF_STOCK, StoreAvailability.UNKNOWN]
    )
    def test_a_stockout_or_unchecked_status_still_trusts_retail(
        self, availability: StoreAvailability
    ) -> None:
        assert resolve_new_price(50.0, availability, [AMAZON_30]) == 50.0

    def test_falls_through_to_bricklink_new(self) -> None:
        assert resolve_new_price(None, StoreAvailability.UNKNOWN, [BL_NEW_40]) == 40.0

    def test_never_returns_a_used_price(self) -> None:
        assert resolve_new_price(None, StoreAvailability.UNKNOWN, [BL_USED_20]) is None


class TestCollectionPrice:
    def test_new_list_prefers_the_new_chain(self) -> None:
        price = resolve_collection_price(50.0, ListCondition.NEW, StoreAvailability.AVAILABLE, [BL_USED_20])
        assert price == 50.0

    def test_used_list_prefers_the_used_quote(self) -> None:
        price = resolve_collection_price(50.0, ListCondition.USED, StoreAvailability.AVAILABLE, [BL_USED_20])
        assert price == 20.0

    def test_used_list_falls_back_to_the_new_chain_as_a_last_resort(self) -> None:
        # #194 reversed the earlier "return nothing rather than value an occasion set off retail"
        # rule: dropping those sets both under-counted the collection and left the "complete the
        # missing prices" action looping on sets a re-fetch could never fix.
        price = resolve_collection_price(50.0, ListCondition.USED, StoreAvailability.AVAILABLE, [])
        assert price == 50.0

    def test_the_reported_condition_follows_the_cross_fallback(self) -> None:
        condition = resolve_collection_price_condition(
            50.0, ListCondition.USED, StoreAvailability.AVAILABLE, []
        )
        assert condition is ListCondition.NEW

    def test_valuation_uses_the_pricier_marketplace(self) -> None:
        price = resolve_collection_price(None, ListCondition.NEW, StoreAvailability.UNKNOWN, [AMAZON_30, CDISCOUNT_25])
        assert price == 30.0

    def test_no_source_at_all_is_none_not_zero(self) -> None:
        assert resolve_collection_price(None, ListCondition.NEW, StoreAvailability.UNKNOWN, []) is None


class TestWishlistPrice:
    def test_marketplaces_come_before_retail(self) -> None:
        # Deliberately reversed from the History chain, per the wishlist's own request (#109/#121).
        assert resolve_wishlist_price(50.0, [AMAZON_30]) == 30.0

    def test_falls_all_the_way_to_bricklink_used(self) -> None:
        assert resolve_wishlist_price(None, [BL_USED_20]) == 20.0

    def test_a_used_only_fallback_reports_itself_as_used(self) -> None:
        # A wishlist skews toward retired/hard-to-find sets, so this fallback is common and the
        # caption must not silently present a used price as new.
        assert resolve_wishlist_price_condition(None, [BL_USED_20]) is ListCondition.USED


class TestMinifigPrice:
    def test_defaults_to_used_when_no_condition_is_known(self) -> None:
        assert resolve_minifig_price(None, [BL_NEW_40, BL_USED_20]) == 20.0

    def test_new_condition_prefers_the_new_quote(self) -> None:
        assert resolve_minifig_price(ListCondition.NEW, [BL_NEW_40, BL_USED_20]) == 40.0

    def test_cross_falls_back_when_the_preferred_side_is_missing(self) -> None:
        assert resolve_minifig_price(ListCondition.USED, [BL_NEW_40]) == 40.0


class TestBestDeal:
    def test_prefers_the_biggest_new_discount(self) -> None:
        deal = best_deal(100.0, [AMAZON_30, CDISCOUNT_25, BL_NEW_40])
        assert deal is not None
        assert deal.source is PriceSource.CDISCOUNT
        assert deal.percent == -75

    def test_used_is_only_a_last_resort(self) -> None:
        deal = best_deal(100.0, [AMAZON_30, BL_USED_20])
        assert deal is not None
        assert deal.source is PriceSource.AMAZON
        assert deal.percent == -70

    def test_falls_back_to_used_when_no_new_comparison_exists(self) -> None:
        deal = best_deal(100.0, [BL_USED_20])
        assert deal is not None
        assert deal.source is PriceSource.BRICKLINK_USED
        assert deal.percent == -80

    def test_returns_none_without_a_retail_reference(self) -> None:
        assert best_deal(None, [AMAZON_30]) is None


class TestValuation:
    def test_paid_price_is_the_reference_when_recorded(self) -> None:
        valuation = make_valuation("10307-1", 100.0, 80.0, ListCondition.NEW, [], availability=StoreAvailability.AVAILABLE)
        assert valuation.basis is ValuationBasis.PAID
        assert valuation.growth_percent == pytest.approx(25.0)

    def test_retail_is_the_sole_default_reference(self) -> None:
        valuation = make_valuation("10307-1", 100.0, None, ListCondition.NEW, [], availability=StoreAvailability.AVAILABLE)
        assert valuation.basis is ValuationBasis.RETAIL
        # Worth exactly what it lists for reads as a neutral 0 %, not "unavailable".
        assert valuation.growth_percent == pytest.approx(0.0)

    def test_a_marketplace_quote_is_never_promoted_to_reference(self) -> None:
        # Those say what the set is worth *now*, not what it cost — using one would compare two
        # market readings instead of measuring a gain.
        valuation = make_valuation("10307-1", None, None, ListCondition.NEW, [AMAZON_30])
        assert valuation.basis is ValuationBasis.UNKNOWN
        assert valuation.growth_percent is None
        assert valuation.current_value_eur == 30.0

    def test_a_minifig_has_no_default_reference(self) -> None:
        valuation = make_valuation("fig-000123", None, None, None, [BL_USED_20])
        assert valuation.current_value_eur == 20.0
        assert valuation.basis is ValuationBasis.UNKNOWN

    def test_a_retired_set_keeps_retail_as_its_growth_reference(self) -> None:
        valuation = make_valuation(
            "21335-1", 299.99, None, ListCondition.NEW, [AMAZON_30], availability=StoreAvailability.RETIRED
        )
        assert valuation.current_value_eur == 30.0  # retail gated out of the *value*
        assert valuation.basis_eur == 299.99  # but not out of the *reference*
        assert valuation.growth_percent == pytest.approx((30.0 - 299.99) / 299.99 * 100)

    def test_as_of_tracks_the_quote_that_actually_won(self) -> None:
        stamp = datetime.now(UTC) - timedelta(days=3)
        winning = PriceQuote(source=PriceSource.AMAZON, amount=30.0, fetched_at=stamp)
        valuation = make_valuation("10307-1", None, None, ListCondition.NEW, [winning])
        assert valuation.as_of == stamp
        assert valuation.is_stale is False


class TestThinSample:
    def test_two_lots_or_fewer_is_thin(self) -> None:
        assert PriceQuote(PriceSource.BRICKLINK_USED, 196.27, lot_count=1).is_thin_sample is True

    def test_a_source_with_no_sample_size_is_not_thin(self) -> None:
        # Every non-BrickLink source quotes one listing rather than an average over sales, so it
        # has no sample size to be small in the first place.
        assert PriceQuote(PriceSource.AMAZON, 30.0, lot_count=None).is_thin_sample is False

    def test_zero_lots_is_not_thin(self) -> None:
        assert PriceQuote(PriceSource.BRICKLINK_NEW, 40.0, lot_count=0).is_thin_sample is False


class TestDealVerdict:
    def test_cheaper_than_every_reference_is_a_good_deal(self) -> None:
        result = evaluate_deal(20.0, 50.0, "EUR", [BL_NEW_40])
        assert result is not None and result.verdict.value == "good"

    def test_dearer_than_every_reference_is_a_bad_one(self) -> None:
        result = evaluate_deal(60.0, 50.0, "EUR", [BL_NEW_40])
        assert result is not None and result.verdict.value == "bad"

    def test_mixed_references_are_merely_fair(self) -> None:
        result = evaluate_deal(45.0, 50.0, "EUR", [BL_NEW_40])
        assert result is not None and result.verdict.value == "fair"

    def test_cdiscount_is_included_in_the_verdict(self) -> None:
        result = evaluate_deal(20.0, None, None, [CDISCOUNT_25])
        assert result is not None
        assert result.verdict.value == "good"
        assert [comparison.label for comparison in result.comparisons] == ["Cdiscount (neuf)"]

    def test_no_reference_at_all_yields_no_verdict(self) -> None:
        assert evaluate_deal(45.0, None, None, []) is None

    def test_a_foreign_currency_reference_is_left_out_rather_than_compared(self) -> None:
        usd = PriceQuote(PriceSource.BRICKLINK_NEW, 40.0, currency="USD")
        assert evaluate_deal(45.0, None, None, [usd]) is None


class TestHelpers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("71045-3", "71045"), ("10307-1", "10307"), ("fig-000123", "fig-000123"), ("AUTOSHOW-1", "AUTOSHOW")],
    )
    def test_base_set_num(self, value: str, expected: str) -> None:
        assert base_set_num(value) == expected

    def test_minifig_ids_survive_suffix_stripping(self) -> None:
        # Splitting one would leave just "fig" (#123).
        assert is_minifig("fig-000123")
        assert not is_minifig("10307-1")

    def test_percent_vs_store_rounds_and_keeps_zero(self) -> None:
        assert percent_vs_store(45.0, "EUR", 50.0, "EUR") == -10
        assert percent_vs_store(50.0, "EUR", 50.0, "EUR") == 0

    def test_percent_vs_store_refuses_a_cross_currency_comparison(self) -> None:
        assert percent_vs_store(45.0, "USD", 50.0, "EUR") is None


class TestStoreAvailability:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("in stock", StoreAvailability.AVAILABLE),
            ("out of stock", StoreAvailability.OUT_OF_STOCK),
            ("retired", StoreAvailability.RETIRED),
            ("something else", StoreAvailability.UNKNOWN),
            (None, StoreAvailability.UNKNOWN),
        ],
    )
    def test_only_the_three_observed_strings_map(self, raw: str | None, expected: StoreAvailability) -> None:
        assert StoreAvailability.from_raw(raw) is expected


class TestParseAmount:
    """Every quote the four resolution chains above see starts as a scraped string — a wrong
    separator here is wrong for every downstream decision at once, the same failure mode the
    module docstring warns about."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("EUR 22.50", 22.50),
            ("€22,50", 22.50),
            ("1 174,00 €", 1174.0),  # French: space thousands, comma decimal
            ("1.174,00 €", 1174.0),  # German/Cdiscount: dot thousands, comma decimal
            ("$1,174.00", 1174.0),  # US: comma thousands, dot decimal
            ("129,99 €", 129.99),
            ("1234.56", 1234.56),  # no thousands separator at all
            ("1 174 €", 1174.0),  # thousands, no decimal part
        ],
    )
    def test_handles_every_separator_convention(self, raw: str, expected: float) -> None:
        assert parse_amount(raw) == pytest.approx(expected)

    def test_returns_none_without_a_number(self) -> None:
        assert parse_amount("Indisponible") is None
