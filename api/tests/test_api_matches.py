"""GET /matches/{match_id}."""

from __future__ import annotations

import copy

import pytest

from tests.factories import make_match_json, spec
from tests.test_api_support import add_match, add_summoner, score_all

ME = "puuid-me"


async def test_match_detail(client, session, match_sample):
    tracked = match_sample["info"]["participants"][3]
    await add_summoner(
        session,
        tracked["puuid"],
        tracked["riotIdGameName"],
        tracked["riotIdTagline"],
        tracked=True,
    )
    await add_match(session, match_sample, scores=score_all(match_sample), model_version="v1")
    await session.commit()
    match_id = match_sample["metadata"]["matchId"]
    info = match_sample["info"]

    resp = await client.get(f"/api/v1/matches/{match_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["match_id"] == match_id
    assert body["queue_id"] == info["queueId"]
    assert body["game_mode"] == info["gameMode"]
    assert body["game_version"] == info["gameVersion"]
    assert body["patch"] == ".".join(info["gameVersion"].split(".")[:2])
    assert body["game_duration"] == info["gameDuration"]
    assert body["remake"] is False
    assert body["model_version"] is None  # matches.scored_at/model_version untouched here

    teams = body["teams"]
    assert [t["team_id"] for t in teams] == [100, 200]
    raw_teams = {t["teamId"]: t for t in info["teams"]}
    for team in teams:
        raw = raw_teams[team["team_id"]]
        members = [p for p in info["participants"] if p["teamId"] == team["team_id"]]
        assert team["win"] == raw["win"]
        assert team["kills"] == sum(p["kills"] for p in members)
        assert [p["puuid"] for p in team["participants"]] == [p["puuid"] for p in members]
        objectives = team["objectives"]
        for field, key in (
            ("baron", "baron"),
            ("dragon", "dragon"),
            ("rift_herald", "riftHerald"),
            ("tower", "tower"),
            ("inhibitor", "inhibitor"),
            ("champion", "champion"),
        ):
            assert objectives[field] == {
                "first": raw["objectives"][key]["first"],
                "kills": raw["objectives"][key]["kills"],
            }
        ordered = sorted(raw["bans"], key=lambda b: b["pickTurn"])
        assert team["bans"] == [b["championId"] for b in ordered]

    everyone = teams[0]["participants"] + teams[1]["participants"]
    assert sorted(p["ai_rank"] for p in everyone) == list(range(1, 11))
    flags = {p["puuid"]: p["is_tracked"] for p in everyone}
    assert flags[tracked["puuid"]] is True and sum(flags.values()) == 1


async def test_match_detail_old_payload_objectives(client, session):
    raw = make_match_json("NA1_77", [spec(ME)])
    for team in raw["info"]["teams"]:
        del team["objectives"]["atakhan"]
        del team["objectives"]["horde"]
        team["bans"] = []
    await add_match(session, raw)
    await session.commit()
    body = (await client.get("/api/v1/matches/NA1_77")).json()
    for team in body["teams"]:
        assert team["objectives"]["atakhan"] is None
        assert team["objectives"]["horde"] == {"first": False, "kills": 0}
        assert team["bans"] == []
        assert all(p["ai_score"] is None and p["ai_rank"] is None for p in team["participants"])


async def test_match_detail_atakhan_and_bans(client, session):
    raw = make_match_json("NA1_78", [spec(ME)], winning_team=200)
    blue = raw["info"]["teams"][0]
    blue["bans"] = list(reversed(blue["bans"]))  # pick-turn order must be restored
    await add_match(session, copy.deepcopy(raw))
    await session.commit()
    body = (await client.get("/api/v1/matches/NA1_78")).json()
    blue_body, red_body = body["teams"]
    assert blue_body["win"] is False and red_body["win"] is True
    assert blue_body["bans"] == [157, 238, 84, -1, 350]
    assert red_body["objectives"]["atakhan"] == {"first": True, "kills": 1}
    assert blue_body["objectives"]["atakhan"] == {"first": False, "kills": 0}


@pytest.mark.parametrize("match_id", ["NA1_404", "EUW1_1"])
async def test_match_detail_404(client, match_id):
    resp = await client.get(f"/api/v1/matches/{match_id}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


async def test_match_detail_remake(client, session):
    await add_match(session, make_match_json("NA1_79", [spec(ME)], remake=True, duration_s=190))
    await session.commit()
    body = (await client.get("/api/v1/matches/NA1_79")).json()
    assert body["remake"] is True


async def test_arena_kill_participation_uses_the_real_duo(client, session):
    """Riot puts Arena's eight duos into teamId 100 (placements 1-4) and 200 (5-8). Kill
    participation measured against those halves divides by four unrelated duos' kills; the
    duo a player was on is playerSubteamId."""
    raw = make_match_json("NA1_700", game_mode="CHERRY", queue_id=1700, duration_s=1020)
    raw["info"]["participants"] = raw["info"]["participants"][:8]
    for index, participant in enumerate(raw["info"]["participants"]):
        participant["teamId"] = 100 if index < 4 else 200
        participant["playerSubteamId"] = index // 2 + 1
        participant["placement"] = index + 1
        participant["kills"] = 10
        participant["assists"] = 0
        participant["win"] = index < 4
    await add_summoner(session, raw["info"]["participants"][0]["puuid"], "Arena Fan", "NA1")
    await add_match(session, raw)
    await session.commit()

    body = (await client.get("/api/v1/matches/NA1_700")).json()

    players = [p for team in body["teams"] for p in team["participants"]]
    assert [p["subteam_id"] for p in players] == [1, 1, 2, 2, 3, 3, 4, 4]
    assert [p["placement"] for p in players] == list(range(1, 9))
    # 10 of the duo's 20 kills, not 10 of a made-up 40-kill "team".
    assert {p["kill_participation"] for p in players} == {0.5}


async def test_summoners_rift_participants_have_no_subteam_or_placement(
    client, session, match_sample
):
    await add_summoner(session, match_sample["info"]["participants"][0]["puuid"], "Rift", "NA1")
    await add_match(session, match_sample)
    await session.commit()
    body = (await client.get(f"/api/v1/matches/{match_sample['metadata']['matchId']}")).json()
    players = [p for team in body["teams"] for p in team["participants"]]
    assert all(p["subteam_id"] is None and p["placement"] is None for p in players)


# --- input validation ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/matches/NA1_%00",
        "/api/v1/summoners/%00/matches",
        "/api/v1/summoners/by-riot-id/a%00b/NA1",
        "/api/v1/search?q=%00",
        "/api/v1/summoners/puuid-me/matches?queue=2147483648",
        "/api/v1/summoners/puuid-me/matches?queue=99999999999",
        "/api/v1/summoners/puuid-me/matches?cursor=" + "MTc1fE5BMV8A",  # match id with a NUL
    ],
)
async def test_unusable_input_is_rejected_with_an_error_body(client, session, path):
    """A NUL byte reaches asyncpg as invalid UTF-8 and a queue id above int32 overflows the
    bind parameter: both used to answer a plain-text 500."""
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()
    resp = await client.get(path)
    assert resp.status_code in (400, 404, 422), (path, resp.status_code, resp.text)
    body = resp.json()
    assert isinstance(body["detail"], str) and "code" in body
