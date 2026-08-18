"""Credential storage (Keychain replacement) and the optional password gate.

The iOS app stored third-party credentials in the Keychain and never in a backup. The
self-hosted equivalent is Fernet encryption with a key derived from `BRICKSEEKER_SECRET_KEY`,
so the SQLite file on its own is not enough to read them.

One behaviour is deliberately *not* ported: the app's three-state Keychain read
(present/absent/undetermined) existed because iOS can refuse a read on a locked device. A server
read has no such state, so "row missing" genuinely means "not configured" and the accusatory
"non configuré" copy is safe here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Credential, Session


class CredentialKey(StrEnum):
    """Same set of secrets the iOS `KeychainKey` enum held, same meaning."""

    REBRICKABLE_API_KEY = "rebrickable_api_key"
    REBRICKABLE_USER_TOKEN = "rebrickable_user_token"
    BRICKSET_API_KEY = "brickset_api_key"
    BRICKSET_USER_HASH = "brickset_user_hash"
    BRICKLINK_CONSUMER_KEY = "bricklink_consumer_key"
    BRICKLINK_CONSUMER_SECRET = "bricklink_consumer_secret"
    BRICKLINK_TOKEN = "bricklink_token"
    BRICKLINK_TOKEN_SECRET = "bricklink_token_secret"
    VAPID_PRIVATE_KEY = "vapid_private_key"
    VAPID_PUBLIC_KEY = "vapid_public_key"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


async def get_credential(session: AsyncSession, key: CredentialKey | str) -> str | None:
    row = await session.get(Credential, str(key))
    if row is None:
        return None
    try:
        return _fernet().decrypt(row.value_encrypted.encode()).decode()
    except InvalidToken:
        # The secret key changed (rotated, or a data dir moved between hosts). The value is
        # unrecoverable — report it as absent so the UI asks for it again instead of throwing.
        return None


async def set_credential(session: AsyncSession, key: CredentialKey | str, value: str | None) -> None:
    key = str(key)
    if value is None or value == "":
        await session.execute(delete(Credential).where(Credential.key == key))
        await session.commit()
        return
    encrypted = _fernet().encrypt(value.encode()).decode()
    row = await session.get(Credential, key)
    if row is None:
        session.add(Credential(key=key, value_encrypted=encrypted, updated_at=datetime.now(UTC)))
    else:
        row.value_encrypted = encrypted
        row.updated_at = datetime.now(UTC)
    await session.commit()


async def has_credential(session: AsyncSession, key: CredentialKey | str) -> bool:
    return await get_credential(session, key) is not None


async def get_bricklink_credentials(session: AsyncSession) -> dict[str, str] | None:
    """All four OAuth 1.0a values, or `None` if any is missing — a partial set can't sign a
    request, and BrickLink rows are simply omitted when it isn't configured."""
    keys = (
        CredentialKey.BRICKLINK_CONSUMER_KEY,
        CredentialKey.BRICKLINK_CONSUMER_SECRET,
        CredentialKey.BRICKLINK_TOKEN,
        CredentialKey.BRICKLINK_TOKEN_SECRET,
    )
    values = {}
    for key in keys:
        value = await get_credential(session, key)
        if not value:
            return None
        values[key.value] = value
    return {
        "consumer_key": values[CredentialKey.BRICKLINK_CONSUMER_KEY.value],
        "consumer_secret": values[CredentialKey.BRICKLINK_CONSUMER_SECRET.value],
        "token": values[CredentialKey.BRICKLINK_TOKEN.value],
        "token_secret": values[CredentialKey.BRICKLINK_TOKEN_SECRET.value],
    }


# --------------------------------------------------------------------------------------
# Optional password gate
# --------------------------------------------------------------------------------------

SESSION_COOKIE = "brickseeker_session"


def auth_required() -> bool:
    return bool(settings.password)


def verify_password(candidate: str) -> bool:
    expected = settings.password or ""
    return hmac.compare_digest(candidate.encode(), expected.encode())


async def create_session(session: AsyncSession) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=settings.session_ttl_days)
    session.add(Session(token=token, expires_at=expires.replace(tzinfo=None)))
    await session.commit()
    return token


async def session_is_valid(session: AsyncSession, token: str | None) -> bool:
    if not token:
        return False
    row = await session.get(Session, token)
    if row is None:
        return False
    if row.expires_at < datetime.now(UTC).replace(tzinfo=None):
        await session.delete(row)
        await session.commit()
        return False
    return True


async def destroy_session(session: AsyncSession, token: str | None) -> None:
    if not token:
        return
    await session.execute(delete(Session).where(Session.token == token))
    await session.commit()


async def purge_expired_sessions(session: AsyncSession) -> None:
    await session.execute(
        delete(Session).where(Session.expires_at < datetime.now(UTC).replace(tzinfo=None))
    )
    await session.commit()


async def any_session_exists(session: AsyncSession) -> bool:
    result = await session.execute(select(Session.token).limit(1))
    return result.first() is not None
