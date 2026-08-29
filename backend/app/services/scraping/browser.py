"""The one browser code path — Playwright/Chromium replacing the iOS app's hidden `WKWebView`.

lego.com and most external retail sites sit behind a JS bot challenge (lego.com's was confirmed to
be a Cloudflare Managed Challenge via `cf-mitigated: challenge` and the "Just a moment..."
interstitial). No plain HTTP client passes them: it was verified with `curl` from several networks
under several realistic User-Agents that the block is identical every time. It is not a
header/UA/cookie problem — the challenge requires executing the page's JavaScript. Do not spend time
re-trying `httpx` variants against these hosts.

The iOS app drove a per-call `WKWebView` sharing one `WKProcessPool` and the default data store.
The equivalent here is one lazily launched Chromium plus **one long-lived context**: the context is
what holds `cf_clearance`, so a solved challenge is reused by later scrapes instead of being paid
for again. Each `load_and_extract` still gets its **own page**, so independent scrapes run in
parallel — the app's rule of "no shared single-web-view mutex; don't reintroduce one" applies here
too.

That Chromium is either launched in-process (local dev against a Playwright install) or reached
over CDP on `settings.browser_ws_endpoint` (the packaged image, which bundles no browser — see
docker-compose.yml's `chromium` service). Same launch flags either way, same lifecycle either way;
only how the process is reached differs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from urllib.parse import quote

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Response as PlaywrightResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ...config import settings

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------


class ScrapeError(Exception):
    """Base failure. Every price source treats one of these as "no quote", never as fatal."""


class ScrapeNotFound(ScrapeError):
    """The page became ready but the extractor matched nothing (no card, no meta tag)."""


class ScrapeHttpNotFound(ScrapeError):
    """The page's *own* response was 404, seen after the challenge cleared — a genuinely removed
    product, which lego.com must be able to tell apart from a challenge that never cleared."""


class ScrapeChallengeUnsolved(ScrapeError):
    """Readiness never went truthy inside the timeout."""


class ScrapeBlocked(ScrapeError):
    """The retailer explicitly rejected this automated browser session."""

    def __init__(self, reason: str, url: str) -> None:
        super().__init__(f"Accès refusé par le retailer ({reason}) : {url}")
        self.reason = reason
        self.url = url


class InteractiveChallengeUnavailable(ScrapeError):
    """The retailer refused this browser without exposing a human-solvable challenge."""


class ScrapeDisabled(ScrapeError):
    """`scraping_enabled` is off. A `ScrapeError` subclass on purpose: every existing caller already
    omits the source on `ScrapeError`, so turning scraping off needs no new handling anywhere."""


_DISABLED_MESSAGE = "Scraping désactivé (BRICKSEEKER_SCRAPING_ENABLED=false)"


# --------------------------------------------------------------------------------------
# Browser lifecycle
# --------------------------------------------------------------------------------------

#: Realistic desktop Chrome, built around the engine's real major version — a UA claiming a Chrome
#: release far from the one actually rendering is itself a bot signal.
_USER_AGENT_TEMPLATE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
)
_FALLBACK_CHROME_MAJOR = "131"

_VIEWPORT = {"width": 1280, "height": 800}

_LAUNCH_ARGS = [
    # Drops `navigator.webdriver`, which every one of these challenges scores on.
    "--disable-blink-features=AutomationControlled",
    # Docker's default 64 MB /dev/shm makes Chromium crash mid-render.
    "--disable-dev-shm-usage",
    # The container runs unprivileged and without user namespaces, so the sandbox can't start.
    "--no-sandbox",
]
#: DataDome accepts the slider in a headless session but rejects the fingerprint after the human
#: completes it. The Browserless sidecar owns an Xvfb display, so its long-lived browser runs
#: headful; bare local development keeps the in-process browser headless because no display is
#: guaranteed there. `connect_over_cdp` takes these options in the URL, not as Python kwargs.
_REMOTE_LAUNCH_OPTIONS_JSON = json.dumps(
    {"headless": False, "stealth": False, "args": _LAUNCH_ARGS}
)

_POLL_INTERVAL = 0.4
_CLOSE_TIMEOUT_SECONDS = 10.0
_BLOCKED_JS = """
(() => {
  if (document.querySelector('iframe[src*="captcha-delivery.com"]')) return 'DataDome CAPTCHA';
  const title = document.title || '';
  const text = document.body ? document.body.innerText : '';
  if (/accès bloqué/i.test(title) || /^accès bloqué/i.test(text.trim())) return 'accès bloqué';
  if (/Malheureusement notre site n'est actuellement pas disponible/i.test(text)) {
    return 'site indisponible pour cette session';
  }
  return null;
})()
"""

_playwright: Playwright | None = None
_browser: Browser | None = None
_context: BrowserContext | None = None
_restored_cookies: dict[tuple[str, str, str], dict] = {}
#: Serialises launch/teardown only. Pages are created under it but *used* outside it, which is what
#: keeps parallel scrapes parallel.
_lock = asyncio.Lock()


def _user_agent(browser: Browser) -> str:
    major = (browser.version or "").split(".")[0] or _FALLBACK_CHROME_MAJOR
    return _USER_AGENT_TEMPLATE.format(major=major)


def remember_cookies(cookies: list[dict]) -> None:
    """Keeps encrypted-on-disk retailer cookies available after a Chromium relaunch."""
    for cookie in cookies:
        name = cookie.get("name")
        domain = cookie.get("domain")
        path = cookie.get("path")
        if all(isinstance(value, str) and value for value in (name, domain, path)):
            _restored_cookies[(domain, path, name)] = dict(cookie)


def configure_restored_cookies(cookies: list[dict]) -> None:
    """Startup hook. Values came from encrypted credential storage, never from the frontend."""
    remember_cookies(cookies)


async def _ensure_stack() -> tuple[Browser, BrowserContext]:
    global _playwright, _browser, _context

    if _browser is not None and not _browser.is_connected():
        # Chromium died under us (an OOM kill in a small container is the usual cause), or the
        # sidecar dropped the connection. Drop the whole stack rather than handing out pages on
        # a corpse forever.
        logger.warning("Chromium s'est arrêté, redémarrage")
        await _dispose()

    if _playwright is None:
        try:
            _playwright = await asyncio.wait_for(
                async_playwright().start(),
                timeout=settings.scrape_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ScrapeError("Playwright indisponible : délai de démarrage dépassé") from exc
    if _browser is None:
        try:
            if settings.browser_ws_endpoint:
                separator = "&" if "?" in settings.browser_ws_endpoint else "?"
                endpoint = (
                    f"{settings.browser_ws_endpoint}{separator}"
                    f"launch={quote(_REMOTE_LAUNCH_OPTIONS_JSON)}"
                )
                _browser = await asyncio.wait_for(
                    _playwright.chromium.connect_over_cdp(endpoint),
                    timeout=settings.scrape_timeout_seconds,
                )
            else:
                _browser = await asyncio.wait_for(
                    _playwright.chromium.launch(headless=True, args=_LAUNCH_ARGS),
                    timeout=settings.scrape_timeout_seconds,
                )
        except TimeoutError as exc:
            # An unresponsive sidecar (container restarting, network partition…) must not hang
            # this forever under `_lock`: that would freeze every scrape, and — because the manual
            # batch awaits one set at a time — the whole collection price batch right along with it.
            raise ScrapeError(f"Chromium indisponible : délai de connexion dépassé ({exc})") from exc
    if _context is None:
        try:
            context_options = {
                "viewport": _VIEWPORT,
                "locale": "fr-FR",
                "timezone_id": "Europe/Paris",
            }
            if not settings.browser_ws_endpoint:
                # A local headless browser would otherwise advertise HeadlessChrome. The remote
                # headful browser keeps its own native Linux fingerprint coherent end-to-end.
                context_options["user_agent"] = _user_agent(_browser)
            _context = await asyncio.wait_for(
                _browser.new_context(**context_options),
                timeout=settings.scrape_timeout_seconds,
            )
            if _restored_cookies:
                await asyncio.wait_for(
                    _context.add_cookies(list(_restored_cookies.values())),
                    timeout=settings.scrape_timeout_seconds,
                )
        except TimeoutError as exc:
            raise ScrapeError("Chromium indisponible : délai de création du contexte dépassé") from exc
    return _browser, _context


async def _dispose() -> None:
    """Tear the stack down and forget it. Idempotent, and never raises: a shutdown path that can
    fail is a shutdown path that leaves a zombie Chromium behind."""
    global _playwright, _browser, _context

    closers = [
        None if _context is None else _context.close,
        None if _browser is None else _browser.close,
        None if _playwright is None else _playwright.stop,
    ]
    _context, _browser, _playwright = None, None, None

    for close in closers:
        if close is None:
            continue
        try:
            await asyncio.wait_for(close(), timeout=_CLOSE_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("Fermeture Chromium abandonnée après %.0f s", _CLOSE_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - teardown must not mask the caller's own failure
            logger.debug("Fermeture Chromium partielle", exc_info=True)


async def get_browser() -> Browser:
    """The shared Chromium, launched on first use and relaunched if it died."""
    if not settings.scraping_enabled:
        raise ScrapeDisabled(_DISABLED_MESSAGE)
    async with _lock:
        try:
            browser, _ = await _ensure_stack()
        except PlaywrightError as exc:
            raise ScrapeError(f"Chromium indisponible : {exc}") from exc
        return browser


async def shutdown_browser() -> None:
    """Safe to call twice, and safe to call when nothing was ever launched."""
    async with _lock:
        await _dispose()


async def _acquire_page() -> Page:
    async with _lock:
        try:
            _, context = await _ensure_stack()
            return await asyncio.wait_for(
                context.new_page(),
                timeout=settings.scrape_timeout_seconds,
            )
        except (PlaywrightError, ScrapeError) as first_error:
            # The context can outlive its usefulness without the browser reporting a disconnect
            # (a crashed renderer, a context closed from outside). One clean relaunch, then give up.
            # ScrapeError can also be raised if _ensure_stack() timeouts, so we retry on that too.
            logger.warning("Contexte Chromium inutilisable (%s), redémarrage", first_error)
            await _dispose()
            try:
                _, context = await _ensure_stack()
                return await asyncio.wait_for(
                    context.new_page(),
                    timeout=settings.scrape_timeout_seconds,
                )
            except (PlaywrightError, ScrapeError) as exc:
                raise ScrapeError(f"Chromium indisponible : {exc}") from exc
            except TimeoutError as exc:
                raise ScrapeError("Chromium indisponible : délai de création de page dépassé") from exc
        except TimeoutError as exc:
            raise ScrapeError("Chromium indisponible : délai de création de page dépassé") from exc


async def _close_page(page: Page) -> None:
    try:
        await asyncio.wait_for(page.close(), timeout=_CLOSE_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("Fermeture d'une page Chromium abandonnée après %.0f s", _CLOSE_TIMEOUT_SECONDS)
    except PlaywrightError:
        logger.debug("Page déjà fermée", exc_info=True)


async def open_interactive_page(url: str) -> Page:
    """Opens the challenged URL in the shared context for human interaction."""
    page = await _acquire_page()
    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=settings.scrape_timeout_seconds * 1000,
        )
    except PlaywrightTimeoutError:
        # A challenge can keep subresources pending while its visible controls are already usable.
        logger.debug("Page CAPTCHA partiellement chargée : %s", url)
    except PlaywrightError as error:
        await _close_page(page)
        raise ScrapeError(f"Ouverture du CAPTCHA impossible : {url} ({error})") from error
    await _retry_blocked_datadome_frame(page)
    if await _datadome_challenge_state(page) == "blocked":
        await _close_page(page)
        raise InteractiveChallengeUnavailable(
            "DataDome refuse cette session sans proposer de défi résolvable"
        )
    return page


async def _datadome_challenge_state(page: Page) -> str | None:
    for frame in page.frames:
        if "captcha-delivery.com" not in frame.url:
            continue
        try:
            return await frame.evaluate(
                """
() => {
  const text = document.body ? document.body.innerText : '';
  if (/glisser vers la droite|slide to the right|vérification audio|audio verification/i.test(text)) {
    return 'solvable';
  }
  if (Array.from(document.querySelectorAll('button'))
    .some((button) => /retry|réessayer|try again/i.test(button.innerText || ''))) {
    return 'retry';
  }
  if (/you have been blocked|vous avez été bloqué|accès temporairement restreint/i.test(text)) {
    return 'blocked';
  }
  return null;
}
"""
            )
        except PlaywrightError:
            continue
    return None


async def _retry_blocked_datadome_frame(page: Page) -> bool:
    """Turns DataDome's terminal-looking landing state into its actual human challenge.

    This only presses DataDome's own Retry button. The slider/audio verification itself remains a
    human action in the interactive viewer.
    """
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        for frame in page.frames:
            if "captcha-delivery.com" not in frame.url:
                continue
            try:
                clicked = await frame.evaluate(
                    """
() => {
  const retry = Array.from(document.querySelectorAll('button'))
    .find((button) => /retry|réessayer|try again/i.test(button.innerText || ''));
  if (!retry) return false;
  retry.click();
  return true;
}
"""
                )
            except PlaywrightError:
                continue
            if clicked:
                await asyncio.sleep(1)
                return True
            return False
        await asyncio.sleep(_POLL_INTERVAL)
    return False


async def close_interactive_page(page: Page) -> None:
    await _close_page(page)


async def cookies_for_url(url: str) -> list[dict]:
    async with _lock:
        _, context = await _ensure_stack()
        return list(
            await asyncio.wait_for(
                context.cookies([url]),
                timeout=settings.scrape_timeout_seconds,
            )
        )


# --------------------------------------------------------------------------------------
# The single scrape entry point
# --------------------------------------------------------------------------------------


async def load_and_extract(
    url: str,
    readiness_js: str,
    extract_js: str,
    timeout: float | None = None,
    fails_on_http_404: bool = False,
    retry_empty_extraction: bool = False,
) -> str:
    """Load `url`, wait for `readiness_js` to go truthy, then return `extract_js`'s string result.

    `readiness_js` is how a cleared challenge is detected: it must test for something only the real
    page has (lego.com uses `og:title`, absent from the interstitial). `extract_js` should end in a
    `JSON.stringify(...)` so the caller decodes a known shape.

    `fails_on_http_404` opts into raising `ScrapeHttpNotFound` as soon as the page's own response
    comes back 404 — the lego.com path needs "removed from the store" and "challenge never cleared"
    to stay distinguishable instead of both timing out.
    """
    if not settings.scraping_enabled:
        raise ScrapeDisabled(_DISABLED_MESSAGE)

    limit = settings.scrape_timeout_seconds if timeout is None else timeout
    page: Page | None = None
    last_status: int | None = None
    saw_ready_page = False

    def record_status(response: PlaywrightResponse) -> None:
        # Every navigation response, not just the first: after a Cloudflare interstitial (403/503)
        # the browser reloads itself, and it is that later response that says whether the real
        # product page exists.
        nonlocal last_status
        try:
            if response.request.is_navigation_request() and response.frame == page.main_frame:
                last_status = response.status
        except PlaywrightError:
            logger.debug("Réponse sans frame associée, ignorée", exc_info=True)

    try:
        async with asyncio.timeout(limit):
            page = await _acquire_page()
            page.on("response", record_status)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=limit * 1000)
            except PlaywrightTimeoutError as exc:
                # A page that never even reaches DOMContentLoaded is the same user-visible outcome as a
                # challenge that never clears, and the callers' messages say exactly that.
                raise ScrapeChallengeUnsolved(f"Chargement expiré : {url}") from exc
            except PlaywrightError as exc:
                raise ScrapeError(f"Navigation échouée : {url} ({exc})") from exc

            deadline = time.monotonic() + limit
            while time.monotonic() < deadline:
                try:
                    blocked = await page.evaluate(_BLOCKED_JS)
                except PlaywrightError:
                    blocked = None
                if isinstance(blocked, str) and blocked:
                    raise ScrapeBlocked(blocked, url)
                if last_status == 403:
                    try:
                        body_is_empty = await page.evaluate(
                            "() => !document.body || !(document.body.innerText || '').trim()"
                        )
                    except PlaywrightError:
                        body_is_empty = False
                    if body_is_empty:
                        raise ScrapeBlocked("HTTP 403 vide", url)
                if fails_on_http_404 and last_status == 404:
                    raise ScrapeHttpNotFound(f"HTTP 404 : {url}")
                try:
                    ready = await page.evaluate(readiness_js)
                except PlaywrightError:
                    # The challenge's own reload destroys the execution context mid-evaluation; that is
                    # a "not ready yet", not a failure.
                    ready = None
                if ready:
                    saw_ready_page = True
                    try:
                        extracted = await page.evaluate(extract_js)
                    except PlaywrightError as exc:
                        raise ScrapeError(f"Extraction impossible : {url} ({exc})") from exc
                    if not isinstance(extracted, str) or not extracted or extracted == "null":
                        if retry_empty_extraction:
                            await asyncio.sleep(_POLL_INTERVAL)
                            continue
                        raise ScrapeNotFound(f"Rien à extraire : {url}")
                    return extracted
                await asyncio.sleep(_POLL_INTERVAL)

            if saw_ready_page:
                raise ScrapeNotFound(f"Rien à extraire avant l'échéance : {url}")
            raise ScrapeChallengeUnsolved(f"Page jamais prête : {url}")
    except TimeoutError as exc:
        if saw_ready_page:
            raise ScrapeNotFound(f"Rien à extraire avant l'échéance : {url}") from exc
        raise ScrapeChallengeUnsolved(f"Délai global dépassé : {url}") from exc
    finally:
        if page is not None:
            await _close_page(page)


# --------------------------------------------------------------------------------------
# Price string parsing (port of `PriceParsing.swift`)
# --------------------------------------------------------------------------------------

#: Thousands groups are matched explicitly (three digits behind a space, dot or comma) so
#: `"1 174,00 EUR"`, `"1.174,00 EUR"` and `"$1,174.00"` all read as 1174 rather than stopping at
#: the first separator. A trailing group counts as the *decimal* fraction rather than another
#: thousands group precisely when it has one or two digits, not three — that length, not which
#: character it uses, is what disambiguates it. The narrow/non-breaking spaces sites use are
#: normalised to plain spaces first.
_AMOUNT_RE = re.compile(r"(?P<whole>[0-9]+(?:[ .,][0-9]{3})*)(?:[.,](?P<frac>[0-9]{1,2}))?")
_CURRENCY_CODE_RE = re.compile(r"[A-Z]{3}")
_SPACES = (" ", " ", " ")


def parse_amount(raw: str) -> float | None:
    """Best-effort amount out of a scraped price string. Handles the formatting conventions
    actually seen across sites: `"EUR 22.50"`, `"22,50 EUR"`, `"1 174,00 EUR"` (French),
    `"1.174,00 EUR"` (German/Cdiscount) and `"$1,174.00"` (US)."""
    cleaned = raw
    for space in _SPACES:
        cleaned = cleaned.replace(space, " ")
    match = _AMOUNT_RE.search(cleaned)
    if match is None:
        return None
    whole = re.sub(r"[ .,]", "", match.group("whole"))
    frac = match.group("frac")
    number = f"{whole}.{frac}" if frac else whole
    try:
        return float(number)
    except ValueError:
        return None


def parse_currency(raw: str) -> str:
    if "€" in raw:
        return "EUR"
    if "$" in raw:
        return "USD"
    if "£" in raw:
        return "GBP"
    match = _CURRENCY_CODE_RE.search(raw)
    return match.group(0) if match else "EUR"
