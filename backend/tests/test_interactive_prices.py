from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error as PlaywrightError

from app.services import interactive_prices
from app.services.interactive_prices import (
    CaptchaSession,
    InteractiveOperation,
    InteractivePriceManager,
)
from app.services.rebrickable import LegoSet
from app.services.scraping.browser import ScrapeBlocked


@asynccontextmanager
async def _session_scope():
    yield None


def _page() -> MagicMock:
    page = MagicMock()
    page.title = AsyncMock(return_value="CAPTCHA")
    page.screenshot = AsyncMock(return_value=b"jpeg")
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.keyboard.insert_text = AsyncMock()
    page.keyboard.press = AsyncMock()
    return page


@pytest.mark.asyncio
async def test_explicit_refresh_waits_for_captcha_then_retries_only_source() -> None:
    manager = InteractivePriceManager()
    page = _page()
    lego_set = LegoSet("76924-1", "Mercedes", 2024, 1, 808, None, None)

    async def initial_refresh(_session, _target, **kwargs):
        kwargs["on_captcha"](
            "fnac",
            ScrapeBlocked("DataDome CAPTCHA", "https://www.fnac.com/search"),
        )
        return {}

    async def retry_refresh(_session, _target, source, **kwargs):
        kwargs["on_progress"](source, "started")
        kwargs["on_progress"](source, "completed")
        return None

    with (
        patch.object(manager, "_lego_set", new=AsyncMock(return_value=lego_set)),
        patch.object(manager, "_save_cookies", new=AsyncMock()) as save_cookies,
        patch.object(
            interactive_prices,
            "session_scope",
            _session_scope,
        ),
        patch.object(
            interactive_prices.prices,
            "is_background_refreshing",
            return_value=False,
        ),
        patch.object(
            interactive_prices.prices,
            "refresh_set_prices",
            side_effect=initial_refresh,
        ),
        patch.object(
            interactive_prices.prices,
            "refresh_retail_source",
            side_effect=retry_refresh,
        ) as retry_source,
        patch.object(
            interactive_prices.browser,
            "open_interactive_page",
            new=AsyncMock(return_value=page),
        ),
        patch.object(
            interactive_prices.browser,
            "cookies_for_url",
            new=AsyncMock(return_value=[{"name": "datadome", "domain": ".fnac.com"}]),
        ),
        patch.object(
            interactive_prices.browser,
            "close_interactive_page",
            new=AsyncMock(),
        ),
        patch.object(interactive_prices.prices, "clear_captcha_requirement"),
    ):
        started = manager.start(lego_set.set_num)
        operation_id = str(started["operationId"])
        for _ in range(20):
            state = manager.state(operation_id)
            if state["status"] == "captchaRequired":
                break
            await asyncio.sleep(0)
        else:
            pytest.fail("CAPTCHA state was never published")

        challenge = state["challenge"]
        assert isinstance(challenge, dict)
        manager.resolve_challenge(str(challenge["challengeId"]), "continue")

        operation = manager._operations[operation_id]
        assert operation.task is not None
        await operation.task

    assert manager.state(operation_id)["status"] == "completed"
    assert manager.state(operation_id)["captchaRequiredSources"] == []
    assert manager.state(operation_id)["resolvedSources"] == ["fnac"]
    retry_source.assert_awaited_once()
    save_cookies.assert_awaited_once()


@pytest.mark.asyncio
async def test_captcha_viewer_forwards_frame_pointer_keyboard_and_wheel() -> None:
    manager = InteractivePriceManager()
    page = _page()
    now = datetime.now(UTC)
    operation = InteractiveOperation("operation", "76924-1", "captchaRequired", now, now)
    challenge = CaptchaSession(
        id="challenge",
        operation_id=operation.id,
        source="fnac",
        source_url="https://www.fnac.com/search",
        reason="DataDome CAPTCHA",
        page=page,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    manager._operations[operation.id] = operation
    manager._challenges[challenge.id] = challenge

    assert await manager.frame(challenge.id) == b"jpeg"
    await manager.pointer(challenge.id, "down", 100, 200, "left")
    await manager.pointer(challenge.id, "move", 140, 200, "left")
    await manager.pointer(challenge.id, "up", 180, 200, "left")
    await manager.wheel(challenge.id, 0, 300)
    await manager.key(challenge.id, None, "123456")
    await manager.key(challenge.id, "Enter", None)

    page.mouse.down.assert_awaited_once_with(button="left")
    page.mouse.up.assert_awaited_once_with(button="left")
    page.mouse.wheel.assert_awaited_once_with(0, 300)
    page.keyboard.insert_text.assert_awaited_once_with("123456")
    page.keyboard.press.assert_awaited_once_with("Enter")


@pytest.mark.asyncio
async def test_challenge_reload_does_not_make_session_look_expired() -> None:
    manager = InteractivePriceManager()
    page = _page()
    page.title = AsyncMock(side_effect=PlaywrightError("context destroyed"))
    now = datetime.now(UTC)
    challenge = CaptchaSession(
        id="challenge",
        operation_id="operation",
        source="fnac",
        source_url="https://www.fnac.com/search",
        reason="DataDome CAPTCHA",
        page=page,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    manager._challenges[challenge.id] = challenge

    state = await manager.challenge_state(challenge.id)

    assert state["pageTitle"] == "Fnac (neuf)"
    assert state["pageUrl"] == challenge.source_url


def test_different_interactive_sets_cannot_overlap() -> None:
    manager = InteractivePriceManager()
    now = datetime.now(UTC)
    manager._operations["active"] = InteractiveOperation(
        "active",
        "76924-1",
        "running",
        now,
        now,
    )
    manager._active_by_set["76924-1"] = "active"

    with pytest.raises(RuntimeError, match="déjà en cours"):
        manager.start("10350-1")


@pytest.mark.asyncio
async def test_background_block_records_captcha_without_raising() -> None:
    statuses: list[tuple[str, str]] = []

    async def blocked():
        raise ScrapeBlocked("DataDome CAPTCHA", "https://www.fnac.com/search")

    interactive_prices.prices.clear_captcha_requirement("fnac")
    try:
        result = await interactive_prices.prices._run_source(
            "fnac",
            blocked,
            lambda source, status: statuses.append((source, status)),
            browser_backed=True,
            bypass_cooldown=True,
        )
        assert result is None
        assert ("fnac", "captcha_required") in statuses
        assert "fnac" in interactive_prices.prices.captcha_required_sources()
    finally:
        interactive_prices.prices.clear_captcha_requirement("fnac")


@pytest.mark.asyncio
async def test_restore_loads_only_unexpired_encrypted_cookies() -> None:
    manager = InteractivePriceManager()
    future = datetime.now(UTC).timestamp() + 3600
    expired = datetime.now(UTC).timestamp() - 3600
    stored = json.dumps(
        [
            {"name": "valid", "value": "secret", "domain": ".fnac.com", "expires": future},
            {"name": "old", "value": "secret", "domain": ".fnac.com", "expires": expired},
        ]
    )

    async def credential(_session, key):
        return stored if str(key).endswith(":fnac") else None

    with (
        patch.object(interactive_prices, "get_credential", side_effect=credential),
        patch.object(interactive_prices.browser, "configure_restored_cookies") as configure,
    ):
        await manager.restore(None)

    configure.assert_called_once()
    restored = configure.call_args.args[0]
    assert [cookie["name"] for cookie in restored] == ["valid"]
