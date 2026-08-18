"""Price alerts.

One alert is one threshold, on one set, for **one** condition — never both. Neuf and occasion are
priced by different sources, so a single alert covering the pair could not say which one crossed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import ApiError, SessionDep, require_auth
from ..schemas import CamelModel, OkOut, PriceAlertOut
from ..services import collection_repo
from ..services.alerts import effective_threshold
from ..services.pricing import (
    ListCondition,
    PriceSource,
    StoreAvailability,
    resolve_collection_price,
    resolve_new_price,
)

router = APIRouter(prefix="/alerts", tags=["alertes"], dependencies=[Depends(require_auth)])


class AlertUpsertIn(CamelModel):
    set_num: str
    condition: ListCondition
    threshold_eur: float | None = None
    discount_percent: float | None = None
    is_enabled: bool = True


class AlertEnabledIn(CamelModel):
    is_enabled: bool


def _out(alert) -> PriceAlertOut:  # noqa: ANN001 - ORM row
    return PriceAlertOut(
        id=alert.id,
        set_num=alert.set_num,
        condition=alert.condition,
        set_name=alert.set_name,
        set_img_url=alert.set_img_url,
        threshold_eur=alert.threshold_eur,
        discount_percent=alert.discount_percent,
        reference_price_eur=alert.reference_price_eur,
        reference_source_name=alert.reference_source_name,
        effective_threshold_eur=effective_threshold(alert),
        is_enabled=alert.is_enabled,
        last_observed_price_eur=alert.last_observed_price_eur,
        last_notified_at=alert.last_notified_at,
        created_at=alert.created_at,
    )


async def _resolve_reference(
    session, set_num: str, condition: ListCondition
) -> tuple[float | None, str | None]:
    """The reference a percentage is measured against, resolved **once** and frozen at creation.

    lego.com retail when known — stable and public — otherwise the set's current resolved value for
    that condition. Re-resolving it on every evaluation would let the threshold drift with the
    market, which is precisely what a "-20 %" alert must not do.
    """
    cached = await collection_repo.cached_set(session, set_num)
    quotes = await collection_repo.cached_prices(session, set_num)
    availability = (
        StoreAvailability.from_raw(cached.store_availability) if cached else StoreAvailability.UNKNOWN
    )
    store_price = cached.store_price_eur if cached else None

    if store_price:
        return store_price, "lego.com (officiel)"

    if condition is ListCondition.USED:
        for quote in quotes:
            if quote.source is PriceSource.BRICKLINK_USED:
                return quote.amount, quote.source.display_name
        return None, None

    current = resolve_new_price(store_price, availability, quotes)
    if current is None:
        current = resolve_collection_price(store_price, condition, availability, quotes)
    if current is None:
        return None, None
    source_name = next(
        (quote.source.display_name for quote in quotes if quote.amount == current), "Valeur estimée"
    )
    return current, source_name


@router.get("")
async def read_alerts(session: SessionDep) -> dict[str, list[PriceAlertOut]]:
    alerts = await collection_repo.price_alerts(session)
    return {"alerts": [_out(alert) for alert in alerts]}


@router.get("/{set_num}")
async def read_alerts_for_set(set_num: str, session: SessionDep) -> dict[str, list[PriceAlertOut]]:
    alerts = await collection_repo.price_alerts(session, set_num)
    return {"alerts": [_out(alert) for alert in alerts]}


@router.put("", response_model=PriceAlertOut)
async def upsert_alert(payload: AlertUpsertIn, session: SessionDep) -> PriceAlertOut:
    if payload.threshold_eur is None and payload.discount_percent is None:
        raise ApiError("Indique un montant ou un pourcentage")
    if payload.threshold_eur is not None and payload.discount_percent is not None:
        raise ApiError("Choisis soit un montant, soit un pourcentage")

    cached = await collection_repo.cached_set(session, payload.set_num)
    if cached is None:
        raise ApiError("Ouvre d'abord la fiche de ce set", 404)

    reference_price = None
    reference_source = None
    if payload.discount_percent is not None:
        reference_price, reference_source = await _resolve_reference(
            session, payload.set_num, payload.condition
        )
        if reference_price is None:
            raise ApiError(
                "Aucun prix de référence connu pour ce set — saisis plutôt un montant, "
                "ou rafraîchis les prix d'abord."
            )

    alert = await collection_repo.upsert_price_alert(
        session,
        set_num=payload.set_num,
        condition=payload.condition,
        set_name=cached.name,
        set_img_url=cached.set_img_url,
        threshold_eur=payload.threshold_eur,
        discount_percent=payload.discount_percent,
        reference_price_eur=reference_price,
        reference_source_name=reference_source,
        is_enabled=payload.is_enabled,
    )
    return _out(alert)


@router.patch("/{alert_id}", response_model=OkOut)
async def set_enabled(alert_id: int, payload: AlertEnabledIn, session: SessionDep) -> OkOut:
    await collection_repo.set_price_alert_enabled(session, alert_id, payload.is_enabled)
    return OkOut()


@router.delete("/{alert_id}", response_model=OkOut)
async def delete_alert(alert_id: int, session: SessionDep) -> OkOut:
    await collection_repo.delete_price_alert(session, alert_id)
    return OkOut()
