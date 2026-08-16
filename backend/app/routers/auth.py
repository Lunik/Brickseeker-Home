"""The optional password gate.

A LAN-only deployment shouldn't have to log in, so with `BRICKSEEKER_PASSWORD` unset the app is
open and every endpoint here reports that plainly rather than pretending to authenticate.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from ..config import settings
from ..deps import ApiError, SessionDep
from ..schemas import CamelModel
from ..security import (
    SESSION_COOKIE,
    auth_required,
    create_session,
    destroy_session,
    session_is_valid,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentification"])


class AuthStatusOut(CamelModel):
    auth_required: bool
    authenticated: bool


class LoginIn(CamelModel):
    password: str


class LoginOut(CamelModel):
    ok: bool = True
    auth_required: bool


@router.get("/status", response_model=AuthStatusOut)
async def status(
    session: SessionDep,
    brickseeker_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> AuthStatusOut:
    if not auth_required():
        return AuthStatusOut(auth_required=False, authenticated=True)
    return AuthStatusOut(
        auth_required=True,
        authenticated=await session_is_valid(session, brickseeker_session),
    )


@router.post("/login", response_model=LoginOut)
async def login(payload: LoginIn, session: SessionDep, response: Response) -> LoginOut:
    if not auth_required():
        return LoginOut(auth_required=False)

    if not verify_password(payload.password):
        raise ApiError("Mot de passe incorrect", 401)

    token = await create_session(session)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        # Not forced: a self-hosted deployment is commonly reached over plain http on a LAN, and a
        # Secure cookie there would never be sent back, locking the user out of their own app.
        secure=False,
        path="/",
    )
    return LoginOut(auth_required=True)


@router.post("/logout")
async def logout(
    session: SessionDep,
    response: Response,
    brickseeker_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict[str, bool]:
    await destroy_session(session, brickseeker_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
