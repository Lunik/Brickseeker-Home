"""Test that scraping errors (including timeouts) are handled gracefully and don't crash the batch."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.scraping.browser import (
    _REMOTE_LAUNCH_OPTIONS_JSON,
    ScrapeBlocked,
    ScrapeChallengeUnsolved,
    ScrapeError,
    _acquire_page,
    _datadome_challenge_state,
    _retry_blocked_datadome_frame,
    load_and_extract,
)


@pytest.mark.asyncio
async def test_acquire_page_recovers_from_scrape_error_on_first_attempt() -> None:
    """When _ensure_stack raises ScrapeError on first try, _acquire_page should recover with retry."""
    with patch("app.services.scraping.browser._ensure_stack") as mock_ensure_stack:
        mock_dispose = AsyncMock()
        with patch("app.services.scraping.browser._dispose", mock_dispose):
            # First call fails with ScrapeError (e.g. timeout), second succeeds
            mock_context_first = MagicMock()
            mock_page = MagicMock()
            mock_context_first.new_page = AsyncMock(return_value=mock_page)
            
            mock_ensure_stack.side_effect = [
                ScrapeError("Chromium indisponible : délai de connexion dépassé"),
                (MagicMock(), mock_context_first),
            ]
            
            # Should not raise, should return the page from second attempt
            page = await _acquire_page()
            assert page == mock_page
            assert mock_ensure_stack.call_count == 2
            assert mock_dispose.call_count == 1


@pytest.mark.asyncio
async def test_acquire_page_fails_after_two_scrape_errors() -> None:
    """When both attempts fail with ScrapeError, _acquire_page should raise ScrapeError."""
    with patch("app.services.scraping.browser._ensure_stack") as mock_ensure_stack:
        mock_dispose = AsyncMock()
        with patch("app.services.scraping.browser._dispose", mock_dispose):
            # Both calls fail with ScrapeError
            mock_ensure_stack.side_effect = [
                ScrapeError("Chromium indisponible : délai de connexion dépassé"),
                ScrapeError("Chromium indisponible : délai de connexion dépassé"),
            ]
            
            with pytest.raises(ScrapeError) as exc_info:
                await _acquire_page()
            
            assert "Chromium indisponible" in str(exc_info.value)
            assert mock_ensure_stack.call_count == 2
            assert mock_dispose.call_count == 1


@pytest.mark.asyncio
async def test_total_scrape_deadline_includes_page_acquisition() -> None:
    cancelled = asyncio.Event()

    async def stalled_page():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with (
        patch("app.services.scraping.browser._acquire_page", side_effect=stalled_page),
        pytest.raises(ScrapeChallengeUnsolved, match="Délai global dépassé"),
    ):
        await asyncio.wait_for(
            load_and_extract(
                "https://example.test",
                readiness_js="true",
                extract_js="'ok'",
                timeout=0.01,
            ),
            timeout=0.2,
        )

    await asyncio.wait_for(cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_dynamic_page_retries_an_empty_extraction() -> None:
    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(
        side_effect=[None, True, "null", None, True, '{"price":"49.99"}']
    )

    with (
        patch(
            "app.services.scraping.browser._acquire_page",
            new=AsyncMock(return_value=page),
        ),
        patch("app.services.scraping.browser._close_page", new=AsyncMock()),
    ):
        result = await load_and_extract(
            "https://example.test",
            readiness_js="ready",
            extract_js="extract",
            timeout=1,
            retry_empty_extraction=True,
        )

    assert result == '{"price":"49.99"}'
    assert page.evaluate.await_count == 6


def test_datadome_challenge_is_recognized_as_explicit_block() -> None:
    from app.services.scraping.browser import _BLOCKED_JS

    assert "captcha-delivery.com" in _BLOCKED_JS
    assert ScrapeBlocked.__mro__[1] is ScrapeError


@pytest.mark.asyncio
async def test_interactive_datadome_page_clicks_retry_but_not_the_challenge() -> None:
    normal_frame = MagicMock(url="https://www.king-jouet.com/search")
    captcha_frame = MagicMock(url="https://geo.captcha-delivery.com/captcha/")
    captcha_frame.evaluate = AsyncMock(return_value=True)
    page = MagicMock(frames=[normal_frame, captcha_frame])

    assert await _retry_blocked_datadome_frame(page) is True

    captcha_frame.evaluate.assert_awaited_once()
    script = captcha_frame.evaluate.await_args.args[0]
    assert "retry" in script.lower()
    assert "drag" not in script.lower()


def test_remote_browser_is_headful_for_datadome_validation() -> None:
    options = json.loads(_REMOTE_LAUNCH_OPTIONS_JSON)

    assert options["headless"] is False
    assert options["stealth"] is False


@pytest.mark.asyncio
async def test_terminal_datadome_block_is_not_presented_as_solvable() -> None:
    frame = MagicMock(url="https://geo.captcha-delivery.com/captcha/")
    frame.evaluate = AsyncMock(return_value="blocked")
    page = MagicMock(frames=[frame])

    assert await _datadome_challenge_state(page) == "blocked"
