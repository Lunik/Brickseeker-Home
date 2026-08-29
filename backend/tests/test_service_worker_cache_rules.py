"""What the service worker caches for offline use, checked against the real route table.

This exists because of a bug in the same family as the one `test_routes.py` guards — invisible
from the UI, silent, and uncatchable by types or the build. The worker's allow-list was written as
`/^\\/api\\/(…|new-sets|minifigs|…)/`, but those screens live at `/api/catalog/new-sets` and
`/api/catalog/minifigs`: the two entries matched nothing at all, so *Nouveaux sets* and the minifig
gallery quietly had no cached responses, while `/api/settings`, `/api/stats` and `/api/alerts` had
never been listed in the first place. Nothing failed; the screens simply had less offline data than
they appeared to.

The patterns are read out of `sw-src/sw.js` itself rather than restated here — a copy in this file
would be free to drift from the worker, which is exactly the failure being guarded against. JS and
Python regex syntax coincide for the constructs used there (anchors, alternation, `\\/`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.main import app

_SERVICE_WORKER = Path(__file__).resolve().parents[2] / "frontend" / "sw-src" / "sw.js"


def _pattern(name: str) -> re.Pattern[str]:
    """The named JS regex literal from the worker source, compiled with Python's `re`."""
    source = _SERVICE_WORKER.read_text(encoding="utf-8")
    # The literal may sit on the line after `const NAME =`; its body may contain escaped slashes.
    match = re.search(rf"const {name}\s*=\s*\n?\s*/((?:[^/\\\n]|\\.)+)/", source)
    assert match, f"{name} not found in {_SERVICE_WORKER}"
    return re.compile(match.group(1))


def _is_cached(path: str) -> bool:
    return bool(_pattern("CACHEABLE_API").match(path)) and not bool(
        _pattern("UNCACHEABLE_API").match(path)
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/collection",
        "/api/collection/lists",
        "/api/history",
        "/api/wishlist",
        "/api/settings",
        "/api/stats",
        "/api/alerts",
        "/api/catalog/status",
        "/api/catalog/themes",
        "/api/catalog/new-sets",
        "/api/catalog/minifigs",
        "/api/sets/10307-1",
        "/api/prices/10307-1",
        "/api/minifigs/fig-000001/sets",
    ],
)
def test_offline_readable_endpoints_are_cached(path: str) -> None:
    """Everything a screen must still render with no backend reachable."""
    assert _is_cached(path), f"{path} would not be cached for offline use"


@pytest.mark.parametrize(
    "path",
    [
        # Must always be checked live: a cached 200 would let a password-gated instance skip its
        # own login gate while offline.
        "/api/auth/status",
        # Pulled into IndexedDB by application code; duplicating a multi-megabyte export in the
        # HTTP cache buys nothing.
        "/api/catalog/export",
        # Transient progress reads — a cached "63 % done" from yesterday is worse than no answer,
        # the same reason `lib/query-persistence.ts` refuses to persist them.
        "/api/prices/batch/status",
        "/api/prices/interactive/operation",
        "/api/prices/captcha/challenge/frame",
        "/api/wishlist/import/status",
        # File downloads, and the reachability probe.
        "/api/stats/export.csv",
        "/api/stats/export.pdf",
        "/api/health",
        # Meaningless offline.
        "/api/notifications",
    ],
)
def test_deliberately_uncached_endpoints_are_not_cached(path: str) -> None:
    assert not _is_cached(path), f"{path} must not be served from the offline cache"


def test_every_cached_pattern_matches_a_real_route() -> None:
    """No dead entry in the allow-list.

    The original bug was precisely an alternative that matched no route in the schema, so it is
    the alternatives themselves — not just a sample of paths — that have to be checked.
    """
    paths = app.openapi()["paths"]
    concrete = [re.sub(r"\{[^}]+\}", "x", path) for path in paths]

    body = _pattern("CACHEABLE_API").pattern
    alternatives = re.search(r"\(([^)]*)\)", body).group(1).split("|")

    dead = [
        alternative
        for alternative in alternatives
        if not any(path.startswith(f"/api/{alternative}") for path in concrete)
    ]
    assert not dead, f"Allow-list entries matching no route: {dead}"


def test_sets_prefix_does_not_swallow_settings() -> None:
    """`sets` and `settings` share a prefix; only a segment-anchored pattern tells them apart, and
    getting it wrong would cache `/api/settings` under the wrong intent (or not at all)."""
    assert _is_cached("/api/settings")
    assert _is_cached("/api/sets/10307-1")
