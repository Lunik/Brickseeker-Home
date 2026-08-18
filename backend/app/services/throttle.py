"""Per-host request spacing — port of the iOS `RequestThrottler` actor.

One instance per remote host, never a shared global: the hosts are unrelated, and a collection
sync hammering Rebrickable must not slow down a BrickLink price call happening at the same time.
The intervals themselves are tuned per host in `config.py` (Brickset in particular answers HTTP
429 to a back-to-back pair spaced only 0.2 s apart — confirmed live on device).
"""

from __future__ import annotations

import asyncio
import time

from ..config import settings


class Throttler:
    """Guarantees at least `minimum_interval` seconds between two calls to `wait()`."""

    def __init__(self, minimum_interval: float) -> None:
        self._minimum_interval = minimum_interval
        self._lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def wait(self) -> None:
        # The sleep happens *inside* the lock on purpose. Releasing it first would let every
        # waiting task compute the same delay against the same timestamp and then fire together —
        # the exact burst the throttler exists to prevent. Holding it makes N concurrent callers
        # queue up one interval apart.
        async with self._lock:
            if self._last_request_at is not None:
                # Monotonic, not wall clock: an NTP correction mid-batch would otherwise either
                # stall the throttler for hours or disable the spacing entirely.
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self._minimum_interval:
                    await asyncio.sleep(self._minimum_interval - elapsed)
            self._last_request_at = time.monotonic()


rebrickable_throttler = Throttler(settings.rebrickable_min_interval)
brickset_throttler = Throttler(settings.brickset_min_interval)
bricklink_throttler = Throttler(settings.bricklink_min_interval)
