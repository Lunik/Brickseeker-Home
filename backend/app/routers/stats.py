"""Collection statistics and exports.

The total is computed with `resolve_collection_price` — the very function the Collection row uses.
That shared call is the reason the list and the total can never disagree about a set's value.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response

from ..deps import SessionDep, require_auth
from ..schemas import CamelModel, SetRowOut
from ..services import catalog, collection_repo, exports
from ..services.pricing import StoreAvailability, resolve_collection_price

router = APIRouter(prefix="/stats", tags=["statistiques"], dependencies=[Depends(require_auth)])

#: Below this share of priced sets a daily reading understates the collection. The point is still
#: real and still plotted, but greyed — drawing it like any other point shows a crash that never
#: happened.
RELIABLE_COVERAGE = 0.8


class ThemeBreakdownOut(CamelModel):
    theme_id: int
    theme_name: str
    set_count: int
    part_count: int


class YearBreakdownOut(CamelModel):
    bucket_start: int
    label: str
    set_count: int


class ValueSnapshotOut(CamelModel):
    day_key: str
    total_value_eur: float
    sets_count: int
    units_count: int
    priced_sets_count: int
    coverage: float
    is_reliable: bool


class StatsOut(CamelModel):
    set_count: int
    unit_count: int
    part_count: int
    theme_count: int
    theme_breakdown: list[ThemeBreakdownOut]
    year_breakdown: list[YearBreakdownOut]
    total_value_eur: float
    sets_with_known_price: int
    priced_unit_count: int
    #: Sets a "compléter les prix manquants" run would actually process — unpriced *and* never
    #: fully processed. The naive `setCount - setsWithKnownPrice` includes sets already tried
    #: against every source, which the queue skips, so the button did nothing and the number never
    #: went down (#194).
    completable_price_count: int
    most_expensive_set: SetRowOut | None
    most_expensive_set_price_eur: float | None
    oldest_set: SetRowOut | None
    largest_set: SetRowOut | None
    value_snapshots: list[ValueSnapshotOut]


@router.get("", response_model=StatsOut)
async def read_stats(session: SessionDep) -> StatsOut:
    owned = await collection_repo.owned_sets(session)
    quotes_by_set = await collection_repo.all_cached_prices(session)
    conditions = await collection_repo.condition_by_list_id(session)
    theme_names = await catalog.theme_names(session)

    def name_of(theme_id: int) -> str:
        return theme_names.get(theme_id, f"Thème #{theme_id}")

    def row_of(cached, price: float | None = None) -> SetRowOut:  # noqa: ANN001 - ORM row
        return SetRowOut.of(cached, theme_name=name_of(cached.theme_id), resolved_price=price)

    if not owned:
        return StatsOut(
            set_count=0,
            unit_count=0,
            part_count=0,
            theme_count=0,
            theme_breakdown=[],
            year_breakdown=[],
            total_value_eur=0.0,
            sets_with_known_price=0,
            priced_unit_count=0,
            completable_price_count=0,
            most_expensive_set=None,
            most_expensive_set_price_eur=None,
            oldest_set=None,
            largest_set=None,
            value_snapshots=await _snapshots(session),
        )

    prices: dict[str, float | None] = {}
    for cached in owned:
        condition = conditions.get(cached.current_list_id) if cached.current_list_id else None
        prices[cached.set_num] = resolve_collection_price(
            cached.store_price_eur,
            condition,
            StoreAvailability.from_raw(cached.store_availability),
            quotes_by_set.get(cached.set_num, []),
        )

    # Grouped by resolved theme *name*, not raw id: Rebrickable's theme table is hierarchical and
    # several distinct ids share a name, so grouping by id splits one theme (e.g. "City") into
    # identical-looking slices.
    themes: dict[str, dict[str, int]] = {}
    for cached in owned:
        bucket = themes.setdefault(
            name_of(cached.theme_id), {"theme_id": cached.theme_id, "set_count": 0, "part_count": 0}
        )
        bucket["theme_id"] = min(bucket["theme_id"], cached.theme_id)
        bucket["set_count"] += 1
        bucket["part_count"] += cached.num_parts * cached.quantity

    # 5-year buckets: a real collection spans 30-40 distinct years, and one bar per year is
    # unreadable at phone width no matter how many labels are thinned out.
    years: dict[int, int] = {}
    for cached in owned:
        years[(cached.year // 5) * 5] = years.get((cached.year // 5) * 5, 0) + 1

    priced = [(cached, prices[cached.set_num]) for cached in owned if prices[cached.set_num] is not None]
    total_value = sum(price * cached.quantity for cached, price in priced)
    most_expensive = max(priced, key=lambda pair: pair[1], default=None)

    stats = StatsOut(
        set_count=len(owned),
        unit_count=sum(cached.quantity for cached in owned),
        part_count=sum(cached.num_parts * cached.quantity for cached in owned),
        theme_count=len(themes),
        theme_breakdown=sorted(
            (
                ThemeBreakdownOut(
                    theme_id=values["theme_id"],
                    theme_name=theme,
                    set_count=values["set_count"],
                    part_count=values["part_count"],
                )
                for theme, values in themes.items()
            ),
            key=lambda item: item.set_count,
            reverse=True,
        ),
        year_breakdown=[
            YearBreakdownOut(bucket_start=start, label=str(start), set_count=count)
            for start, count in sorted(years.items())
        ],
        total_value_eur=total_value,
        sets_with_known_price=len(priced),
        priced_unit_count=sum(cached.quantity for cached, _ in priced),
        completable_price_count=sum(
            1
            for cached in owned
            if prices[cached.set_num] is None and cached.prices_fetched_at is None
        ),
        most_expensive_set=row_of(most_expensive[0], most_expensive[1]) if most_expensive else None,
        most_expensive_set_price_eur=most_expensive[1] if most_expensive else None,
        oldest_set=row_of(min(owned, key=lambda cached: cached.year or 9999)),
        largest_set=row_of(max(owned, key=lambda cached: cached.num_parts)),
        value_snapshots=[],
    )

    # Opening Statistiques records today's reading: the figures were just computed, so it costs no
    # extra fetch, and it keeps working for someone who never runs a price batch.
    await collection_repo.record_collection_value_snapshot(
        session,
        total_value_eur=stats.total_value_eur,
        sets_count=stats.set_count,
        units_count=stats.unit_count,
        priced_sets_count=stats.sets_with_known_price,
    )
    stats.value_snapshots = await _snapshots(session)
    return stats


async def _snapshots(session) -> list[ValueSnapshotOut]:
    rows = await collection_repo.collection_value_snapshots(session)
    out: list[ValueSnapshotOut] = []
    for row in rows:
        coverage = row.priced_sets_count / row.sets_count if row.sets_count else 0.0
        out.append(
            ValueSnapshotOut(
                day_key=row.day_key,
                total_value_eur=row.total_value_eur,
                sets_count=row.sets_count,
                units_count=row.units_count,
                priced_sets_count=row.priced_sets_count,
                coverage=coverage,
                is_reliable=coverage >= RELIABLE_COVERAGE,
            )
        )
    return out


def _filename(extension: str) -> str:
    return f"brickseeker-collection-{datetime.now(UTC).strftime('%Y-%m-%d')}.{extension}"


@router.get("/export.csv")
async def export_csv(session: SessionDep) -> Response:
    payload = await exports.export_collection_csv(session)
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename("csv")}"'},
    )


@router.get("/export.pdf")
async def export_pdf(session: SessionDep) -> Response:
    payload = await exports.export_collection_pdf(session)
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename("pdf")}"'},
    )
