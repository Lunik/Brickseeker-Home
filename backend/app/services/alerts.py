"""Price-alert evaluation.

Reads the just-written cache rather than taking quotes as arguments, so a new price path only has
to call `evaluate_alerts` once instead of threading quotes and the store price through to here.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PriceAlert
from . import collection_repo, notifications
from .pricing import ListCondition, PriceQuote, PriceSource, StoreAvailability, resolve_new_price

#: Floor between two notifications for the same alert. Crossing detection already stops the common
#: "still cheap" repeat; this covers a price oscillating around the threshold, which would
#: otherwise re-cross and re-notify on every refresh.
MINIMUM_NOTIFICATION_INTERVAL = timedelta(hours=12)

#: How fresh a cached price must be to be trusted for a crossing check. Cached prices never expire,
#: so without this a months-old quote could "notify" a drop that isn't real.
MAX_QUOTE_AGE_FOR_ALERTS = timedelta(hours=24)

#: Watched sets are spread uniformly over a week rather than all coming due at once.
PRICE_WATCH_WINDOW = timedelta(days=7)


def next_due_date(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(UTC)
    return moment + timedelta(seconds=random.uniform(0, PRICE_WATCH_WINDOW.total_seconds()))


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_fresh_enough(fetched_at: datetime | None) -> bool:
    stamp = _aware(fetched_at)
    if stamp is None:
        return False
    return datetime.now(UTC) - stamp < MAX_QUOTE_AGE_FOR_ALERTS


def watched_price(
    condition: ListCondition,
    store_price_eur: float | None,
    availability: StoreAvailability,
    quotes: list[PriceQuote],
) -> float | None:
    """The price this alert watches, resolved through the app's *existing* chains.

    `used` is the BrickLink occasion quote **alone** — deliberately no cross-fallback, unlike
    collection valuation: an occasion alert that fired off a retail price would be reporting
    something the user never asked to be told about.
    """
    if condition is ListCondition.NEW:
        return resolve_new_price(store_price_eur, availability, quotes)
    for quote in quotes:
        if quote.source is PriceSource.BRICKLINK_USED:
            return quote.amount
    return None


def effective_threshold(alert: PriceAlert) -> float | None:
    """The amount the price is actually compared against. `None` for a percentage alert whose
    reference was never resolvable — treated as "cannot be evaluated" rather than guessing."""
    if alert.threshold_eur is not None:
        return alert.threshold_eur
    if alert.discount_percent is None or alert.reference_price_eur is None:
        return None
    raw = alert.reference_price_eur * (1 - alert.discount_percent / 100)
    return round(raw, 2)


async def evaluate_alerts(session: AsyncSession, set_num: str) -> list[PriceAlert]:
    """Evaluates both of a set's alerts (neuf and occasion are independent) against the currently
    cached prices, and returns the ones that fired."""
    alerts = [alert for alert in await collection_repo.price_alerts(session, set_num) if alert.is_enabled]
    if not alerts:
        return []

    cached = await collection_repo.cached_set(session, set_num)
    store_price = (
        cached.store_price_eur
        if cached and _is_fresh_enough(cached.store_price_fetched_at)
        else None
    )
    availability = (
        StoreAvailability.from_raw(cached.store_availability) if cached else StoreAvailability.UNKNOWN
    )
    cached_quotes = await collection_repo.cached_prices(session, set_num)
    quotes = [quote for quote in cached_quotes if _is_fresh_enough(quote.fetched_at)]

    fired: list[PriceAlert] = []
    for alert in alerts:
        if await _evaluate(session, alert, store_price, availability, quotes):
            fired.append(alert)
    await session.commit()
    return fired


async def _evaluate(
    session: AsyncSession,
    alert: PriceAlert,
    store_price_eur: float | None,
    availability: StoreAvailability,
    quotes: list[PriceQuote],
) -> bool:
    threshold = effective_threshold(alert)
    if threshold is None:
        return False

    price = watched_price(ListCondition(alert.condition), store_price_eur, availability, quotes)
    if price is None:
        # No price for this condition yet. Leave `was_below_threshold` untouched rather than
        # resetting it, so "no data" doesn't silently re-arm the crossing detector.
        return False

    alert.last_observed_price_eur = price
    is_below = price <= threshold
    was_below = alert.was_below_threshold
    alert.was_below_threshold = is_below

    if not is_below or was_below:
        return False

    last_notified = _aware(alert.last_notified_at)
    if last_notified and datetime.now(UTC) - last_notified < MINIMUM_NOTIFICATION_INTERVAL:
        return False

    alert.last_notified_at = datetime.now(UTC).replace(tzinfo=None)
    await notifications.notify_price_alert(session, alert, price, threshold)
    return True
