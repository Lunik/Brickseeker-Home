"""Image proxy endpoints used by canvas exports.

Normal thumbnails load directly from catalog CDNs (`imageUrl()` in the frontend), but drawing those
cross-origin URLs onto a `<canvas>` requires CORS headers that those CDNs do not always send.
This endpoint keeps the rest of the app on direct CDN URLs while giving share-card export a
same-origin image URL.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

from ..deps import ApiError, require_auth

_TIMEOUT = httpx.Timeout(15.0, connect=6.0)

router = APIRouter(prefix="/images", tags=["images"], dependencies=[Depends(require_auth)])


def _validate_remote_image_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ApiError("URL d'image invalide", status.HTTP_400_BAD_REQUEST)
    if not parsed.hostname:
        raise ApiError("URL d'image invalide", status.HTTP_400_BAD_REQUEST)
    if parsed.hostname == "localhost":
        raise ApiError("Hôte d'image non autorisé", status.HTTP_400_BAD_REQUEST)
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return url
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise ApiError("Hôte d'image non autorisé", status.HTTP_400_BAD_REQUEST)
    return url


@router.get("/proxy")
async def proxy(url: str = Query()) -> Response:
    remote_url = _validate_remote_image_url(url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            upstream = await client.get(remote_url)
        upstream.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == status.HTTP_404_NOT_FOUND:
            raise ApiError("Image introuvable", status.HTTP_404_NOT_FOUND) from exc
        raise ApiError("Impossible de charger l'image", status.HTTP_502_BAD_GATEWAY) from exc
    except httpx.HTTPError as exc:
        raise ApiError(
            "Connexion impossible. Vérifiez votre réseau.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    content_type = upstream.headers.get("content-type", "").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        raise ApiError("Le lien ne pointe pas vers une image", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
