"""Notifications: an in-app log plus best-effort Web Push.

The in-app row is written **first** and the push attempted after. Push is the optional half — a
user who never granted permission, or a browser without push support, still gets the bell — so a
push failure is logged and swallowed, never propagated to the caller that was recording a price.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Notification, PriceAlert, PushSubscription
from ..security import CredentialKey, get_credential, set_credential
from .pricing import ListCondition

logger = logging.getLogger(__name__)

#: Required by the Web Push spec as a contact for the push service. mailto: with no real inbox is
#: the accepted convention for a self-hosted deployment that has no support address.
VAPID_CLAIM_EMAIL = "mailto:brickseeker@localhost"


async def notify(
    session: AsyncSession,
    *,
    kind: str,
    title: str,
    body: str,
    set_num: str | None = None,
) -> Notification:
    notification = Notification(kind=kind, title=title, body=body, set_num=set_num)
    session.add(notification)
    await session.commit()
    await session.refresh(notification)

    await _push(session, title=title, body=body, set_num=set_num)
    return notification


async def notify_price_alert(
    session: AsyncSession, alert: PriceAlert, price: float, threshold: float
) -> Notification:
    condition = ListCondition(alert.condition).display_name.lower()
    return await notify(
        session,
        kind="priceAlert",
        title=f"Baisse de prix : {alert.set_name}",
        body=(
            f"{alert.set_num} ({condition}) est à {price:.2f} €, "
            f"sous ton seuil de {threshold:.2f} €."
        ),
        set_num=alert.set_num,
    )


async def notify_batch_complete(session: AsyncSession, processed_count: int) -> Notification:
    return await notify(
        session,
        kind="batchComplete",
        title="Mise à jour des prix terminée",
        body=f"{processed_count} set(s) traité(s).",
    )


async def list_notifications(session: AsyncSession, limit: int = 50) -> tuple[list[Notification], int]:
    rows = (
        (
            await session.execute(
                select(Notification).order_by(Notification.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    unread = (
        await session.execute(
            select(func.count()).select_from(Notification).where(Notification.read_at.is_(None))
        )
    ).scalar_one()
    return list(rows), int(unread)


async def mark_read(session: AsyncSession, ids: list[int] | None = None) -> int:
    query = select(Notification).where(Notification.read_at.is_(None))
    if ids:
        query = query.where(Notification.id.in_(ids))
    rows = (await session.execute(query)).scalars().all()
    stamp = datetime.now(UTC).replace(tzinfo=None)
    for row in rows:
        row.read_at = stamp
    await session.commit()
    return len(rows)


# --------------------------------------------------------------------------------------
# Web Push
# --------------------------------------------------------------------------------------


async def vapid_keys(session: AsyncSession) -> tuple[str, str]:
    """The keypair, generated and stored on first use. Regenerating it would invalidate every
    existing browser subscription, so it is created exactly once."""
    private_key = await get_credential(session, CredentialKey.VAPID_PRIVATE_KEY)
    public_key = await get_credential(session, CredentialKey.VAPID_PUBLIC_KEY)
    if private_key and public_key:
        return private_key, public_key

    private_key, public_key = await asyncio.to_thread(_generate_vapid_keys)
    await set_credential(session, CredentialKey.VAPID_PRIVATE_KEY, private_key)
    await set_credential(session, CredentialKey.VAPID_PUBLIC_KEY, public_key)
    return private_key, public_key


def _generate_vapid_keys() -> tuple[str, str]:
    """A P-256 keypair, built with `cryptography` directly rather than through py_vapid's own
    helpers — those differ across versions, while this serialisation is stable and is exactly what
    pywebpush (PEM private key) and the browser (`applicationServerKey`) each expect."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    # The browser wants the raw uncompressed point, URL-safe base64, unpadded.
    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(raw_public).decode().rstrip("=")
    return private_pem, public_b64


async def subscribe_push(session: AsyncSession, subscription: dict) -> None:
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Abonnement push incomplet")

    existing = await session.get(PushSubscription, endpoint)
    if existing is None:
        session.add(PushSubscription(endpoint=endpoint, p256dh=keys["p256dh"], auth=keys["auth"]))
    else:
        existing.p256dh = keys["p256dh"]
        existing.auth = keys["auth"]
    await session.commit()


async def unsubscribe_push(session: AsyncSession, endpoint: str) -> None:
    await session.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
    await session.commit()


async def _push(session: AsyncSession, *, title: str, body: str, set_num: str | None) -> None:
    subscriptions = (await session.execute(select(PushSubscription))).scalars().all()
    if not subscriptions:
        return

    try:
        private_key, _ = await vapid_keys(session)
    except Exception:  # noqa: BLE001 - push is the optional half; the bell already has the row
        logger.warning("Clés VAPID indisponibles, notification push ignorée", exc_info=True)
        return

    payload = json.dumps({"title": title, "body": body, "setNum": set_num})
    dead: list[str] = []
    for subscription in subscriptions:
        status = await asyncio.to_thread(
            _send_one,
            {
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            payload,
            private_key,
        )
        # 404/410 is the push service saying this subscription is permanently gone — the browser
        # was uninstalled or the permission revoked. Keeping it would retry forever.
        if status in (404, 410):
            dead.append(subscription.endpoint)

    for endpoint in dead:
        await unsubscribe_push(session, endpoint)


def _send_one(subscription_info: dict, payload: str, private_key: str) -> int | None:
    try:
        from pywebpush import webpush

        response = webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=private_key,
            vapid_claims={"sub": VAPID_CLAIM_EMAIL},
            timeout=10,
        )
        return getattr(response, "status_code", None)
    except Exception as error:  # noqa: BLE001
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status not in (404, 410):
            logger.info("Envoi push échoué : %s", error)
        if "WebPushException" in type(error).__name__ or status:
            return status
        return None
