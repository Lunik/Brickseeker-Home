"""Shared response models.

JSON is camelCase — the frontend types are ported from the iOS models, so `setNum`/`numParts` read
identically on both sides — while Python stays snake_case. `CamelModel` does the aliasing once so
no router hand-writes field names.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .models import CachedSet, ScanEvent
from .services.pricing import (
    PriceQuote,
    SetValuation,
    StoreAvailability,
    is_minifig,
)


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class LegoSetOut(CamelModel):
    set_num: str
    name: str
    year: int
    theme_id: int
    num_parts: int
    set_img_url: str | None = None
    set_url: str | None = None


class PriceQuoteOut(CamelModel):
    source: str
    amount: float
    currency: str
    source_url: str | None
    fetched_at: datetime | None
    min_amount: float | None
    max_amount: float | None
    lot_count: int | None
    is_thin_sample: bool
    is_stale: bool

    @classmethod
    def of(cls, quote: PriceQuote) -> PriceQuoteOut:
        return cls(
            source=quote.source.value,
            amount=quote.amount,
            currency=quote.currency,
            source_url=quote.source_url,
            fetched_at=quote.fetched_at,
            min_amount=quote.min_amount,
            max_amount=quote.max_amount,
            lot_count=quote.lot_count,
            is_thin_sample=quote.is_thin_sample,
            is_stale=quote.is_stale,
        )


class ValuationOut(CamelModel):
    current_value_eur: float | None
    basis_eur: float | None
    basis: str
    valued_condition: str | None
    growth_percent: float | None
    as_of: datetime | None
    is_stale: bool

    @classmethod
    def of(cls, valuation: SetValuation) -> ValuationOut:
        return cls(
            current_value_eur=valuation.current_value_eur,
            basis_eur=valuation.basis_eur,
            basis=valuation.basis.value,
            valued_condition=valuation.valued_condition.value if valuation.valued_condition else None,
            growth_percent=valuation.growth_percent,
            as_of=valuation.as_of,
            is_stale=valuation.is_stale,
        )


class SetRowOut(CamelModel):
    """One list row. `price_condition` is what the amount actually represents — not always the
    list's nominal condition, since the resolvers cross-fall-back as a last resort."""

    set_num: str
    name: str
    year: int
    theme_id: int
    theme_name: str
    num_parts: int
    set_img_url: str | None
    quantity: int
    is_in_collection: bool
    is_in_wishlist: bool
    has_price_alert: bool = False
    was_scanned: bool
    last_scanned_at: datetime | None
    current_list_id: int | None
    current_list_name: str | None
    store_price_eur: float | None
    availability: str
    resolved_price: float | None = None
    price_condition: str | None = None
    price_label: str | None = None
    is_minifig: bool = False

    @classmethod
    def of(
        cls,
        cached: CachedSet,
        *,
        theme_name: str,
        resolved_price: float | None = None,
        price_condition: str | None = None,
        price_label: str | None = None,
        has_price_alert: bool = False,
    ) -> SetRowOut:
        return cls(
            set_num=cached.set_num,
            name=cached.name,
            year=cached.year,
            theme_id=cached.theme_id,
            theme_name=theme_name,
            num_parts=cached.num_parts,
            set_img_url=cached.set_img_url,
            quantity=cached.quantity,
            is_in_collection=cached.is_in_collection,
            is_in_wishlist=cached.is_in_wishlist,
            has_price_alert=has_price_alert,
            was_scanned=cached.was_scanned,
            last_scanned_at=cached.last_scanned_at,
            current_list_id=cached.current_list_id,
            current_list_name=cached.current_list_name,
            store_price_eur=cached.store_price_eur,
            availability=StoreAvailability.from_raw(cached.store_availability).value,
            resolved_price=resolved_price,
            price_condition=price_condition,
            price_label=price_label,
            is_minifig=is_minifig(cached.set_num),
        )


class ScanEventOut(CamelModel):
    id: int
    set_num: str
    scanned_at: datetime
    latitude: float | None
    longitude: float | None
    place_name: str | None
    price_seen_eur: float | None

    @classmethod
    def of(cls, event: ScanEvent) -> ScanEventOut:
        return cls.model_validate(event)


class PriceAlertOut(CamelModel):
    id: int
    set_num: str
    condition: str
    set_name: str
    set_img_url: str | None
    threshold_eur: float | None
    discount_percent: float | None
    reference_price_eur: float | None
    reference_source_name: str | None
    effective_threshold_eur: float | None
    is_enabled: bool
    last_observed_price_eur: float | None
    last_notified_at: datetime | None
    created_at: datetime


class SetListOut(CamelModel):
    id: int
    name: str
    num_sets: int
    condition: str


class CatalogSetExportOut(CamelModel):
    """One line of `GET /catalog/export?name=sets` — the whole downloaded catalogue, for the
    browser's own offline copy. Deliberately leaner than `CatalogSetOut`: no owned/availability/
    price fields, since those are live-only and this snapshot exists purely for offline
    identification."""

    set_num: str
    name: str
    year: int
    theme_id: int
    num_parts: int
    set_img_url: str | None
    first_seen_at: datetime | None


class CatalogMinifigExportOut(CamelModel):
    """One line of `GET /catalog/export?name=minifigs`. `containing_set_nums` is denormalized here
    (unlike the online gallery) and uncapped — the client needs the whole join to look a minifig up
    offline, not a 12-item display sample."""

    fig_num: str
    name: str
    num_parts: int
    img_url: str | None
    theme_id: int | None
    year: int | None
    containing_set_nums: list[str]


class OkOut(CamelModel):
    ok: bool = True
