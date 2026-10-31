"""Cloudflare fallback: FlareSolverr only for a stuck Cloudflare challenge, nothing else."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.scraping import browser, flaresolverr
from app.services.scraping.browser import (
    ScrapeBlocked,
    ScrapeChallengeUnsolved,
    ScrapeCloudflareChallenge,
    ScrapeError,
    load_and_extract,
)

_SOLUTION = {
    "status": "ok",
    "solution": {
        "userAgent": "UA/1.0",
        "cookies": [
            {"name": "cf_clearance", "value": "x", "domain": ".cultura.com", "path": "/",
             "expiry": 1900000000, "httpOnly": True, "secure": True, "sameSite": "None"},
            {"name": "bad"},
        ],
    },
}


def _mock_client(handler):
    real = httpx.AsyncClient
    return patch.object(
        flaresolverr.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


async def test_solve_converts_cookies_and_keeps_user_agent() -> None:
    with (
        patch.object(flaresolverr.settings, "flaresolverr_url", "http://fs:8191/"),
        _mock_client(lambda request: httpx.Response(200, json=_SOLUTION)),
    ):
        clearance = await flaresolverr.solve("https://www.cultura.com/", 30)
    assert clearance.user_agent == "UA/1.0"
    assert clearance.cookies == [
        {"name": "cf_clearance", "value": "x", "domain": ".cultura.com", "path": "/",
         "secure": True, "httpOnly": True, "expires": 1900000000, "sameSite": "None"}
    ]


async def test_solve_raises_scrape_error_on_failure() -> None:
    failed = {"status": "error", "message": "Timeout"}
    with (
        patch.object(flaresolverr.settings, "flaresolverr_url", "http://fs:8191"),
        _mock_client(lambda request: httpx.Response(500, json=failed)),
        pytest.raises(ScrapeError, match="Timeout"),
    ):
        await flaresolverr.solve("https://www.cultura.com/", 30)


async def test_cloudflare_challenge_falls_back_to_flaresolverr() -> None:
    context = MagicMock(add_cookies=AsyncMock(), close=AsyncMock())
    fake_browser = MagicMock(new_context=AsyncMock(return_value=context))
    attempts = AsyncMock(side_effect=[ScrapeCloudflareChallenge("stuck"), "{}"])
    clearance = flaresolverr.Clearance("UA/1.0", [{"name": "cf_clearance"}])
    with (
        patch.object(browser.settings, "flaresolverr_url", "http://fs:8191"),
        patch.object(browser, "_load_and_extract", attempts),
        patch.object(flaresolverr, "solve", AsyncMock(return_value=clearance)),
        patch.object(browser, "get_browser", AsyncMock(return_value=fake_browser)),
    ):
        assert await load_and_extract("https://x", "r", "e") == "{}"
    assert fake_browser.new_context.await_args.kwargs["user_agent"] == "UA/1.0"
    context.add_cookies.assert_awaited_once_with([{"name": "cf_clearance"}])
    assert attempts.await_args_list[1].kwargs["context"] is context
    context.close.assert_awaited_once()


async def test_cloudflare_challenge_without_flaresolverr_url_is_unchanged() -> None:
    with (
        patch.object(browser.settings, "flaresolverr_url", None),
        patch.object(browser, "_load_and_extract", AsyncMock(side_effect=ScrapeCloudflareChallenge("s"))),
        pytest.raises(ScrapeChallengeUnsolved),
    ):
        await load_and_extract("https://x", "r", "e")


@pytest.mark.parametrize(
    "error", [ScrapeBlocked("DataDome CAPTCHA", "https://x"), ScrapeChallengeUnsolved("t")]
)
async def test_non_cloudflare_errors_never_reach_flaresolverr(error: Exception) -> None:
    solve = AsyncMock()
    with (
        patch.object(browser.settings, "flaresolverr_url", "http://fs:8191"),
        patch.object(browser, "_load_and_extract", AsyncMock(side_effect=error)),
        patch.object(flaresolverr, "solve", solve),
        pytest.raises(type(error)),
    ):
        await load_and_extract("https://x", "r", "e")
    solve.assert_not_awaited()
