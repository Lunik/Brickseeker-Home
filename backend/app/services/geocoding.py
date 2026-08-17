"""Turning a scan's coordinates into a place name.

The point of storing a location at all is answering "in which shop did I see this deal", and a
latitude/longitude pair does not answer it — the name does. iOS gets this from CoreLocation's
reverse geocoder; here it comes from Nominatim, OpenStreetMap's public service.

Two constraints shape everything below, and both come from Nominatim's usage policy: **at most one
request per second**, and **a real User-Agent identifying the application**. A self-hosted app
making a handful of requests a day sits comfortably inside that, but only if it never bursts — so
this is throttled globally and results are cached, since a user scanning several sets in one shop
would otherwise ask the same question repeatedly.

Failure is always silent: a scan with no place name is a scan with coordinates, which still plots
on the map. Nothing here may ever block or fail a scan.
"""

from __future__ import annotations

import logging

import httpx

from .throttle import Throttler

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

#: Nominatim's policy is one request per second, and it is enforced by IP.
_throttler = Throttler(1.1)

#: Their policy also requires an identifiable agent with a way to reach the operator.
USER_AGENT = "BrickSeeker/1.0 (self-hosted; https://github.com/lunik/brickseeker)"

_TIMEOUT = httpx.Timeout(8.0, connect=4.0)

#: Coordinates rounded to ~11 m before caching: two scans in the same shop differ in the sixth
#: decimal, and asking twice for the same aisle is exactly the burst the policy forbids.
_PRECISION = 4

_cache: dict[tuple[float, float], str | None] = {}


def _key(latitude: float, longitude: float) -> tuple[float, float]:
    return round(latitude, _PRECISION), round(longitude, _PRECISION)


def _format(payload: dict) -> str | None:
    """A short, human place name — "Carrefour, Nice", not a postal address.

    Nominatim returns a deep address tree; the useful part is the named thing at the point (a shop,
    a mall) plus the town, which is what makes the answer recognisable a month later.
    """
    address = payload.get("address") or {}
    name = payload.get("name") or address.get("shop") or address.get("amenity")

    town = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("suburb")
    )

    parts = [part for part in (name, town) if part]
    if parts:
        return ", ".join(dict.fromkeys(parts))
    # No named feature and no town — a road or a bare display name is still better than nothing.
    display = payload.get("display_name")
    return display.split(",")[0].strip() if display else None


async def reverse_geocode(latitude: float, longitude: float) -> str | None:
    """The place name for a coordinate pair, or `None`.

    Never raises: every failure path returns `None`, because a missing name must never cost the
    caller its scan.
    """
    key = _key(latitude, longitude)
    if key in _cache:
        return _cache[key]

    await _throttler.wait()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(
                NOMINATIM_URL,
                params={
                    "lat": f"{latitude:.6f}",
                    "lon": f"{longitude:.6f}",
                    "format": "jsonv2",
                    # 18 ≈ building level: enough to name the shop without returning a house number.
                    "zoom": "18",
                    "addressdetails": "1",
                },
            )
            response.raise_for_status()
            place = _format(response.json())
    except (httpx.HTTPError, ValueError):
        logger.debug("Géocodage inverse indisponible pour %s, %s", latitude, longitude, exc_info=True)
        # Not cached: a transient outage should not poison this location permanently.
        return None

    _cache[key] = place
    return place
