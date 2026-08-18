"""User preferences — the `UserDefaults` replacement.

Keys keep their iOS names where one already existed, so the two apps' settings read the same in a
support conversation. `hide_wearables_enabled` in particular keeps its historical name even though
the feature outgrew "wearables": renaming it would silently reset the preference.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AppSetting

#: key → default. Everything the UI can toggle lives here; nothing else is a valid key.
DEFAULTS: dict[str, Any] = {
    # Theme (AppTheme.swift)
    "appTheme.brandColor": "red",  # red | yellow | blue
    "appTheme.appearanceMode": "system",  # system | light | dark
    "appTheme.preferredPricePerPart": 0.12,  # €/pièce target, industry rule of thumb
    # Discovery filter (NonSetFilter.swift) — on by default; hiding non-sets is the point, and it
    # only ever affects screens that *suggest* sets, never what the user owns.
    "hide_wearables_enabled": True,
    # Scan location capture (ScanLocationService.swift) — opt-in, off by default.
    "scan_location_enabled": False,
    # Onboarding / intro sheets
    "hasSeenOnboarding": False,
    "hasSeenBatchModeIntro": False,
    # Background price refresh (BackgroundPriceRefresher.swift)
    "backgroundRefresh.enabled": True,
    "backgroundRefresh.lastRunAt": None,
    "backgroundRefresh.lastRunCount": 0,
    # Collection price batch (CollectionPriceUpdater.swift)
    "collectionPriceUpdate.lastCompletedAt": None,
    # Notifications
    "notifications.pushEnabled": False,
}


async def get_setting(session: AsyncSession, key: str) -> Any:
    row = await session.get(AppSetting, key)
    if row is None:
        return DEFAULTS.get(key)
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return DEFAULTS.get(key)


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    encoded = json.dumps(value, default=str)
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=encoded))
    else:
        row.value = encoded
    await session.commit()


async def all_settings(session: AsyncSession) -> dict[str, Any]:
    """Defaults overlaid with whatever has been stored — the shape the frontend hydrates from."""
    result = dict(DEFAULTS)
    rows = (await session.execute(select(AppSetting))).scalars().all()
    for row in rows:
        try:
            result[row.key] = json.loads(row.value)
        except json.JSONDecodeError:
            continue
    return result


async def update_settings(session: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue  # unknown keys are ignored rather than stored, so typos can't accumulate
        encoded = json.dumps(value, default=str)
        row = await session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=encoded))
        else:
            row.value = encoded
    await session.commit()
    return await all_settings(session)
