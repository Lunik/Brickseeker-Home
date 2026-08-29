"""User-driven CAPTCHA resolution for an explicit single-set price refresh.

The user's browser never receives retailer cookies or a raw CDP endpoint. It sees JPEG frames from
the exact Playwright page and sends pointer/keyboard events back through authenticated API routes.
Cookies remain in the shared BrowserContext and are persisted encrypted for the next refresh.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import session_scope
from ..security import get_credential, set_credential
from . import collection_repo, prices
from .pricing import RETAIL_SOURCES, source_display_name
from .rebrickable import LegoSet
from .scraping import browser
from .scraping.browser import InteractiveChallengeUnavailable, ScrapeBlocked

logger = logging.getLogger(__name__)

OperationStatus = Literal[
    "running",
    "captchaRequired",
    "completed",
    "failed",
    "cancelled",
]
ChallengeResolution = Literal["continue", "skip"]

_MAX_CAPTCHA_ATTEMPTS = 3
_COOKIE_KEY_PREFIX = "retailer_session:"
_SPECIAL_KEYS = {
    "Backspace",
    "Delete",
    "Enter",
    "Escape",
    "Tab",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "Home",
    "End",
    "PageDown",
    "PageUp",
    "Space",
}


@dataclass(slots=True)
class BlockedRetailer:
    source: str
    reason: str
    url: str

    @classmethod
    def from_error(cls, source: str, error: ScrapeBlocked) -> BlockedRetailer:
        return cls(source=source, reason=error.reason, url=error.url)


def _blocked_collector(target: dict[str, BlockedRetailer]):
    def capture(source: str, error: ScrapeBlocked) -> None:
        target[source] = BlockedRetailer.from_error(source, error)

    return capture


def _status_collector(target: list[prices.SourceProgressStatus]):
    def capture(_source: str, status: prices.SourceProgressStatus) -> None:
        target.append(status)

    return capture


@dataclass(slots=True)
class CaptchaSession:
    id: str
    operation_id: str
    source: str
    source_url: str
    reason: str
    page: Page
    created_at: datetime
    expires_at: datetime
    resolution: ChallengeResolution | None = None
    resolved: asyncio.Event = field(default_factory=asyncio.Event)
    page_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class InteractiveOperation:
    id: str
    set_num: str
    status: OperationStatus
    created_at: datetime
    updated_at: datetime
    current_challenge_id: str | None = None
    captcha_required_sources: list[str] = field(default_factory=list)
    resolved_sources: list[str] = field(default_factory=list)
    warning: str | None = None
    error: str | None = None
    completed_at: datetime | None = None
    task: asyncio.Task[None] | None = None

    def as_dict(self, challenge: CaptchaSession | None) -> dict[str, object]:
        return {
            "operationId": self.id,
            "setNum": self.set_num,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "captchaRequiredSources": list(self.captcha_required_sources),
            "resolvedSources": list(self.resolved_sources),
            "warning": self.warning,
            "error": self.error,
            "challenge": (
                {
                    "challengeId": challenge.id,
                    "source": challenge.source,
                    "sourceName": source_display_name(challenge.source),
                    "reason": challenge.reason,
                    "pageUrl": challenge.source_url,
                    "expiresAt": challenge.expires_at,
                }
                if challenge is not None
                else None
            ),
        }


class InteractivePriceManager:
    def __init__(self) -> None:
        self._operations: dict[str, InteractiveOperation] = {}
        self._active_by_set: dict[str, str] = {}
        self._challenges: dict[str, CaptchaSession] = {}

    @property
    def has_active_operation(self) -> bool:
        return any(
            operation.status in ("running", "captchaRequired")
            for operation in self._operations.values()
        )

    async def restore(self, session: AsyncSession) -> None:
        """Loads encrypted retailer cookies before Chromium is launched."""
        restored: list[dict] = []
        now = datetime.now(UTC).timestamp()
        for source in RETAIL_SOURCES:
            raw = await get_credential(session, self._cookie_key(source.value))
            if raw is None:
                continue
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Session retailer illisible pour %s", source.value)
                continue
            if not isinstance(decoded, list):
                continue
            for cookie in decoded:
                if not isinstance(cookie, dict):
                    continue
                expires = cookie.get("expires")
                if isinstance(expires, int | float) and expires > 0 and expires <= now:
                    continue
                restored.append(cookie)
        browser.configure_restored_cookies(restored)

    def start(self, set_num: str) -> dict[str, object]:
        self._cleanup_completed()
        existing_id = self._active_by_set.get(set_num)
        if existing_id is not None:
            return self.state(existing_id)
        if self.has_active_operation:
            raise RuntimeError("Une autre actualisation interactive est déjà en cours")

        now = datetime.now(UTC)
        operation = InteractiveOperation(
            id=secrets.token_urlsafe(24),
            set_num=set_num,
            status="running",
            created_at=now,
            updated_at=now,
        )
        self._operations[operation.id] = operation
        self._active_by_set[set_num] = operation.id
        operation.task = asyncio.create_task(self._run(operation))
        return operation.as_dict(None)

    def state(self, operation_id: str) -> dict[str, object]:
        self._cleanup_completed()
        operation = self._operations.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        challenge = (
            self._challenges.get(operation.current_challenge_id)
            if operation.current_challenge_id
            else None
        )
        return operation.as_dict(challenge)

    async def challenge_state(self, challenge_id: str) -> dict[str, object]:
        challenge = self._challenge(challenge_id)
        async with challenge.page_lock:
            try:
                title = await challenge.page.title()
                page_url = challenge.page.url
            except PlaywrightError:
                # Challenge pages reload themselves while validating a proof. The session still
                # exists; a transiently unreadable title must not strand the viewer on a false 404.
                title = source_display_name(challenge.source)
                page_url = challenge.source_url
        return {
            "challengeId": challenge.id,
            "operationId": challenge.operation_id,
            "source": challenge.source,
            "sourceName": source_display_name(challenge.source),
            "reason": challenge.reason,
            "pageTitle": title,
            "pageUrl": page_url,
            "expiresAt": challenge.expires_at,
        }

    async def frame(self, challenge_id: str) -> bytes:
        challenge = self._challenge(challenge_id)
        async with challenge.page_lock:
            try:
                return await challenge.page.screenshot(
                    type="jpeg",
                    quality=75,
                    animations="disabled",
                )
            except PlaywrightError as error:
                raise KeyError(challenge_id) from error

    async def pointer(
        self,
        challenge_id: str,
        event_type: Literal["move", "down", "up"],
        x: float,
        y: float,
        button: Literal["left", "middle", "right"],
    ) -> None:
        challenge = self._challenge(challenge_id)
        async with challenge.page_lock:
            await challenge.page.mouse.move(x, y)
            if event_type == "down":
                await challenge.page.mouse.down(button=button)
            elif event_type == "up":
                await challenge.page.mouse.up(button=button)

    async def wheel(self, challenge_id: str, delta_x: float, delta_y: float) -> None:
        challenge = self._challenge(challenge_id)
        async with challenge.page_lock:
            await challenge.page.mouse.wheel(delta_x, delta_y)

    async def key(self, challenge_id: str, key: str | None, text: str | None) -> None:
        challenge = self._challenge(challenge_id)
        async with challenge.page_lock:
            if text:
                await challenge.page.keyboard.insert_text(text[:16])
                return
            if key not in _SPECIAL_KEYS:
                raise ValueError("Touche non autorisée")
            await challenge.page.keyboard.press(key)

    def resolve_challenge(
        self,
        challenge_id: str,
        resolution: ChallengeResolution,
    ) -> None:
        challenge = self._challenge(challenge_id)
        challenge.resolution = resolution
        challenge.resolved.set()

    async def cancel(self, operation_id: str) -> None:
        operation = self._operations.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        task = operation.task
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        tasks = [
            operation.task
            for operation in self._operations.values()
            if operation.task is not None and not operation.task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for challenge in list(self._challenges.values()):
            await self._close_challenge(challenge)
        self._challenges.clear()

    async def _run(self, operation: InteractiveOperation) -> None:
        try:
            # Opening a stale detail page may already have started a non-interactive refresh.
            deadline = time.monotonic() + settings.price_refresh_timeout_seconds
            while (
                prices.is_background_refreshing(operation.set_num)
                and time.monotonic() < deadline
            ):
                await asyncio.sleep(0.5)

            blocked: dict[str, BlockedRetailer] = {}

            async with session_scope() as session:
                lego_set = await self._lego_set(session, operation.set_num)
                await prices.refresh_set_prices(
                    session,
                    lego_set,
                    reconcile=True,
                    on_captcha=_blocked_collector(blocked),
                    bypass_cooldown=True,
                )

            operation.captcha_required_sources = list(blocked)
            operation.updated_at = datetime.now(UTC)
            for source, challenge in blocked.items():
                try:
                    await self._resolve_source(operation, lego_set, source, challenge)
                except asyncio.CancelledError:
                    raise
                except InteractiveChallengeUnavailable:
                    label = source_display_name(source)
                    operation.warning = (
                        f"{label} refuse cette session interactive ; réessayez plus tard."
                    )
                except Exception as error:  # noqa: BLE001 - one retailer must not hide the next
                    label = source_display_name(source)
                    operation.warning = f"{label} n'a pas pu ouvrir sa validation."
                    logger.warning(
                        "Validation interactive échouée pour %s (%s)",
                        source,
                        error,
                        exc_info=True,
                    )

            operation.status = "completed"
            if operation.captcha_required_sources and operation.warning is None:
                names = ", ".join(
                    source_display_name(source)
                    for source in operation.captcha_required_sources
                )
                operation.warning = f"CAPTCHA encore requis : {names}."
        except asyncio.CancelledError:
            operation.status = "cancelled"
            operation.warning = "Actualisation interactive annulée."
        except Exception as error:  # noqa: BLE001 - state must become terminal for the polling UI
            operation.status = "failed"
            operation.error = str(error)
            logger.warning(
                "Actualisation interactive échouée pour %s",
                operation.set_num,
                exc_info=True,
            )
        finally:
            operation.current_challenge_id = None
            operation.completed_at = datetime.now(UTC)
            operation.updated_at = operation.completed_at
            self._active_by_set.pop(operation.set_num, None)

    async def _resolve_source(
        self,
        operation: InteractiveOperation,
        lego_set: LegoSet,
        source: str,
        blocked: BlockedRetailer,
    ) -> None:
        current = blocked
        for _attempt in range(_MAX_CAPTCHA_ATTEMPTS):
            page = await browser.open_interactive_page(current.url)
            now = datetime.now(UTC)
            challenge = CaptchaSession(
                id=secrets.token_urlsafe(24),
                operation_id=operation.id,
                source=source,
                source_url=current.url,
                reason=current.reason,
                page=page,
                created_at=now,
                expires_at=now + timedelta(seconds=settings.captcha_interactive_timeout_seconds),
            )
            self._challenges[challenge.id] = challenge
            operation.current_challenge_id = challenge.id
            operation.status = "captchaRequired"
            operation.updated_at = now

            timed_out = False
            try:
                await asyncio.wait_for(
                    challenge.resolved.wait(),
                    timeout=settings.captcha_interactive_timeout_seconds,
                )
            except TimeoutError:
                timed_out = True
                operation.warning = (
                    f"Validation expirée pour {source_display_name(source)}."
                )
            except asyncio.CancelledError:
                await self._close_challenge(challenge)
                raise
            finally:
                operation.current_challenge_id = None
                operation.status = "running"

            if timed_out or challenge.resolution == "skip":
                await self._close_challenge(challenge)
                return

            await self._close_challenge(challenge)

            retry: dict[str, BlockedRetailer] = {}
            retry_status: list[prices.SourceProgressStatus] = []

            async with session_scope() as session:
                await prices.refresh_retail_source(
                    session,
                    lego_set,
                    source,
                    on_captcha=_blocked_collector(retry),
                    on_progress=_status_collector(retry_status),
                )
            if source not in retry and "completed" in retry_status:
                cookies = await browser.cookies_for_url(current.url)
                await self._save_cookies(source, current.url, cookies)
                prices.clear_captcha_requirement(source)
                operation.captcha_required_sources = [
                    value
                    for value in operation.captcha_required_sources
                    if value != source
                ]
                operation.resolved_sources.append(source)
                operation.updated_at = datetime.now(UTC)
                return
            if source not in retry:
                operation.warning = (
                    f"{source_display_name(source)} n'a pas pu être vérifié après le CAPTCHA."
                )
                return
            current = retry[source]

        operation.warning = (
            f"Le CAPTCHA {source_display_name(source)} n'a pas été validé."
        )

    async def _save_cookies(self, source: str, url: str, cookies: list[dict]) -> None:
        host = (urlparse(url).hostname or "").lower()
        selected = [
            cookie
            for cookie in cookies
            if isinstance(cookie.get("domain"), str)
            and (
                host == cookie["domain"].lstrip(".").lower()
                or host.endswith(f".{cookie['domain'].lstrip('.').lower()}")
            )
        ]
        if not selected:
            return
        browser.remember_cookies(selected)
        async with session_scope() as session:
            await set_credential(
                session,
                self._cookie_key(source),
                json.dumps(selected, separators=(",", ":")),
            )

    async def _close_challenge(self, challenge: CaptchaSession) -> None:
        async with challenge.page_lock:
            await browser.close_interactive_page(challenge.page)
        self._challenges.pop(challenge.id, None)

    async def _lego_set(self, session: AsyncSession, set_num: str) -> LegoSet:
        cached = await collection_repo.cached_set(session, set_num)
        if cached is None:
            raise ValueError("Ce set n'est pas encore en cache")
        return collection_repo.to_lego_set(cached)

    def _challenge(self, challenge_id: str) -> CaptchaSession:
        challenge = self._challenges.get(challenge_id)
        if challenge is None or challenge.expires_at <= datetime.now(UTC):
            raise KeyError(challenge_id)
        return challenge

    def _cleanup_completed(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(
            seconds=settings.captcha_operation_retention_seconds
        )
        expired = [
            operation_id
            for operation_id, operation in self._operations.items()
            if operation.completed_at is not None and operation.completed_at < cutoff
        ]
        for operation_id in expired:
            self._operations.pop(operation_id, None)

    @staticmethod
    def _cookie_key(source: str) -> str:
        return f"{_COOKIE_KEY_PREFIX}{source}"


interactive_price_manager = InteractivePriceManager()
