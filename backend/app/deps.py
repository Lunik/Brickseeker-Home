"""Shared FastAPI dependencies and the error vocabulary the routers raise.

`ApiError` carries the same French messages `APIError.errorDescription` produced in the iOS app —
the UI copy is part of the port, not incidental.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .security import SESSION_COOKIE, auth_required, session_is_valid

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class ApiError(HTTPException):
    """A failure the UI is expected to render inline, with the app's own French wording."""

    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(status_code=status_code, detail=message)


def unauthorized() -> ApiError:
    return ApiError("API Key invalide", status.HTTP_401_UNAUTHORIZED)


def forbidden() -> ApiError:
    return ApiError("Nom d'utilisateur ou mot de passe incorrect", status.HTTP_403_FORBIDDEN)


def not_found(message: str = "Ressource introuvable") -> ApiError:
    return ApiError(message, status.HTTP_404_NOT_FOUND)


def missing_credentials(message: str = "Identifiants manquants") -> ApiError:
    return ApiError(message, status.HTTP_412_PRECONDITION_FAILED)


def network_unavailable() -> ApiError:
    return ApiError("Connexion impossible. Vérifiez votre réseau.", status.HTTP_503_SERVICE_UNAVAILABLE)


def rate_limited() -> ApiError:
    return ApiError("Trop de requêtes, veuillez réessayer plus tard", status.HTTP_429_TOO_MANY_REQUESTS)


async def require_auth(
    session: SessionDep,
    brickseeker_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """No-op unless `BRICKSEEKER_PASSWORD` is set — a LAN-only deployment shouldn't have to log in."""
    if not auth_required():
        return
    if not await session_is_valid(session, brickseeker_session):
        raise ApiError("Authentification requise", status.HTTP_401_UNAUTHORIZED)


AuthDep = Annotated[None, Depends(require_auth)]
