"""The price-resolution kernel — a line-by-line port of the iOS app's `SetRowView.swift`
resolution chains, `SetValuation.swift`, `DealVerdict.swift` and `PriceComparison.swift`.

Pure functions, no database and no network: callers read the pieces they need and hand them in.
That is what keeps the Collection row, the Statistics total, the CSV export and the alert
evaluator from ever disagreeing about what one set is worth — the drift issue #194 had to fix.

The chains are **not** interchangeable and each exists for a stated reason:

* `resolve_new_price` — History: lego.com retail → cheapest(Amazon, Cdiscount) → BrickLink neuf.
* `resolve_collection_price` — Collection row *and* the Statistics total (one function, #194),
  condition-driven with a last-resort cross-fallback to the other condition. Uses the
  **pricier** of Amazon/Cdiscount so the collection's value doesn't dip based on which
  marketplace happened to be cheaper that day.
* `resolve_wishlist_price` — Liste cadeaux: cheapest(Amazon, Cdiscount) **before** lego.com,
  deliberately reversed from `resolve_new_price` (#109/#121).
* `resolve_minifig_price` — a minifig only ever has BrickLink quotes (#175), so retail/Amazon/
  Cdiscount never enter.

A `.retired` lego.com availability gates the retail step out of the *value* chains (#243):
lego.com keeps serving a residual `product:price:amount` for sets it no longer sells, and
reporting that as the set's price is wrong. It never gates the growth *reference* — measuring
the market's move away from the catalogue price is the whole point of that percentage.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

#: How old a price gets before the UI captions it with its age (#244). Not a TTL and not a
#: filter — a stale price is still shown, never dropped.
STALE_AFTER = timedelta(days=7)

#: Source key for lego.com in `PriceHistoryEntry`, which (unlike a `PriceQuote`) has no
#: `PriceSource` case of its own.
LEGO_STORE_HISTORY_SOURCE = "legoStore"


class PriceSource(StrEnum):
    BRICKLINK_USED = "bricklinkUsed"
    BRICKLINK_NEW = "bricklinkNew"
    AMAZON = "amazon"
    CDISCOUNT = "cdiscount"

    @property
    def is_used(self) -> bool:
        return self is PriceSource.BRICKLINK_USED

    @property
    def display_name(self) -> str:
        return {
            PriceSource.BRICKLINK_USED: "BrickLink (occasion)",
            PriceSource.BRICKLINK_NEW: "BrickLink (neuf)",
            PriceSource.AMAZON: "Amazon (neuf)",
            PriceSource.CDISCOUNT: "Cdiscount (neuf)",
        }[self]


def source_display_name(raw: str) -> str:
    """Display name for a `PriceHistoryEntry.source`, covering lego.com too."""
    if raw == LEGO_STORE_HISTORY_SOURCE:
        return "lego.com (officiel)"
    try:
        return PriceSource(raw).display_name
    except ValueError:
        return raw


class ListCondition(StrEnum):
    NEW = "newSet"
    USED = "used"

    @property
    def display_name(self) -> str:
        return "Neuf" if self is ListCondition.NEW else "Occasion"


class StoreAvailability(StrEnum):
    """Typed view of lego.com's raw `product:availability`. Only these three strings have been
    observed; anything else maps to `unknown` rather than being guessed at."""

    AVAILABLE = "available"
    OUT_OF_STOCK = "outOfStock"
    RETIRED = "retired"
    UNKNOWN = "unknown"

    @classmethod
    def from_raw(cls, raw: str | None) -> StoreAvailability:
        match (raw or "").lower():
            case "in stock":
                return cls.AVAILABLE
            case "out of stock":
                return cls.OUT_OF_STOCK
            case "retired":
                return cls.RETIRED
            case _:
                return cls.UNKNOWN

    @property
    def display_name(self) -> str:
        return {
            StoreAvailability.AVAILABLE: "En vente",
            StoreAvailability.OUT_OF_STOCK: "Rupture de stock",
            StoreAvailability.RETIRED: "Retiré de la vente",
            StoreAvailability.UNKNOWN: "Inconnue",
        }[self]


@dataclass(slots=True, frozen=True)
class SoldSale:
    """One completed BrickLink sale. No currency of its own — it is always the parent quote's,
    and duplicating it would only invite the two drifting apart."""

    unit_amount: float
    quantity: int
    ordered_at: datetime


@dataclass(slots=True)
class PriceQuote:
    """One source's price for one item.

    `amount` is *the* number every consumer means by "the price". The fields below it are optional
    context a source may or may not provide, and nothing may quietly promote one of them into
    `amount`'s place (#213) — in particular BrickLink's `qty_avg_price`, which is deliberately
    never stored.
    """

    source: PriceSource
    amount: float
    currency: str = "EUR"
    source_url: str | None = None
    fetched_at: datetime | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    lot_count: int | None = None
    #: `None` and `[]` mean different things and the storage layer depends on it: `None` is "this
    #: quote says nothing about sales" (rebuilt from cache), `[]` is a live fetch that found none —
    #: the only one of the two allowed to clear stored rows.
    sales: list[SoldSale] | None = None

    @property
    def is_thin_sample(self) -> bool:
        """Whether the average rests on so few sales that one atypical transaction *is* the quote.
        A `None` lot count is not thin: every non-BrickLink source quotes a single listing and has
        no sample size to be small in the first place."""
        if self.lot_count is None:
            return False
        return 0 < self.lot_count <= 2

    @property
    def is_stale(self) -> bool:
        if self.fetched_at is None:
            return False
        return _now() - _aware(self.fetched_at) > STALE_AFTER


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _quote(quotes: Iterable[PriceQuote], source: PriceSource) -> PriceQuote | None:
    for quote in quotes:
        if quote.source == source:
            return quote
    return None


def _amount(quotes: Iterable[PriceQuote], source: PriceSource) -> float | None:
    found = _quote(quotes, source)
    return found.amount if found else None


# --------------------------------------------------------------------------------------
# Amazon / Cdiscount are one comparison point everywhere except SetDetail
# --------------------------------------------------------------------------------------


def _amazon_or_cdiscount(quotes: Sequence[PriceQuote], pick: Callable[[float, float], float]) -> float | None:
    amazon = _amount(quotes, PriceSource.AMAZON)
    cdiscount = _amount(quotes, PriceSource.CDISCOUNT)
    if amazon is not None and cdiscount is not None:
        return pick(amazon, cdiscount)
    return amazon if amazon is not None else cdiscount


def best_amazon_or_cdiscount(quotes: Sequence[PriceQuote]) -> float | None:
    """The cheaper of the two — for chains about the best deal to buy at (History, Wishlist)."""
    return _amazon_or_cdiscount(quotes, min)


def most_expensive_amazon_or_cdiscount(quotes: Sequence[PriceQuote]) -> float | None:
    """The pricier of the two — for collection valuation (#124): the total estimated value
    shouldn't drop just because one marketplace happened to be cheaper that day."""
    return _amazon_or_cdiscount(quotes, max)


# --------------------------------------------------------------------------------------
# The chains
# --------------------------------------------------------------------------------------


def resolve_new_price(
    store_price_eur: float | None,
    availability: StoreAvailability,
    quotes: Sequence[PriceQuote],
) -> float | None:
    """History's chain. Never returns a used price."""
    if availability is not StoreAvailability.RETIRED and store_price_eur is not None:
        return store_price_eur
    market = best_amazon_or_cdiscount(quotes)
    if market is not None:
        return market
    return _amount(quotes, PriceSource.BRICKLINK_NEW)


def _resolve_new_price_for_valuation(
    store_price_eur: float | None,
    availability: StoreAvailability,
    quotes: Sequence[PriceQuote],
) -> float | None:
    """Same chain, taking the pricier of Amazon/Cdiscount (#124)."""
    if availability is not StoreAvailability.RETIRED and store_price_eur is not None:
        return store_price_eur
    market = most_expensive_amazon_or_cdiscount(quotes)
    if market is not None:
        return market
    return _amount(quotes, PriceSource.BRICKLINK_NEW)


def resolve_collection_price_detailed(
    store_price_eur: float | None,
    condition: ListCondition | None,
    availability: StoreAvailability,
    quotes: Sequence[PriceQuote],
) -> tuple[float, ListCondition] | None:
    """Shared branching behind the amount and its label, so the two can never drift apart.

    The list condition is the *primary* source; the cross-fallback to the other condition is
    strictly last-resort (#194 — dropping such sets both under-counted the collection and left
    "Compléter les prix manquants" looping on sets a re-fetch could never fix).
    """
    used_price = _amount(quotes, PriceSource.BRICKLINK_USED)
    new_price = _resolve_new_price_for_valuation(store_price_eur, availability, quotes)

    if (condition or ListCondition.NEW) is ListCondition.NEW:
        if new_price is not None:
            return new_price, ListCondition.NEW
        if used_price is not None:
            return used_price, ListCondition.USED
        return None
    if used_price is not None:
        return used_price, ListCondition.USED
    if new_price is not None:
        return new_price, ListCondition.NEW
    return None


def resolve_collection_price(
    store_price_eur: float | None,
    condition: ListCondition | None,
    availability: StoreAvailability,
    quotes: Sequence[PriceQuote],
) -> float | None:
    resolved = resolve_collection_price_detailed(store_price_eur, condition, availability, quotes)
    return resolved[0] if resolved else None


def resolve_collection_price_condition(
    store_price_eur: float | None,
    condition: ListCondition | None,
    availability: StoreAvailability,
    quotes: Sequence[PriceQuote],
) -> ListCondition | None:
    resolved = resolve_collection_price_detailed(store_price_eur, condition, availability, quotes)
    return resolved[1] if resolved else None


def resolve_minifig_price(condition: ListCondition | None, quotes: Sequence[PriceQuote]) -> float | None:
    """BrickLink-only (#203). `None` condition — a minifig with no owned containing set — defaults
    to `used`, not `newSet`, matching this resolver's original and only source."""
    used_price = _amount(quotes, PriceSource.BRICKLINK_USED)
    new_price = _amount(quotes, PriceSource.BRICKLINK_NEW)
    if (condition or ListCondition.USED) is ListCondition.USED:
        return used_price if used_price is not None else new_price
    return new_price if new_price is not None else used_price


def resolve_wishlist_price_detailed(
    store_price_eur: float | None, quotes: Sequence[PriceQuote]
) -> tuple[float, ListCondition] | None:
    market = best_amazon_or_cdiscount(quotes)
    if market is not None:
        return market, ListCondition.NEW
    if store_price_eur is not None:
        return store_price_eur, ListCondition.NEW
    new_price = _amount(quotes, PriceSource.BRICKLINK_NEW)
    if new_price is not None:
        return new_price, ListCondition.NEW
    used_price = _amount(quotes, PriceSource.BRICKLINK_USED)
    if used_price is not None:
        return used_price, ListCondition.USED
    return None


def resolve_wishlist_price(store_price_eur: float | None, quotes: Sequence[PriceQuote]) -> float | None:
    resolved = resolve_wishlist_price_detailed(store_price_eur, quotes)
    return resolved[0] if resolved else None


def resolve_wishlist_price_condition(
    store_price_eur: float | None, quotes: Sequence[PriceQuote]
) -> ListCondition | None:
    resolved = resolve_wishlist_price_detailed(store_price_eur, quotes)
    return resolved[1] if resolved else None


# --------------------------------------------------------------------------------------
# Valuation
# --------------------------------------------------------------------------------------


class ValuationBasis(StrEnum):
    PAID = "paid"
    RETAIL = "retail"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class SetValuation:
    current_value_eur: float | None
    basis_eur: float | None
    basis: ValuationBasis
    valued_condition: ListCondition | None
    growth_percent: float | None
    as_of: datetime | None

    @property
    def has_value(self) -> bool:
        return self.current_value_eur is not None

    @property
    def is_stale(self) -> bool:
        if self.as_of is None:
            return False
        return _now() - _aware(self.as_of) > STALE_AFTER


EMPTY_VALUATION = SetValuation(None, None, ValuationBasis.UNKNOWN, None, None, None)


def make_valuation(
    set_num: str,
    store_price_eur: float | None,
    paid_price_eur: float | None,
    condition: ListCondition | None,
    quotes: Sequence[PriceQuote],
    store_price_fetched_at: datetime | None = None,
    availability: StoreAvailability = StoreAvailability.UNKNOWN,
) -> SetValuation:
    """What one item is worth now and how that compares to what it cost.

    The current value is **never** resolved here — it delegates to the chains above, which is what
    keeps the header card, the Collection row and the Statistics total agreeing.

    The reference follows one rule and no other (#227): the paid price when recorded, the lego.com
    retail price as the *sole* default, and nothing at all otherwise. A marketplace quote is never
    promoted to reference — those say what the set is worth *now*, not what it cost, so using one
    would make the percentage compare two market readings instead of measuring a gain. A minifig
    therefore keeps showing "—" until a paid price is recorded: it is never sold at retail, so
    there is no catalogue price to move away from.
    """
    if is_minifig(set_num):
        current_value = resolve_minifig_price(condition, quotes)
        valued_condition = None if current_value is None else (condition or ListCondition.USED)
    else:
        detailed = resolve_collection_price_detailed(store_price_eur, condition, availability, quotes)
        current_value = detailed[0] if detailed else None
        valued_condition = detailed[1] if detailed else None

    if paid_price_eur is not None and paid_price_eur > 0:
        basis_eur, basis = paid_price_eur, ValuationBasis.PAID
    elif store_price_eur is not None and store_price_eur > 0:
        basis_eur, basis = store_price_eur, ValuationBasis.RETAIL
    else:
        basis_eur, basis = None, ValuationBasis.UNKNOWN

    growth_percent = None
    if current_value is not None and basis_eur:
        growth_percent = (current_value - basis_eur) / basis_eur * 100

    # Recovers which quote produced `current_value` by matching the amount back to its source,
    # rather than re-deriving the winning branch — a second decision tree is how the label and the
    # number drift apart.
    as_of: datetime | None = None
    if current_value is not None:
        if store_price_eur is not None and store_price_eur == current_value:
            as_of = store_price_fetched_at
        else:
            for quote in quotes:
                if quote.amount == current_value:
                    as_of = quote.fetched_at
                    break

    return SetValuation(
        current_value_eur=current_value,
        basis_eur=basis_eur,
        basis=basis,
        valued_condition=valued_condition,
        growth_percent=growth_percent,
        as_of=as_of,
    )


# --------------------------------------------------------------------------------------
# Deal verdict ("prix vu en magasin")
# --------------------------------------------------------------------------------------


class DealVerdict(StrEnum):
    GOOD = "good"
    FAIR = "fair"
    BAD = "bad"

    @property
    def emoji(self) -> str:
        return {DealVerdict.GOOD: "🟢", DealVerdict.FAIR: "🟡", DealVerdict.BAD: "🔴"}[self]

    @property
    def label(self) -> str:
        return {
            DealVerdict.GOOD: "Bonne affaire",
            DealVerdict.FAIR: "Correct",
            DealVerdict.BAD: "À éviter",
        }[self]


@dataclass(slots=True, frozen=True)
class DealComparison:
    label: str
    reference_amount: float
    difference_amount: float
    percent: int
    fetched_at: datetime | None


@dataclass(slots=True, frozen=True)
class DealVerdictResult:
    verdict: DealVerdict
    comparisons: list[DealComparison]


def evaluate_deal(
    price_seen: float,
    store_amount: float | None,
    store_currency: str | None,
    quotes: Sequence[PriceQuote],
    store_fetched_at: datetime | None = None,
    currency: str = "EUR",
) -> DealVerdictResult | None:
    """Mirrors `PriceRepository`'s "a source that fails is simply omitted": a reference that isn't
    loaded, or is in another currency, is left out rather than blocking the verdict."""
    comparisons: list[DealComparison] = []

    def add(label: str, reference: float, fetched_at: datetime | None) -> None:
        difference = price_seen - reference
        percent = round((difference / reference) * 100) if reference else 0
        comparisons.append(DealComparison(label, reference, difference, int(percent), fetched_at))

    if store_amount and store_amount > 0 and (store_currency or currency) == currency:
        add("lego.com (officiel)", store_amount, store_fetched_at)

    for source in (
        PriceSource.BRICKLINK_NEW,
        PriceSource.AMAZON,
        PriceSource.CDISCOUNT,
        PriceSource.BRICKLINK_USED,
    ):
        quote = _quote(quotes, source)
        if quote is None or quote.currency != currency:
            continue
        add(source.display_name, quote.amount, quote.fetched_at)

    if not comparisons:
        return None

    if all(c.percent < 0 for c in comparisons):
        verdict = DealVerdict.GOOD
    elif all(c.percent > 0 for c in comparisons):
        verdict = DealVerdict.BAD
    else:
        verdict = DealVerdict.FAIR
    return DealVerdictResult(verdict=verdict, comparisons=comparisons)


def percent_vs_store(
    amount: float, currency: str, store_amount: float | None, store_currency: str | None
) -> int | None:
    """The "±% versus lego.com" shared by SetDetail's per-row hint and the batch ranking. A 0%
    result is returned as 0, not None — display sites decide whether to hide it."""
    if not store_amount or store_amount <= 0 or (store_currency or "EUR") != currency:
        return None
    return int(round(((amount - store_amount) / store_amount) * 100))


# --------------------------------------------------------------------------------------
# Identifier helpers (ports of the `String` extensions in `APIModels.swift`)
# --------------------------------------------------------------------------------------


def is_minifig(set_num: str) -> bool:
    return set_num.startswith("fig-")


def base_set_num(set_num: str) -> str:
    """Strips Rebrickable's variant suffix (`71045-3` → `71045`). Minifig ids have no suffix, so
    they're returned as-is — splitting one would leave just `fig` (#123)."""
    if is_minifig(set_num):
        return set_num
    return set_num.split("-")[0] if "-" in set_num else set_num


def set_digits(set_num: str) -> str:
    """The digits a marketplace search uses — same as `base_set_num` for a set."""
    return base_set_num(set_num)
