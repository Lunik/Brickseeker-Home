"""The screens' endpoints over a real database: what a row says must match what the total says."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from app.config import settings
from app.main import app
from app.services import collection_repo
from app.services.pricing import PriceQuote, PriceSource
from app.services.rebrickable import LegoSet, SetList, UserSet

#: Reachable without a session on purpose: they are how a client finds out it must log in.
PUBLIC_ROUTES = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout"}


def _set(set_num: str, parts: int = 100) -> LegoSet:
    return LegoSet(
        set_num=set_num,
        name=f"Set {set_num}",
        year=2022,
        theme_id=1,
        num_parts=parts,
        set_img_url=None,
        set_url=None,
    )


@pytest.fixture
async def collection(session) -> None:  # noqa: ANN001 - fixture session
    """Two owned sets: one worth 30 € over two copies, one with no price at all."""
    await collection_repo.sync_collection(
        session,
        [
            UserSet(lego_set=_set("10307-1"), quantity=2, include_spares=False, list_id=1),
            UserSet(lego_set=_set("75192-1", parts=50), quantity=1, include_spares=False, list_id=1),
        ],
        [SetList(id=1, name="displayed", num_sets=2)],
    )
    await collection_repo.cache_prices(
        session, [PriceQuote(source=PriceSource.BRICKLINK_NEW, amount=30.0)], "10307-1", reconcile=True
    )


def _every_route() -> list[tuple[str, str]]:
    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if path not in PUBLIC_ROUTES
    ]


@pytest.mark.parametrize(("method", "path"), _every_route())
async def test_every_route_requires_a_session_when_a_password_is_set(client, method: str, path: str) -> None:  # noqa: ANN001
    url = re.sub(r"\{[^}]+\}", "1", path)

    with patch.object(settings, "password", "secret"):
        response = await client.request(method, url)

    assert response.status_code == 401, f"{method} {path} répond {response.status_code}"


async def test_login_opens_the_gate_and_logout_closes_it(client) -> None:  # noqa: ANN001
    with patch.object(settings, "password", "secret"):
        assert (await client.post("/api/auth/login", json={"password": "wrong"})).status_code == 401
        assert (await client.post("/api/auth/login", json={"password": "secret"})).status_code == 200
        assert (await client.get("/api/auth/status")).json()["authenticated"] is True
        assert (await client.get("/api/stats")).status_code == 200

        await client.post("/api/auth/logout")

        assert (await client.get("/api/stats")).status_code == 401


@pytest.mark.usefixtures("collection")
async def test_collection_row_and_statistics_agree_on_the_value(client) -> None:  # noqa: ANN001
    rows = {row["setNum"]: row for row in (await client.get("/api/collection")).json()["sets"]}
    stats = (await client.get("/api/stats")).json()

    assert rows["10307-1"]["resolvedPrice"] == 30.0
    assert rows["75192-1"]["resolvedPrice"] is None
    assert stats["setCount"] == 2
    assert stats["unitCount"] == 3
    assert stats["partCount"] == 250
    assert stats["setsWithKnownPrice"] == 1
    assert stats["totalValueEur"] == 60.0


@pytest.mark.usefixtures("collection")
async def test_csv_export_totals_the_same_value(client) -> None:  # noqa: ANN001
    response = await client.get("/api/stats/export.csv")

    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert any(line.startswith("10307-1;") for line in lines)
    assert lines[-1].startswith("Total")
    assert lines[-1].endswith("60,00")


@pytest.mark.usefixtures("collection")
async def test_pdf_export_is_a_pdf(client) -> None:  # noqa: ANN001
    response = await client.get("/api/stats/export.pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


async def test_typed_lookup_lands_in_history_and_can_be_removed(client, session) -> None:  # noqa: ANN001
    await collection_repo.cache_set(
        session, _set("10307-1"), is_in_collection=False, list_id=None, list_name=None, mark_as_scanned=False
    )

    lookup = await client.post("/api/scan/lookup", json={"setNum": "10307", "source": "manualEntry"})

    assert lookup.json()["set"]["setNum"] == "10307-1"
    assert lookup.json()["scanEventId"] is not None
    history = (await client.get("/api/history")).json()
    assert [row["setNum"] for row in history["sets"]] == ["10307-1"]

    assert (await client.delete("/api/history/10307-1")).status_code == 200
    assert (await client.get("/api/history")).json()["sets"] == []


async def test_reopening_from_a_list_is_not_a_scan(client, session) -> None:  # noqa: ANN001
    await collection_repo.cache_set(
        session, _set("10307-1"), is_in_collection=False, list_id=None, list_name=None, mark_as_scanned=False
    )

    lookup = await client.post("/api/scan/lookup", json={"setNum": "10307-1", "source": "listReopen"})

    assert lookup.json()["scanEventId"] is None
    assert (await client.get("/api/history")).json()["sets"] == []


async def test_alert_lifecycle(client, session) -> None:  # noqa: ANN001
    await collection_repo.cache_set(
        session, _set("10307-1"), is_in_collection=False, list_id=None, list_name=None, mark_as_scanned=False
    )

    created = await client.put(
        "/api/alerts", json={"setNum": "10307-1", "condition": "used", "thresholdEur": 20.0}
    )
    assert created.status_code == 200
    alert_id = created.json()["id"]
    assert created.json()["effectiveThresholdEur"] == 20.0

    await client.patch(f"/api/alerts/{alert_id}", json={"isEnabled": False})
    alerts = (await client.get("/api/alerts/10307-1")).json()["alerts"]
    assert [alert["isEnabled"] for alert in alerts] == [False]

    await client.delete(f"/api/alerts/{alert_id}")
    assert (await client.get("/api/alerts")).json()["alerts"] == []


async def test_paid_price_round_trip(client, session) -> None:  # noqa: ANN001
    await collection_repo.cache_set(
        session, _set("10307-1"), is_in_collection=False, list_id=None, list_name=None, mark_as_scanned=False
    )

    response = await client.put("/api/sets/10307-1/paid-price", json={"paidPriceEur": 12.5})

    assert response.json()["paidPriceEur"] == 12.5
