"""Cloudflare fallback: ask a FlareSolverr instance to clear the challenge, reuse its clearance.

FlareSolverr only returns the cookies and the User-Agent it cleared the challenge with. The caller
replays them in a throwaway Chromium context, so the retailer-specific extractors run unchanged.
`cf_clearance` is bound to that exact User-Agent (and to our IP), hence both are handed back.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ...config import settings
from .browser import ScrapeError


@dataclass(frozen=True)
class Clearance:
    user_agent: str
    cookies: list[dict]


def _playwright_cookie(cookie: dict) -> dict | None:
    name, value, domain = cookie.get("name"), cookie.get("value"), cookie.get("domain")
    if not (isinstance(name, str) and isinstance(value, str) and isinstance(domain, str)):
        return None
    converted: dict = {
        "name": name,
        "value": value,
        "domain": domain,
        "path": cookie.get("path") or "/",
        "secure": bool(cookie.get("secure")),
        "httpOnly": bool(cookie.get("httpOnly")),
    }
    expires = cookie.get("expiry", cookie.get("expires"))
    if isinstance(expires, int | float) and expires > 0:
        converted["expires"] = expires
    if cookie.get("sameSite") in ("Strict", "Lax", "None"):
        converted["sameSite"] = cookie["sameSite"]
    return converted


async def solve(url: str, timeout: float) -> Clearance:
    """One stateless `request.get`. Raises `ScrapeError` on any failure, never returns a half result."""
    endpoint = f"{(settings.flaresolverr_url or '').rstrip('/')}/v1"
    try:
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            response = await client.post(
                endpoint,
                json={"cmd": "request.get", "url": url, "maxTimeout": int(timeout * 1000)},
            )
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ScrapeError(f"FlareSolverr indisponible : {error}") from error

    solution = payload.get("solution") if isinstance(payload, dict) else None
    if not isinstance(solution, dict) or payload.get("status") != "ok":
        message = payload.get("message") if isinstance(payload, dict) else None
        raise ScrapeError(f"FlareSolverr a échoué : {message or 'réponse inattendue'}")
    user_agent = solution.get("userAgent")
    cookies = [c for c in map(_playwright_cookie, solution.get("cookies") or []) if c]
    if not isinstance(user_agent, str) or not user_agent or not cookies:
        raise ScrapeError("FlareSolverr n'a renvoyé ni cookies ni User-Agent")
    return Clearance(user_agent=user_agent, cookies=cookies)
