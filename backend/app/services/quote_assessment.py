"""Decides whether a cached quote can be believed. Pure, like `pricing.py`: no base, no network.

Retailers are searched by number alone, so a quote can be a whole series box, a keyring mentioning
the number, or a reseller's asking price. Every quote gets a verdict and a reason, and nothing is
deleted: the set sheet shows what was set aside and why, and the user can overrule it.

- `rejected`: not this product, or the user said so. Never used.
- `suspect`: probably real but not representative. Used only when the set has nothing better, and
  the value is then reported as uncertain.
- `trusted`: everything else.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import median

from .pricing import RETAIL_SOURCES, PriceQuote, PriceSource, is_set_variant

#: Under this share of the market a retail offer is another product: on a real 506-set collection
#: these quotes were 1 % to 8 % of what the set sells for, while genuine offers sit well above it.
MINIMUM_RATIO_TO_MARKET = 0.35
#: Above this multiple it is a reseller or a box. The median retail offer on retired sets is 2.1
#: times the market, so 3 only catches the real outliers.
MAXIMUM_RATIO_TO_MARKET = 3.0
#: A market price needs this many sales behind it: below, one atypical sale *is* the quote.
MINIMUM_SALES_FOR_MARKET = 3
#: Retailers agreeing with each other only mean something from three of them.
MINIMUM_RETAIL_FOR_CONSENSUS = 3
#: A price moving by this factor against its own past is held until a second reading confirms it.
JUMP_FACTOR = 2.0
#: Two readings this close count as the same price level.
SAME_LEVEL_TOLERANCE = 0.25
MINIMUM_READINGS_FOR_JUMP = 3
#: A user's verdict is about one offer. Once the price moves this much it is another offer.
DECISION_VALID_FACTOR = 2.0

#: What a retailer's title says when it is not selling one set. Set names are English and titles
#: French, so a positive match is impossible and only these negative words are looked for. A count
#: is required after "boîte de" and the like: "Boîte de briques créatives" is a real set.
_OTHER_PRODUCT = re.compile(
    r"(?<!\w)(?:porte[- ]cl(?:é|e|ef)s?|key ?chains?|key ?rings?|livres?|books?|magazines?|puzzles?"
    r"|montres?|réveils?|(?:boîte|boite|lot|pack)s? de \d+|s[ée]rie compl[èe]te"
    r"|collection compl[èe]te|complete set of)(?!\w)",
    re.IGNORECASE,
)


class QuoteVerdict(StrEnum):
    TRUSTED = "trusted"
    SUSPECT = "suspect"
    REJECTED = "rejected"


class QuoteReason(StrEnum):
    SERIES_VARIANT = "seriesVariant"
    OTHER_PRODUCT = "otherProduct"
    FAR_BELOW_MARKET = "farBelowMarket"
    FAR_ABOVE_MARKET = "farAboveMarket"
    THIN_MARKET = "thinMarket"
    PRICE_JUMP = "priceJump"
    USER_CONFIRMED = "userConfirmed"
    USER_REJECTED = "userRejected"

    @property
    def label(self) -> str:
        return {
            QuoteReason.SERIES_VARIANT: "Ce site vend la série entière, pas cette figurine",
            QuoteReason.OTHER_PRODUCT: "Le titre de l'offre désigne un autre produit",
            QuoteReason.FAR_BELOW_MARKET: "Très en dessous du marché",
            QuoteReason.FAR_ABOVE_MARKET: "Très au-dessus du marché",
            QuoteReason.THIN_MARKET: "Trop peu de ventes, et loin des autres prix",
            QuoteReason.PRICE_JUMP: "Saut de prix, en attente d'un second relevé",
            QuoteReason.USER_CONFIRMED: "Confirmé par vous",
            QuoteReason.USER_REJECTED: "Écarté par vous",
        }[self]


@dataclass(slots=True, frozen=True)
class UserDecision:
    verdict: QuoteVerdict
    amount: float

    def applies_to(self, amount: float) -> bool:
        if self.amount <= 0 or amount <= 0:
            return False
        return max(amount, self.amount) / min(amount, self.amount) < DECISION_VALID_FACTOR


@dataclass(slots=True, frozen=True)
class QuoteEvidence:
    """Everything known about a set's quotes besides the quotes, each mapping keyed by source."""

    set_name: str = ""
    sales: Mapping[str, Sequence[float]] = field(default_factory=dict)
    #: Oldest first.
    history: Mapping[str, Sequence[float]] = field(default_factory=dict)
    titles: Mapping[str, str] = field(default_factory=dict)
    decisions: Mapping[str, UserDecision] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AssessedQuote:
    quote: PriceQuote
    verdict: QuoteVerdict
    reason: QuoteReason | None = None
    title: str | None = None
    #: The user's verdict when it is the one applied, so the UI can offer to undo it.
    user_decided: bool = False


@dataclass(slots=True, frozen=True)
class _Reference:
    amount: float
    is_new_condition: bool


def _market_price(quote: PriceQuote | None, sales: Sequence[float]) -> float | None:
    """What the item really sells for: the median sale resists one atypical lot, unlike the average
    a BrickLink quote carries. `None` when too few sales support any figure."""
    if quote is None:
        return None
    if len(sales) >= MINIMUM_SALES_FOR_MARKET:
        return median(sales)
    if (quote.lot_count or 0) >= MINIMUM_SALES_FOR_MARKET:
        return quote.amount
    return None


def _reference(quotes: Sequence[PriceQuote], evidence: QuoteEvidence) -> _Reference | None:
    by_source = {quote.source: quote for quote in quotes}
    new = _market_price(
        by_source.get(PriceSource.BRICKLINK_NEW), evidence.sales.get(PriceSource.BRICKLINK_NEW.value, ())
    )
    if new is not None:
        return _Reference(new, is_new_condition=True)
    retail = [quote.amount for quote in quotes if quote.source in RETAIL_SOURCES]
    if len(retail) >= MINIMUM_RETAIL_FOR_CONSENSUS:
        return _Reference(median(retail), is_new_condition=True)
    used = _market_price(
        by_source.get(PriceSource.BRICKLINK_USED), evidence.sales.get(PriceSource.BRICKLINK_USED.value, ())
    )
    # Only a floor: a new set is rightly worth many times a used one, never much less.
    return _Reference(used, is_new_condition=False) if used is not None else None


def is_other_product(title: str, set_name: str = "") -> bool:
    """A set really called "Book" is not rejected for saying so."""
    own_name = set_name.casefold()
    return any(match.group().casefold() not in own_name for match in _OTHER_PRODUCT.finditer(title))


def _has_jumped(amount: float, readings: Sequence[float]) -> bool:
    if len(readings) < MINIMUM_READINGS_FOR_JUMP or amount <= 0:
        return False
    same_level = [value for value in readings if abs(value - amount) <= amount * SAME_LEVEL_TOLERANCE]
    if len(same_level) >= 2:
        return False
    previous = [value for value in readings if value not in same_level]
    if not previous:
        return False
    baseline = median(previous)
    return baseline > 0 and not 1 / JUMP_FACTOR < amount / baseline < JUMP_FACTOR


def _automatic(
    set_num: str,
    quote: PriceQuote,
    quotes: Sequence[PriceQuote],
    reference: _Reference | None,
    evidence: QuoteEvidence,
) -> tuple[QuoteVerdict, QuoteReason | None]:
    source = quote.source.value
    title = evidence.titles.get(source)

    if quote.source in RETAIL_SOURCES:
        if is_set_variant(set_num):
            return QuoteVerdict.REJECTED, QuoteReason.SERIES_VARIANT
        if title and is_other_product(title, evidence.set_name):
            return QuoteVerdict.REJECTED, QuoteReason.OTHER_PRODUCT
        if reference is not None:
            ratio = quote.amount / reference.amount
            if ratio < MINIMUM_RATIO_TO_MARKET:
                # A title that reads as the set is evidence the offer is real, only unusually cheap.
                verdict = QuoteVerdict.SUSPECT if title else QuoteVerdict.REJECTED
                return verdict, QuoteReason.FAR_BELOW_MARKET
            if reference.is_new_condition and ratio > MAXIMUM_RATIO_TO_MARKET:
                return QuoteVerdict.SUSPECT, QuoteReason.FAR_ABOVE_MARKET
    elif quote.is_thin_sample:
        others = _reference([other for other in quotes if other is not quote], evidence)
        if others is not None and quote.amount / others.amount > MAXIMUM_RATIO_TO_MARKET:
            return QuoteVerdict.SUSPECT, QuoteReason.THIN_MARKET

    if _has_jumped(quote.amount, evidence.history.get(source, ())):
        return QuoteVerdict.SUSPECT, QuoteReason.PRICE_JUMP
    return QuoteVerdict.TRUSTED, None


def assess_quotes(
    set_num: str, quotes: Iterable[PriceQuote], evidence: QuoteEvidence | None = None
) -> list[AssessedQuote]:
    known = evidence or QuoteEvidence()
    listed = list(quotes)
    reference = _reference(listed, known)
    assessed: list[AssessedQuote] = []
    for quote in listed:
        source = quote.source.value
        title = known.titles.get(source)
        decision = known.decisions.get(source)
        if decision is not None and decision.applies_to(quote.amount):
            reason = (
                QuoteReason.USER_CONFIRMED
                if decision.verdict is QuoteVerdict.TRUSTED
                else QuoteReason.USER_REJECTED
            )
            assessed.append(AssessedQuote(quote, decision.verdict, reason, title, user_decided=True))
            continue
        verdict, reason = _automatic(set_num, quote, listed, reference, known)
        assessed.append(AssessedQuote(quote, verdict, reason, title))
    return assessed


def _is_used_condition(quote: PriceQuote) -> bool:
    return quote.source is PriceSource.BRICKLINK_USED


def _fallback_suspects(assessed: Sequence[AssessedQuote]) -> list[AssessedQuote]:
    """Suspect quotes with no trusted quote of the same condition to replace them. A used price is
    no substitute for a doubtful new one: it would silently value a sealed set as an opened one."""
    trusted_conditions = {
        _is_used_condition(item.quote) for item in assessed if item.verdict is QuoteVerdict.TRUSTED
    }
    return [
        item
        for item in assessed
        if item.verdict is QuoteVerdict.SUSPECT and _is_used_condition(item.quote) not in trusted_conditions
    ]


def usable_quotes(assessed: Iterable[AssessedQuote]) -> list[PriceQuote]:
    """What the pricing chains may read. A suspect quote only serves when nothing better exists."""
    listed = list(assessed)
    fallbacks = {id(item) for item in _fallback_suspects(listed)}
    return [
        item.quote for item in listed if item.verdict is QuoteVerdict.TRUSTED or id(item) in fallbacks
    ]


def rests_on_suspect(assessed: Iterable[AssessedQuote], value: float | None) -> bool:
    """Whether a value resolved from `usable_quotes` is a suspect quote's amount. The chains return
    amounts untouched, so equality is exact."""
    return any(item.quote.amount == value for item in _fallback_suspects(list(assessed)))
