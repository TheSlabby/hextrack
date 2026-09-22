"""Ingestion end to end through the real RiotClient over an in-memory httpx transport.

The fake Riot server below never touches the network; it checks that ingestion and the
client agree on routes, parameters and DTOs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from hextrack.db.models import Summoner
from hextrack.ingest.ondemand import get_or_resolve_summoner
from hextrack.ingest.poller import poll_once
from hextrack.ingest.roster import add_to_roster
from hextrack.riot.client import RiotClient
from tests.factories import make_match_json, spec
from tests.test_ingest_support import events_of, make_ctx, recent, snapshots_of, stored_match_ids

ACCOUNTS = {"hex": ("Hex Walker", "NA1"), "amy": ("amy", "0001")}


class FakeRiotServer:
    """Routes the handful of endpoints ingestion uses; records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.matches: dict[str, dict[str, Any]] = {}
        self.forbidden = False

    def add_match(self, raw: dict[str, Any]) -> None:
        self.matches[raw["metadata"]["matchId"]] = raw

    def paths(self, contains: str) -> list[str]:
        return [r.url.path for r in self.requests if contains in r.url.path]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["X-Riot-Token"] == "RGAPI-00000000-test-only"
        if self.forbidden:
            return httpx.Response(
                403, json={"status": {"status_code": 403, "message": "Forbidden"}}
            )
        parts = request.url.path.strip("/").split("/")
        api = (request.url.host.split(".")[0], "/".join(parts[:4]))
        if api == ("americas", "riot/account/v1/accounts"):
            if parts[4] == "by-riot-id":
                wanted = (parts[5].casefold(), parts[6].casefold())
                for puuid, (name, tag) in ACCOUNTS.items():
                    if (name.casefold(), tag.casefold()) == wanted:
                        return httpx.Response(200, json=self._account(puuid))
                return self._not_found()
            if parts[4] == "by-puuid" and parts[5] in ACCOUNTS:
                return httpx.Response(200, json=self._account(parts[5]))
            return self._not_found()
        if api == ("na1", "lol/summoner/v4/summoners"):
            return httpx.Response(
                200,
                json={
                    "puuid": parts[5],
                    "profileIconId": 4568,
                    "summonerLevel": 312,
                    "revisionDate": 1,
                },
            )
        if api == ("na1", "lol/league/v4/entries"):
            return httpx.Response(200, json=[self._league(parts[5])])
        if api == ("americas", "lol/match/v5/matches"):
            if parts[4] == "by-puuid":
                return httpx.Response(200, json=self._ids(parts[5], request))
            raw = self.matches.get(parts[4])
            return httpx.Response(200, json=raw) if raw else self._not_found()
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    def _account(self, puuid: str) -> dict[str, Any]:
        name, tag = ACCOUNTS[puuid]
        return {"puuid": puuid, "gameName": name, "tagLine": tag}

    @staticmethod
    def _league(puuid: str) -> dict[str, Any]:
        return {
            "leagueId": "x",
            "queueType": "RANKED_SOLO_5x5",
            "tier": "EMERALD",
            "rank": "II",
            "puuid": puuid,
            "leaguePoints": 57,
            "wins": 61,
            "losses": 55,
            "veteran": False,
            "inactive": False,
            "freshBlood": False,
            "hotStreak": True,
        }

    def _ids(self, puuid: str, request: httpx.Request) -> list[str]:
        query = parse_qs(request.url.query.decode())
        assert query["type"] == ["ranked"]
        start, count = int(query["start"][0]), int(query["count"][0])
        ids = sorted(
            (
                mid
                for mid, raw in self.matches.items()
                if any(p["puuid"] == puuid for p in raw["info"]["participants"])
            ),
            key=lambda mid: self.matches[mid]["info"]["gameStartTimestamp"],
            reverse=True,
        )
        return ids[start : start + count]

    @staticmethod
    def _not_found() -> httpx.Response:
        return httpx.Response(404, json={"status": {"status_code": 404, "message": "Not found"}})


@pytest.fixture
def server() -> FakeRiotServer:
    return FakeRiotServer()


@pytest.fixture
async def ctx(clean_db, settings, session_factory, server) -> AsyncIterator[Any]:
    keyed = settings.model_copy(
        update={"riot_api_key": "RGAPI-00000000-test-only", "ondemand_max_matches": 2}
    )
    riot = RiotClient(keyed, transport=httpx.MockTransport(server))
    try:
        yield make_ctx(keyed, session_factory, riot)
    finally:
        await riot.aclose()


async def test_lookup_of_a_name_with_a_space(ctx, server, session):
    for i in range(3):
        server.add_match(
            make_match_json(
                f"NA1_{700 + i}", [spec("hex", "Hex Walker", "NA1")], start=recent(i + 1)
            )
        )

    summoner = await get_or_resolve_summoner(ctx, session, "hex walker", "na1")
    await session.commit()

    assert summoner is not None and summoner.puuid == "hex"
    assert (summoner.game_name, summoner.profile_icon_id) == ("Hex Walker", 4568)
    assert server.paths("by-riot-id") == ["/riot/account/v1/accounts/by-riot-id/hex walker/na1"]
    assert any(" " in r.url.path and b"%20" in r.url.raw_path for r in server.requests)
    (snap,) = await snapshots_of(session, "hex")
    assert (snap.tier, snap.rank, snap.lp) == ("EMERALD", "II", 57)
    assert await stored_match_ids(session) == {"NA1_700", "NA1_701"}  # newest 2 (max 2)
    assert ctx.riot.limiter_wait_estimate() >= 0.0


async def test_roster_poll_through_the_real_client(ctx, server, session):
    shared = make_match_json(
        "NA1_800",
        [
            spec("hex", "Hex Walker", "NA1", kills=14, deaths=1, assists=6),
            spec("amy", "amy", "0001"),
        ],
        start=recent(),
    )
    server.add_match(shared)
    await add_to_roster(ctx, session, "Hex Walker#NA1")
    await add_to_roster(ctx, session, "amy#0001")
    await session.commit()

    report = await poll_once(ctx)

    assert (report.summoners, report.new_matches, report.errors) == (2, 1, [])
    assert server.paths("/matches/NA1_800") == ["/lol/match/v5/matches/NA1_800"]
    kinds = sorted((e.kind, e.payload["puuid"]) for e in await events_of(session))
    assert kinds == [("great_game", "hex"), ("new_match", "amy"), ("new_match", "hex")]
    assert ctx.riot.status.key_ok is True


async def test_expired_key_aborts_the_poll_and_flags_health(ctx, server, session):
    await add_to_roster(ctx, session, "Hex Walker#NA1")
    await session.commit()
    server.forbidden = True

    report = await poll_once(ctx)

    assert report.auth_failed is True
    assert ctx.riot.status.key_ok is False
    hex_row = await session.get(Summoner, "hex", populate_existing=True)
    assert hex_row is not None and hex_row.is_tracked
