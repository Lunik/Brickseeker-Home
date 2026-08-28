"""New-set catalogue rows keep their cached price even when they were never scanned."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.catalog import new_sets


@pytest.mark.asyncio
async def test_new_sets_uses_any_cached_price_row() -> None:
    session = SimpleNamespace()
    session.execute = AsyncMock()

    baseline_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    rows_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(
                    set_num="77118-1",
                    name="Silver's Car vs. Knuckles' Monster Truck",
                    year=2026,
                    theme_id=1,
                    num_parts=0,
                    set_img_url=None,
                    first_seen_at=datetime(2026, 8, 19, tzinfo=UTC),
                )
            ]
        )
    )
    session.execute.side_effect = [baseline_result, rows_result]

    cached_row = SimpleNamespace(
        set_num="77118-1",
        store_price_eur=24.99,
        store_availability="available",
    )

    with (
        patch("app.routers.catalog.app_settings.get_setting", AsyncMock(return_value=False)),
        patch("app.routers.catalog.collection_repo.owned_sets", AsyncMock(return_value=[])),
        patch("app.routers.catalog.collection_repo.all_cached_sets", AsyncMock(return_value=[cached_row])),
        patch("app.routers.catalog.catalog.theme_names", AsyncMock(return_value={1: "Sonic the Hedgehog"})),
        patch("app.routers.catalog.catalog.should_hide", AsyncMock(return_value=False)),
    ):
        response = await new_sets(
            session=session,
            theme_name=None,
            owned_only=None,
            limit=60,
            include_all=False,
        )

    assert response["count"] == 1
    assert response["results"][0].resolved_price == 24.99
