"""Test that scraping errors (including timeouts) are handled gracefully and don't crash the batch."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.scraping.browser import ScrapeError, _acquire_page, _ensure_stack


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
