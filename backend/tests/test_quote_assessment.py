"""The cases come from a real collection, where these quotes are what lego prices actually look like."""

from __future__ import annotations

from app.models import CachedSet
from app.services import collection_repo
from app.services.pricing import PriceQuote, PriceSource
from app.services.quote_assessment import (
    QuoteEvidence,
    QuoteReason,
    QuoteVerdict,
    UserDecision,
    assess_quotes,
    is_other_product,
    rests_on_suspect,
    usable_quotes,
)
from app.services.scraping import cdiscount, retail_search

NEW = PriceSource.BRICKLINK_NEW
USED = PriceSource.BRICKLINK_USED
AMAZON = PriceSource.AMAZON
CDISCOUNT = PriceSource.CDISCOUNT
CULTURA = PriceSource.CULTURA


def quote(source: PriceSource, amount: float, lots: int | None = None) -> PriceQuote:
    return PriceQuote(source=source, amount=amount, lot_count=lots)


def verdicts(set_num, quotes, evidence=None):
    return {
        item.quote.source: (item.verdict, item.reason) for item in assess_quotes(set_num, quotes, evidence)
    }


TRUSTED = (QuoteVerdict.TRUSTED, None)


class TestVariant:
    def test_retail_rejected_for_one_figure_of_a_series(self):
        result = verdicts("71049-5", [quote(NEW, 3.09, 8), quote(AMAZON, 63.9)])
        assert result[AMAZON] == (QuoteVerdict.REJECTED, QuoteReason.SERIES_VARIANT)
        assert result[NEW] == TRUSTED

    def test_sealed_bag_suffix_is_not_a_variant(self):
        assert verdicts("71038-0", [quote(AMAZON, 4.0)])[AMAZON] == TRUSTED


class TestMarketReference:
    def test_keyring_far_below_market_is_rejected(self):
        result = verdicts("7665-1", [quote(NEW, 537.68, 5), quote(CULTURA, 45.37)])
        assert result[CULTURA] == (QuoteVerdict.REJECTED, QuoteReason.FAR_BELOW_MARKET)

    def test_reseller_far_above_market_is_suspect(self):
        result = verdicts("40639-1", [quote(NEW, 10.6, 20), quote(AMAZON, 138.95)])
        assert result[AMAZON] == (QuoteVerdict.SUSPECT, QuoteReason.FAR_ABOVE_MARKET)

    def test_ordinary_premium_on_a_retired_set_stands(self):
        assert verdicts("42141-1", [quote(NEW, 131.0, 9), quote(AMAZON, 200.0)])[AMAZON] == TRUSTED

    def test_median_of_sales_resists_one_atypical_sale(self):
        evidence = QuoteEvidence(sales={NEW.value: [10.0, 11.0, 12.0, 900.0]})
        result = verdicts("1000-1", [quote(NEW, 233.0, 4), quote(AMAZON, 12.0)], evidence)
        assert result[AMAZON] == TRUSTED

    def test_thin_bricklink_is_no_reference(self):
        assert verdicts("8017-1", [quote(NEW, 205.0, 1), quote(CULTURA, 80.0)])[CULTURA] == TRUSTED

    def test_thin_bricklink_far_from_used_is_suspect(self):
        result = verdicts("8017-1", [quote(NEW, 205.0, 1), quote(USED, 41.84, 11)])
        assert result[NEW] == (QuoteVerdict.SUSPECT, QuoteReason.THIN_MARKET)

    def test_retailers_agree_without_a_market_price(self):
        quotes = [
            quote(AMAZON, 50.0),
            quote(CDISCOUNT, 55.0),
            quote(PriceSource.KING_JOUET, 52.0),
            quote(CULTURA, 4.0),
        ]
        assert verdicts("1000-1", quotes)[CULTURA][1] is QuoteReason.FAR_BELOW_MARKET

    def test_two_retailers_are_no_consensus(self):
        assert verdicts("1000-1", [quote(AMAZON, 50.0), quote(CULTURA, 4.0)])[CULTURA] == TRUSTED

    def test_used_price_is_a_floor_not_a_ceiling(self):
        result = verdicts("1000-1", [quote(USED, 20.0, 9), quote(AMAZON, 200.0)])
        assert result[AMAZON] == TRUSTED


class TestPriceJump:
    def test_jump_is_held(self):
        evidence = QuoteEvidence(history={AMAZON.value: [23.0, 23.0, 138.95]})
        result = verdicts("1000-1", [quote(AMAZON, 138.95)], evidence)
        assert result[AMAZON] == (QuoteVerdict.SUSPECT, QuoteReason.PRICE_JUMP)

    def test_drop_is_held_too(self):
        evidence = QuoteEvidence(history={AMAZON.value: [100.0, 100.0, 100.0, 28.0]})
        assert verdicts("1000-1", [quote(AMAZON, 28.0)], evidence)[AMAZON][1] is QuoteReason.PRICE_JUMP

    def test_second_reading_confirms(self):
        evidence = QuoteEvidence(history={AMAZON.value: [23.0, 23.0, 138.95, 140.0]})
        assert verdicts("1000-1", [quote(AMAZON, 140.0)], evidence)[AMAZON] == TRUSTED

    def test_too_little_history_says_nothing(self):
        evidence = QuoteEvidence(history={AMAZON.value: [23.0, 138.95]})
        assert verdicts("1000-1", [quote(AMAZON, 138.95)], evidence)[AMAZON] == TRUSTED

    def test_ordinary_move_is_not_a_jump(self):
        evidence = QuoteEvidence(history={AMAZON.value: [40.0, 40.0, 60.0]})
        assert verdicts("1000-1", [quote(AMAZON, 60.0)], evidence)[AMAZON] == TRUSTED


class TestUsableQuotes:
    def test_suspect_skipped_when_a_trusted_quote_of_the_same_condition_exists(self):
        new, amazon = quote(NEW, 10.0, 20), quote(AMAZON, 138.95)
        assert usable_quotes(assess_quotes("1000-1", [new, amazon])) == [new]

    def test_rejected_is_never_read(self):
        assert usable_quotes(assess_quotes("71049-5", [quote(AMAZON, 63.9)])) == []

    def test_doubtful_new_price_is_not_replaced_by_a_used_one(self):
        new, used = quote(NEW, 100.0, 1), quote(USED, 23.86, 9)
        assessed = assess_quotes("70500-1", [new, used])
        assert usable_quotes(assessed) == [new, used]
        assert rests_on_suspect(assessed, 100.0)
        assert not rests_on_suspect(assessed, 23.86)

    def test_suspect_serves_alone_and_is_reported(self):
        amazon = quote(AMAZON, 138.95)
        evidence = QuoteEvidence(history={AMAZON.value: [23.0, 23.0, 138.95]})
        assessed = assess_quotes("1000-1", [amazon], evidence)
        assert usable_quotes(assessed) == [amazon]
        assert rests_on_suspect(assessed, 138.95)

    def test_trusted_value_is_not_reported(self):
        assert not rests_on_suspect(assess_quotes("1000-1", [quote(AMAZON, 40.0)]), 40.0)
        assert not rests_on_suspect(assess_quotes("1000-1", [quote(AMAZON, 40.0)]), None)


class TestTitle:
    def test_card_text_is_never_stored_as_a_title(self):
        assert "title" not in cdiscount._extract_js("10307")
        js = retail_search._extract_js("10307", ".card", None, None, None, ".title")
        assert "title: titleElement ? productText : null" in js

    def test_other_product_words(self):
        assert is_other_product("Porte-clés LEGO Ninjago Kai")
        assert is_other_product("LEGO Minifigures : boîte de 36 sachets")
        assert not is_other_product("LEGO 42141 Technic McLaren Formula 1")

    def test_a_real_set_named_box_of_something_is_spared(self):
        assert not is_other_product("LEGO 11016 Boîte de briques créatives")

    def test_word_inside_another_is_not_matched(self):
        assert not is_other_product("LEGO Facebook Tower")

    def test_set_really_named_so_is_spared(self):
        assert not is_other_product("LEGO 21315 Pop-Up Book", "Pop-Up Book")

    def test_title_rejects_before_any_price_check(self):
        evidence = QuoteEvidence(titles={AMAZON.value: "Porte-clés LEGO 10307"})
        result = verdicts("10307-1", [quote(NEW, 12.0, 9), quote(AMAZON, 12.0)], evidence)
        assert result[AMAZON] == (QuoteVerdict.REJECTED, QuoteReason.OTHER_PRODUCT)

    def test_a_clean_title_only_softens_a_low_price_to_suspect(self):
        evidence = QuoteEvidence(titles={CULTURA.value: "LEGO 7665 Republic Cruiser"})
        result = verdicts("7665-1", [quote(NEW, 537.68, 5), quote(CULTURA, 45.37)], evidence)
        assert result[CULTURA] == (QuoteVerdict.SUSPECT, QuoteReason.FAR_BELOW_MARKET)


class TestUserDecision:
    def test_overrules_every_automatic_verdict(self):
        decisions = {AMAZON.value: UserDecision(QuoteVerdict.TRUSTED, 63.9)}
        result = verdicts("71049-5", [quote(AMAZON, 63.9)], QuoteEvidence(decisions=decisions))
        assert result[AMAZON] == (QuoteVerdict.TRUSTED, QuoteReason.USER_CONFIRMED)

    def test_can_reject_what_looked_fine(self):
        decisions = {AMAZON.value: UserDecision(QuoteVerdict.REJECTED, 40.0)}
        result = verdicts("1000-1", [quote(AMAZON, 42.0)], QuoteEvidence(decisions=decisions))
        assert result[AMAZON] == (QuoteVerdict.REJECTED, QuoteReason.USER_REJECTED)

    def test_lapses_once_the_price_is_another_offer(self):
        decisions = {AMAZON.value: UserDecision(QuoteVerdict.REJECTED, 40.0)}
        evidence = QuoteEvidence(decisions=decisions)
        assert verdicts("1000-1", [quote(AMAZON, 80.0)], evidence)[AMAZON] == TRUSTED


class TestReadingTheCache:
    async def test_single_and_bulk_reads_agree(self, session):
        await collection_repo.cache_prices(session, [quote(NEW, 3.09, 8), quote(AMAZON, 63.9)], "71049-5")
        await collection_repo.cache_prices(session, [quote(NEW, 10.0, 8), quote(AMAZON, 12.0)], "1000-1")
        await session.commit()

        single = await collection_repo.cached_prices(session, "71049-5")
        assert [item.source for item in single] == [NEW]
        bulk = await collection_repo.all_cached_prices(session)
        assert [item.source for item in bulk["71049-5"]] == [NEW]
        assert {item.source for item in bulk["1000-1"]} == {NEW, AMAZON}

    async def test_title_survives_a_rebuilt_quote_and_goes_with_the_cache(self, session):
        keyring = PriceQuote(source=AMAZON, amount=12.0, title="Porte-clés LEGO 10307")
        await collection_repo.cache_prices(session, [keyring], "10307-1")
        await collection_repo.cache_prices(session, [quote(AMAZON, 12.0)], "10307-1")
        await session.commit()
        assessed = await collection_repo.assessed_prices(session, "10307-1")
        assert assessed[0].reason is QuoteReason.OTHER_PRODUCT
        assert (await collection_repo.all_assessed_prices(session))["10307-1"][0].title == keyring.title

        await collection_repo.clear_cache(session)
        await collection_repo.cache_prices(session, [quote(AMAZON, 12.0)], "10307-1")
        await session.commit()
        assert (await collection_repo.assessed_prices(session, "10307-1"))[0].title is None

    async def test_title_goes_when_the_retailer_stops_listing_it(self, session):
        keyring = PriceQuote(source=AMAZON, amount=12.0, title="Porte-clés LEGO 10307")
        await collection_repo.cache_prices(session, [keyring], "10307-1")
        await collection_repo.cache_prices(session, [], "10307-1", reconcile=True)
        await collection_repo.cache_prices(session, [quote(AMAZON, 12.0)], "10307-1")
        await session.commit()
        assert (await collection_repo.assessed_prices(session, "10307-1"))[0].title is None

    async def test_set_aside_quotes_stay_readable(self, session):
        await collection_repo.cache_prices(session, [quote(AMAZON, 63.9)], "71049-5")
        await session.commit()
        assessed = await collection_repo.assessed_prices(session, "71049-5")
        assert [item.reason for item in assessed] == [QuoteReason.SERIES_VARIANT]


class TestDecisionRoutes:
    async def test_decision_overrules_then_survives_the_cache_then_undoes(self, session, client):
        await collection_repo.cache_prices(session, [quote(AMAZON, 63.9)], "71049-5")
        await session.commit()

        body = (await client.get("/api/prices/71049-5")).json()
        assert body["quotes"] == []
        assert body["setAsideQuotes"][0]["reason"] == "seriesVariant"

        url = "/api/prices/71049-5/quotes/amazon/decision"
        response = await client.put(url, json={"verdict": "trusted"})
        assert response.status_code == 200
        assert response.json()["quotes"][0]["userDecided"] is True

        await collection_repo.clear_cache(session)
        await collection_repo.cache_prices(session, [quote(AMAZON, 64.0)], "71049-5")
        await session.commit()
        assert (await client.get("/api/prices/71049-5")).json()["quotes"][0]["reason"] == "userConfirmed"

        assert (await client.delete(url)).json()["quotes"] == []

    async def test_cannot_decide_on_a_price_that_is_gone(self, client):
        response = await client.put("/api/prices/1-1/quotes/amazon/decision", json={"verdict": "rejected"})
        assert response.status_code == 404

    async def test_suspect_verdict_is_not_for_the_user_to_give(self, session, client):
        await collection_repo.cache_prices(session, [quote(AMAZON, 10.0)], "1-1")
        await session.commit()
        response = await client.put("/api/prices/1-1/quotes/amazon/decision", json={"verdict": "suspect"})
        assert response.status_code == 422


class TestStats:
    async def test_value_resting_on_a_suspect_price_is_reported(self, session, client):
        session.add(CachedSet(set_num="70500-1", name="Kai's Fire Mech", is_in_collection=True, quantity=2))
        session.add(CachedSet(set_num="1000-1", name="Sure", is_in_collection=True))
        await session.commit()
        await collection_repo.cache_prices(session, [quote(NEW, 100.0, 1), quote(USED, 23.0, 9)], "70500-1")
        await collection_repo.cache_prices(session, [quote(NEW, 40.0, 9)], "1000-1")
        await session.commit()

        body = (await client.get("/api/stats")).json()
        assert body["totalValueEur"] == 240.0
        assert body["uncertainValueEur"] == 200.0
        assert body["uncertainSetCount"] == 1
