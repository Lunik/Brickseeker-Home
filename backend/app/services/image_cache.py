"""Disk cache for set and minifig artwork.

Two reasons this exists rather than letting the browser hit the CDN directly: a list re-requests
the same images on every render, and the container may reach hosts the browser can't.

The host allowlist is a security control, not tidiness — an unrestricted URL proxy is an SSRF hole
that would let anything reach services on the container's network.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset(
    {
        "cdn.rebrickable.com",
        "rebrickable.com",
        "www.rebrickable.com",
        "m.rebrickable.com",
        "img.bricklink.com",
        "www.lego.com",
        "images.brickset.com",
    }
)

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
#: Anything larger than this is not a set thumbnail; refusing it keeps a hostile redirect from
#: filling the volume.
MAX_IMAGE_BYTES = 10 * 1024 * 1024
#: A redirect chain this long is not a CDN doing HTTP->HTTPS or a canonical-host bounce.
_MAX_REDIRECTS = 5


class ImageNotAllowed(Exception):
    pass


class ImageUnavailable(Exception):
    pass


def _is_allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.hostname in ALLOWED_HOSTS


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in _CONTENT_TYPES:
        suffix = ".img"
    # Two levels of fan-out: a large collection is tens of thousands of files, and a single flat
    # directory that size is slow to stat on most filesystems.
    directory = settings.image_cache_dir / digest[:2] / digest[2:4]
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{digest}{suffix}"


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


async def fetch_cached_image(url: str) -> tuple[bytes, str]:
    if not _is_allowed(url):
        raise ImageNotAllowed(url)

    path = _cache_path(url)
    if path.exists():
        return path.read_bytes(), _content_type(path)

    try:
        payload, content_type = await _download(url, path)
    except httpx.HTTPError as error:
        raise ImageUnavailable(url) from error

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)  # atomic: a concurrent reader never sees a half-written file
    _evict_if_needed()

    return payload, content_type


async def _download(url: str, path: Path) -> tuple[bytes, str]:
    """Fetch `url`, following redirects by hand and re-checking the allowlist on every hop.

    `follow_redirects=True` only lets us see the *final* URL after the request already happened —
    by then a redirect to an internal address has already reached it. And the size cap must apply
    to bytes as they arrive, not to a fully-buffered body: buffering first defeats the whole point
    of the cap, an oversized response is what it exists to stop paying for.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS):
            async with client.stream("GET", url) as response:
                if response.has_redirect_location:
                    url = str(response.url.join(response.headers["location"]))
                    if not _is_allowed(url):
                        raise ImageNotAllowed(url)
                    continue

                response.raise_for_status()
                content_type = response.headers.get("content-type", _content_type(path)).split(
                    ";"
                )[0]
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_IMAGE_BYTES:
                        raise ImageUnavailable(url)
                return bytes(chunks), content_type
        raise ImageUnavailable(url)


def _evict_if_needed() -> None:
    """Oldest-first eviction once the cache exceeds its budget. Cheap because it only runs after a
    miss, and every entry is re-downloadable."""
    root = settings.image_cache_dir
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix != ".tmp"]
    total = sum(p.stat().st_size for p in files)
    if total <= settings.image_cache_max_bytes:
        return

    for path in sorted(files, key=lambda p: p.stat().st_mtime):
        try:
            total -= path.stat().st_size
            path.unlink()
        except OSError:
            continue
        if total <= settings.image_cache_max_bytes * 0.9:
            break


def clear_image_cache() -> int:
    removed = 0
    for path in settings.image_cache_dir.rglob("*"):
        if path.is_file():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed
