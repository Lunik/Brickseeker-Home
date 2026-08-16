"""Réglages: credentials, preferences, catalogue state, cache.

Credentials are reported as **presence only** and never echoed back. Linking an account uses the
password exactly once to obtain a token and stores only that — the app's privacy claim, ported
verbatim from iOS, is that the password is never retained.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import ApiError, SessionDep, require_auth
from ..schemas import CamelModel, OkOut
from ..security import CredentialKey, get_bricklink_credentials, has_credential, set_credential
from ..services import app_settings, brickset, catalog, collection_repo, image_cache, rebrickable
from ..services.price_updater import price_updater

router = APIRouter(prefix="/settings", tags=["réglages"], dependencies=[Depends(require_auth)])


class CredentialStatusOut(CamelModel):
    rebrickable_api_key: bool
    rebrickable_linked: bool
    brickset_api_key: bool
    brickset_linked: bool
    bricklink: bool


class SettingsOut(CamelModel):
    preferences: dict[str, Any]
    credentials: CredentialStatusOut
    catalog: dict[str, Any]
    price_update: dict[str, Any]


class ApiKeyIn(CamelModel):
    api_key: str


class LinkAccountIn(CamelModel):
    api_key: str | None = None
    username: str
    password: str


class BrickLinkCredentialsIn(CamelModel):
    consumer_key: str
    consumer_secret: str
    token: str
    token_secret: str


async def _credential_status(session) -> CredentialStatusOut:
    return CredentialStatusOut(
        rebrickable_api_key=await has_credential(session, CredentialKey.REBRICKABLE_API_KEY),
        rebrickable_linked=await has_credential(session, CredentialKey.REBRICKABLE_USER_TOKEN),
        brickset_api_key=await has_credential(session, CredentialKey.BRICKSET_API_KEY),
        brickset_linked=await has_credential(session, CredentialKey.BRICKSET_USER_HASH),
        bricklink=await get_bricklink_credentials(session) is not None,
    )


@router.get("", response_model=SettingsOut)
async def read_settings(session: SessionDep) -> SettingsOut:
    return SettingsOut(
        preferences=await app_settings.all_settings(session),
        credentials=await _credential_status(session),
        catalog=await catalog.catalog_status(session),
        price_update=price_updater.state,
    )


@router.patch("/preferences")
async def update_preferences(values: dict[str, Any], session: SessionDep) -> dict[str, Any]:
    return await app_settings.update_settings(session, values)


# --- Rebrickable ---------------------------------------------------------------------


@router.put("/credentials/rebrickable-key", response_model=OkOut)
async def set_rebrickable_key(payload: ApiKeyIn, session: SessionDep) -> OkOut:
    await set_credential(session, CredentialKey.REBRICKABLE_API_KEY, payload.api_key.strip())
    return OkOut()


@router.post("/link/rebrickable", response_model=OkOut)
async def link_rebrickable(payload: LinkAccountIn, session: SessionDep) -> OkOut:
    if payload.api_key:
        await set_credential(session, CredentialKey.REBRICKABLE_API_KEY, payload.api_key.strip())

    client = await rebrickable.client_for(session)
    token = await client.authenticate(payload.username, payload.password)
    await set_credential(session, CredentialKey.REBRICKABLE_USER_TOKEN, token)
    return OkOut()


@router.post("/unlink/rebrickable", response_model=OkOut)
async def unlink_rebrickable(session: SessionDep) -> OkOut:
    # The API key survives: it is independent of the account link, and there is no endpoint that
    # derives one from a username/password, so discarding it would make the user fetch it again.
    await set_credential(session, CredentialKey.REBRICKABLE_USER_TOKEN, None)
    return OkOut()


# --- Brickset ------------------------------------------------------------------------


@router.put("/credentials/brickset-key", response_model=OkOut)
async def set_brickset_key(payload: ApiKeyIn, session: SessionDep) -> OkOut:
    await set_credential(session, CredentialKey.BRICKSET_API_KEY, payload.api_key.strip())
    return OkOut()


@router.post("/link/brickset", response_model=OkOut)
async def link_brickset(payload: LinkAccountIn, session: SessionDep) -> OkOut:
    if payload.api_key:
        await set_credential(session, CredentialKey.BRICKSET_API_KEY, payload.api_key.strip())

    client = await brickset.client_for(session)
    user_hash = await client.authenticate(payload.username, payload.password)
    await set_credential(session, CredentialKey.BRICKSET_USER_HASH, user_hash)
    return OkOut()


@router.post("/unlink/brickset", response_model=OkOut)
async def unlink_brickset(session: SessionDep) -> OkOut:
    await set_credential(session, CredentialKey.BRICKSET_USER_HASH, None)
    return OkOut()


# --- BrickLink -----------------------------------------------------------------------


@router.put("/credentials/bricklink", response_model=OkOut)
async def set_bricklink_credentials(payload: BrickLinkCredentialsIn, session: SessionDep) -> OkOut:
    values = {
        CredentialKey.BRICKLINK_CONSUMER_KEY: payload.consumer_key,
        CredentialKey.BRICKLINK_CONSUMER_SECRET: payload.consumer_secret,
        CredentialKey.BRICKLINK_TOKEN: payload.token,
        CredentialKey.BRICKLINK_TOKEN_SECRET: payload.token_secret,
    }
    if not all(value.strip() for value in values.values()):
        raise ApiError("Les quatre valeurs BrickLink sont nécessaires pour signer une requête")
    for key, value in values.items():
        await set_credential(session, key, value.strip())
    return OkOut()


@router.delete("/credentials/bricklink", response_model=OkOut)
async def clear_bricklink_credentials(session: SessionDep) -> OkOut:
    for key in (
        CredentialKey.BRICKLINK_CONSUMER_KEY,
        CredentialKey.BRICKLINK_CONSUMER_SECRET,
        CredentialKey.BRICKLINK_TOKEN,
        CredentialKey.BRICKLINK_TOKEN_SECRET,
    ):
        await set_credential(session, key, None)
    return OkOut()


# --- Données -------------------------------------------------------------------------


@router.post("/clear-cache")
async def clear_cache(session: SessionDep) -> dict[str, object]:
    """Purges what can be rebuilt. Scans, prix payés, alertes, historique des prix and the daily
    collection valuations all survive — none of them can be re-fetched from anywhere."""
    await collection_repo.clear_cache(session)
    removed_images = image_cache.clear_image_cache()
    return {"ok": True, "removedImages": removed_images}
