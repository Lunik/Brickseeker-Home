"""Route-table invariants.

These exist because of a bug that was invisible from the UI: `POST /collection/bulk` was declared
*after* `POST /collection/{set_num}`, and Starlette matches in declaration order with no preference
for literal paths — so every bulk action was dispatched to `add_to_collection(set_num="bulk")` and
silently did the wrong thing. Nothing about the frontend, the types or the build could catch it.
"""

from __future__ import annotations

import re

import pytest

from app.main import app


def _routes() -> list[tuple[str, str]]:
    """Every (method, path) in declaration order, with the `/api` prefix applied.

    Read off the OpenAPI schema rather than `app.routes`: FastAPI wraps included routers in an
    opaque object whose children are not exposed, and whose own paths lack the mount prefix. The
    schema is the stable public surface, and its `paths` dict preserves declaration order.
    """
    ordered: list[tuple[str, str]] = []
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method.lower() in {"get", "post", "put", "patch", "delete"}:
                ordered.append((method.upper(), path))
    return ordered


def test_no_literal_route_is_shadowed_by_an_earlier_parameterised_one() -> None:
    """A literal segment declared after a parameterised one at the same position is unreachable."""
    seen_parameterised: dict[tuple[str, int, str], str] = {}
    shadowed: list[str] = []

    for method, path in _routes():
        segments = path.strip("/").split("/")
        for index, segment in enumerate(segments):
            prefix = "/".join(segments[:index])
            key = (method, index, prefix)
            if segment.startswith("{"):
                seen_parameterised.setdefault(key, path)
            elif key in seen_parameterised:
                shadowed.append(f"{method} {path} is shadowed by earlier {seen_parameterised[key]}")

    assert not shadowed, "Unreachable routes:\n  " + "\n  ".join(shadowed)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/collection/bulk"),
        ("POST", "/api/wishlist/import"),
        ("GET", "/api/wishlist/import/status"),
        ("GET", "/api/prices/batch/status"),
        ("POST", "/api/prices/batch/start"),
        ("POST", "/api/prices/batch/cancel"),
        ("POST", "/api/prices/deal-verdict"),
        ("GET", "/api/images/proxy"),
        ("GET", "/api/sets/resolve"),
        ("GET", "/api/sets/search"),
        ("GET", "/api/collection/lists"),
        ("GET", "/api/stats/export.csv"),
        ("GET", "/api/catalog/status"),
        ("POST", "/api/catalog/sets/download"),
    ],
)
def test_literal_routes_resolve_to_themselves(method: str, path: str) -> None:
    """The first matching route for each literal path must be that literal path.

    Mirrors how Starlette dispatches, so a future reorder that reintroduces shadowing fails here
    rather than in production.
    """
    for candidate_method, candidate_path in _routes():
        if candidate_method != method:
            continue
        pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", candidate_path) + "$"
        if re.match(pattern, path):
            assert candidate_path == path, (
                f"{method} {path} is dispatched to {candidate_path} — declare the literal route first"
            )
            return
    pytest.fail(f"{method} {path} matches no route")
