"""In-app notifications and Web Push subscriptions."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from ..deps import ApiError, SessionDep, require_auth
from ..schemas import CamelModel, OkOut
from ..services import notifications

router = APIRouter(
    prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)]
)


class NotificationOut(CamelModel):
    id: int
    kind: str
    title: str
    body: str
    set_num: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationsOut(CamelModel):
    notifications: list[NotificationOut]
    unread_count: int


class MarkReadIn(CamelModel):
    ids: list[int] | None = None


class UnsubscribeIn(CamelModel):
    endpoint: str


@router.get("", response_model=NotificationsOut)
async def read_notifications(session: SessionDep, limit: int = 50) -> NotificationsOut:
    rows, unread = await notifications.list_notifications(session, limit)
    return NotificationsOut(
        notifications=[NotificationOut.model_validate(row) for row in rows], unread_count=unread
    )


@router.post("/read")
async def mark_read(payload: MarkReadIn, session: SessionDep) -> dict[str, int]:
    return {"updated": await notifications.mark_read(session, payload.ids)}


@router.get("/vapid-key")
async def vapid_key(session: SessionDep) -> dict[str, str]:
    _, public_key = await notifications.vapid_keys(session)
    return {"publicKey": public_key}


@router.post("/subscribe", response_model=OkOut)
async def subscribe(payload: dict, session: SessionDep) -> OkOut:
    try:
        await notifications.subscribe_push(session, payload)
    except ValueError as error:
        raise ApiError(str(error)) from error
    return OkOut()


@router.post("/unsubscribe", response_model=OkOut)
async def unsubscribe(payload: UnsubscribeIn, session: SessionDep) -> OkOut:
    await notifications.unsubscribe_push(session, payload.endpoint)
    return OkOut()
