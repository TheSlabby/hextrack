"""Contract checks for the squad / insights / records routes: paths, query parameters and
input validation. Behaviour of each endpoint is tested in its own test module."""

from __future__ import annotations

import pytest

from tests.test_api_support import add_summoner

P = "puuid-contract"

NEW_ROUTES = {
    "/api/v1/squad/pairs": {"since", "queue"},
    "/api/v1/squad/stacks": {"since", "queue", "size"},
    "/api/v1/squad/stacks/games": {"since", "queue", "size", "cursor", "limit"},
    "/api/v1/squad/recent": {"cursor", "limit"},
    "/api/v1/summoners/{puuid}/insights/sessions": {"puuid", "since", "queue", "gap_minutes"},
    "/api/v1/summoners/{puuid}/insights/schedule": {"puuid", "since", "queue", "tz"},
    "/api/v1/summoners/{puuid}/insights/matchups": {"puuid", "since", "queue", "min_games"},
    "/api/v1/summoners/{puuid}/insights/luck": {"puuid", "since", "queue", "limit"},
    "/api/v1/records": {"since", "queue", "puuid", "limit"},
}


async def test_new_routes_in_openapi(client):
    spec = (await client.get("/api/openapi.json")).json()
    for path, params in NEW_ROUTES.items():
        assert path in spec["paths"], path
        get = spec["paths"][path]["get"]
        assert {p["name"] for p in get.get("parameters", [])} == params, path


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/squad/pairs?since=ever",
        "/api/v1/squad/pairs?queue=aram",
        "/api/v1/squad/stacks?size=2",
        "/api/v1/squad/stacks?size=6",
        "/api/v1/squad/stacks?queue=solo",
        "/api/v1/squad/stacks/games?size=2",
        "/api/v1/squad/stacks/games?size=6",
        "/api/v1/squad/stacks/games?queue=solo",
        "/api/v1/squad/stacks/games?limit=0",
        "/api/v1/squad/stacks/games?limit=51",
        "/api/v1/squad/recent?limit=0",
        "/api/v1/squad/recent?limit=21",
        f"/api/v1/summoners/{P}/insights/sessions?gap_minutes=5",
        f"/api/v1/summoners/{P}/insights/sessions?gap_minutes=181",
        f"/api/v1/summoners/{P}/insights/schedule?tz=Not%20A%20Zone",
        f"/api/v1/summoners/{P}/insights/matchups?min_games=0",
        f"/api/v1/summoners/{P}/insights/luck?limit=21",
        "/api/v1/records?limit=0",
        "/api/v1/records?limit=11",
        "/api/v1/records?since=last_week",
    ],
)
async def test_invalid_query_is_rejected(client, session, url):
    await add_summoner(session, P, "Contract", "NA1", tracked=True)
    await session.commit()
    assert (await client.get(url)).status_code == 422, url


async def test_unknown_time_zone_is_400(client, session):
    await add_summoner(session, P, "Contract", "NA1", tracked=True)
    await session.commit()
    resp = await client.get(f"/api/v1/summoners/{P}/insights/schedule?tz=Mars/Olympus_Mons")
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_tz"


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/summoners/nobody/insights/sessions",
        "/api/v1/summoners/nobody/insights/schedule",
        "/api/v1/summoners/nobody/insights/matchups",
        "/api/v1/summoners/nobody/insights/luck",
        "/api/v1/records?puuid=nobody",
    ],
)
async def test_unknown_summoner_is_404(client, url):
    resp = await client.get(url)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
