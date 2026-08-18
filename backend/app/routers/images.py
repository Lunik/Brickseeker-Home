"""Caching image proxy for set and minifig artwork."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from ..deps import ApiError, require_auth
from ..services.image_cache import ImageNotAllowed, ImageUnavailable, fetch_cached_image

router = APIRouter(tags=["images"], dependencies=[Depends(require_auth)])


@router.get("/images")
async def proxy_image(url: str = Query(min_length=8)) -> Response:
    try:
        payload, content_type = await fetch_cached_image(url)
    except ImageNotAllowed as error:
        # Only the known catalogue hosts are proxied: an open proxy would let anything reach
        # services on the container's own network.
        raise ApiError("Hôte d'image non autorisé", 400) from error
    except ImageUnavailable as error:
        raise ApiError("Image indisponible", 502) from error

    return Response(
        content=payload,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )
