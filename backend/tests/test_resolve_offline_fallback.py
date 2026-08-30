"""Resolving a set number falls back to the downloaded catalogue when Rebrickable can't answer —
whether because the network is down (503/504) or because no API key is configured (412). A user
who has downloaded the offline catalogue should be able to identify a set by number without ever
needing a Rebrickable account, exactly as promised by Réglages > Catalogue hors-ligne.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.deps import ApiError, missing_credentials, network_unavailable
from app.routers.sets import _resolve
from app.services.rebrickable import LegoSet

_OFFLINE_SET = LegoSet(
    set_num="75440-1",
    name="Villain lair",
    year=2026,
    theme_id=1,
    num_parts=100,
    set_img_url=None,
    set_url=None,
)


@pytest.mark.asyncio
async def test_resolve_falls_back_to_offline_catalogue_when_api_key_missing() -> None:
    """A 412 `missing_credentials` (no Rebrickable API key configured) must not be surfaced as a
    hard failure if the offline catalogue already has the set — it must behave exactly like a
    connectivity failure."""
    session = SimpleNamespace()

    with (
        patch("app.routers.sets.collection_repo.cached_set", AsyncMock(return_value=None)),
        patch(
            "app.routers.sets.rebrickable.client_for",
            AsyncMock(side_effect=missing_credentials("Clé API Rebrickable non configurée")),
        ),
        patch("app.routers.sets.catalog.lookup_catalog_set", AsyncMock(return_value=_OFFLINE_SET)),
    ):
        result = await _resolve(session, "75440")

    assert result.status == "offline"
    assert result.set is not None
    assert result.set.set_num == "75440-1"


@pytest.mark.asyncio
async def test_resolve_still_raises_missing_credentials_when_catalogue_has_no_match() -> None:
    """Without an offline hit, the original 412 must still propagate — no silent success."""
    session = SimpleNamespace()

    with (
        patch("app.routers.sets.collection_repo.cached_set", AsyncMock(return_value=None)),
        patch(
            "app.routers.sets.rebrickable.client_for",
            AsyncMock(side_effect=missing_credentials("Clé API Rebrickable non configurée")),
        ),
        patch("app.routers.sets.catalog.lookup_catalog_set", AsyncMock(return_value=None)),
    ):
        with pytest.raises(ApiError) as excinfo:
            await _resolve(session, "999999")

    assert excinfo.value.status_code == 412


@pytest.mark.asyncio
async def test_resolve_still_falls_back_on_network_unavailable() -> None:
    """503 (connectivity) keeps working exactly as before — this path isn't touched by the fix."""
    session = SimpleNamespace()

    with (
        patch("app.routers.sets.collection_repo.cached_set", AsyncMock(return_value=None)),
        patch(
            "app.routers.sets.rebrickable.client_for",
            AsyncMock(side_effect=network_unavailable()),
        ),
        patch("app.routers.sets.catalog.lookup_catalog_set", AsyncMock(return_value=_OFFLINE_SET)),
    ):
        result = await _resolve(session, "75440")

    assert result.status == "offline"
