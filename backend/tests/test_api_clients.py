"""Third-party answer shapes, decoded from canned HTTP responses rather than from a live API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.deps import ApiError
from app.services import bricklink
from app.services.bricklink import BrickLinkClient, CatalogRef
from app.services.pricing import PriceSource
from app.services.rebrickable import (
    BASE_URL,
    Ambiguous,
    Found,
    NotFound,
    RebrickableClient,
    _raise_for_status,
)

SET_PAYLOAD = {"set_num": "10307-1", "name": "Eiffel Tower", "year": 2022, "theme_id": 1, "num_parts": 10001}


def _user_set(set_num: str, list_id: int = 1) -> dict[str, object]:
    lego_set = {**SET_PAYLOAD, "set_num": set_num}
    return {"set": lego_set, "quantity": 2, "include_spares": True, "list_id": list_id}


def _client(*responses: httpx.Response) -> RebrickableClient:
    """A client whose calls answer in order, through the real status handling."""
    client = RebrickableClient("key", "token")

    async def answer(*_args: object, **_kwargs: object) -> httpx.Response:
        response = remaining.pop(0)
        _raise_for_status(response)
        return response

    remaining = list(responses)
    client._request = AsyncMock(side_effect=answer)  # type: ignore[method-assign]
    return client


def _page(results: list[object], following: str | None = None) -> httpx.Response:
    return httpx.Response(200, json={"count": len(results), "next": following, "results": results})


class TestRebrickableResolve:
    async def test_full_number_is_tried_first(self) -> None:
        client = _client(httpx.Response(200, json=SET_PAYLOAD))

        resolution = await client.resolve_set("10307")

        assert isinstance(resolution, Found)
        assert resolution.lego_set.set_num == "10307-1"
        assert "/lego/sets/10307-1/" in client._request.await_args.args[1]

    async def test_several_search_results_are_ambiguous(self) -> None:
        miss = httpx.Response(404)
        other = {**SET_PAYLOAD, "set_num": "10307-2"}
        client = _client(miss, miss, _page([SET_PAYLOAD, other]))

        assert isinstance(await client.resolve_set("10307"), Ambiguous)

    async def test_no_search_result_is_not_found(self) -> None:
        miss = httpx.Response(404)
        client = _client(miss, miss, _page([]))

        assert isinstance(await client.resolve_set("10307"), NotFound)


class TestRebrickableCollection:
    async def test_follows_pagination(self) -> None:
        client = _client(
            _page([_user_set("10307-1")], f"{BASE_URL}/users/token/sets/?page=2"),
            _page([_user_set("75192-1", list_id=2)]),
        )

        rows = await client.fetch_all_user_sets()

        assert [row.set_num for row in rows] == ["10307-1", "75192-1"]
        assert (rows[1].list_id, rows[1].quantity, rows[1].include_spares) == (2, 2, True)

    async def test_never_follows_a_foreign_next_url(self) -> None:
        client = _client(_page([_user_set("10307-1")], "https://evil.example/steal"))

        rows = await client.fetch_all_user_sets()

        assert len(rows) == 1
        assert client._request.await_count == 1

    async def test_a_set_out_of_the_collection_is_not_an_error(self) -> None:
        assert await _client(httpx.Response(404)).fetch_user_set("10307-1") is None

    async def test_collection_needs_a_linked_account(self) -> None:
        with pytest.raises(ApiError) as caught:
            await RebrickableClient("key", None).fetch_all_user_sets()

        assert caught.value.status_code == 412

    @pytest.mark.parametrize(("upstream", "expected"), [(401, 401), (403, 403), (429, 429), (500, 502)])
    async def test_upstream_errors_keep_their_meaning(self, upstream: int, expected: int) -> None:
        with pytest.raises(ApiError) as caught:
            await _client(httpx.Response(upstream)).fetch_set("10307-1")

        assert caught.value.status_code == expected

    async def test_authenticate_keeps_the_token_only(self) -> None:
        client = RebrickableClient("key", None)
        client._request = AsyncMock(return_value=httpx.Response(200, json={"user_token": "abc"}))

        assert await client.authenticate("me", "password") == "abc"


CREDENTIALS = {"consumer_key": "a", "consumer_secret": "b", "token": "c", "token_secret": "d"}


def _bricklink(handler) -> BrickLinkClient:  # noqa: ANN001 - httpx handler
    return BrickLinkClient(CREDENTIALS, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _guide(avg: str, **extra: object) -> dict[str, object]:
    return {
        "meta": {"code": 200, "message": "OK"},
        "data": {
            "currency_code": "EUR",
            "avg_price": avg,
            "min_price": "10.00",
            "max_price": "30.00",
            "qty_avg_price": "99.00",
            "unit_quantity": 4,
            "price_detail": [],
            **extra,
        },
    }


@pytest.fixture(autouse=True)
def no_pacing():  # noqa: ANN201 - a patch
    with patch.object(bricklink.bricklink_throttler, "wait", AsyncMock()):
        yield


class TestBrickLinkQuotes:
    async def test_new_and_used_come_from_the_average_price(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            condition = request.url.params["new_or_used"]
            return httpx.Response(200, json=_guide("20.50" if condition == "N" else "12.00"))

        quotes = await bricklink._quotes_for(_bricklink(handler), CatalogRef("S", "10307-1"))

        by_source = {quote.source: quote for quote in quotes}
        assert by_source[PriceSource.BRICKLINK_NEW].amount == 20.5
        assert by_source[PriceSource.BRICKLINK_USED].amount == 12.0
        assert by_source[PriceSource.BRICKLINK_NEW].min_amount == 10.0
        assert by_source[PriceSource.BRICKLINK_NEW].lot_count == 4

    async def test_a_zero_average_means_no_price(self) -> None:
        handler = lambda _request: httpx.Response(200, json=_guide("0.0000"))  # noqa: E731

        assert await bricklink._quotes_for(_bricklink(handler), CatalogRef("S", "10307-1")) == []

    async def test_one_condition_failing_keeps_the_other(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params["new_or_used"] == "N":
                return httpx.Response(200, json={"meta": {"code": 404, "message": "NOT_FOUND"}})
            return httpx.Response(200, json=_guide("12.00"))

        quotes = await bricklink._quotes_for(_bricklink(handler), CatalogRef("S", "10307-1"))

        assert [quote.source for quote in quotes] == [PriceSource.BRICKLINK_USED]

    async def test_requests_are_signed(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["Authorization"])
            return httpx.Response(200, json=_guide("12.00"))

        await bricklink._quotes_for(_bricklink(handler), CatalogRef("S", "10307-1"))

        assert seen[0].startswith("OAuth ")
        assert 'oauth_consumer_key="a"' in seen[0]
        assert "oauth_signature=" in seen[0]
