"""Profile, refresh, match history and rank history routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import pytest
from sqlalchemy import event, select, update

from hextrack.db.models import Summoner
from hextrack.ingest import ondemand
from hextrack.ingest.ondemand import RefreshOutcome
from hextrack.riot.errors import RiotForbidden, RiotRateLimited
from hextrack.stats.queries import MatchCursor, decode_cursor, encode_cursor
from tests.factories import make_match_json, match_series, spec
from tests.fakes import install_fakes
from tests.test_api_support import add_match, add_model, add_rank, add_summoner, score_all

ME = "puuid-me"
FRIEND = "puuid-friend"
SEASON = datetime(2026, 3, 1, 20, tzinfo=UTC)
PRESEASON = datetime(2025, 12, 1, 20, tzinfo=UTC)
AHRI = (103, "Ahri")
LEE = (64, "LeeSin")


def profile_url(game_name: str, tag_line: str) -> str:
    return f"/api/v1/summoners/by-riot-id/{quote(game_name, safe='')}/{quote(tag_line, safe='')}"


def _me(raw: dict[str, Any], puuid: str = ME) -> dict[str, Any]:
    return next(p for p in raw["info"]["participants"] if p["puuid"] == puuid)


def _kill_participation(raw: dict[str, Any], puuid: str = ME) -> float:
    me = _me(raw, puuid)
    team_kills = sum(p["kills"] for p in raw["info"]["participants"] if p["teamId"] == me["teamId"])
    return (me["kills"] + me["assists"]) / team_kills


def _per_min(raw: dict[str, Any], value: float) -> float:
    return value * 60 / raw["info"]["gameDuration"]


async def seed_profile(session) -> dict[str, dict[str, Any]]:
    """ME with 3 counted season games (+ remakes, preseason and ARAM that must not count)."""
    await add_summoner(
        session,
        ME,
        "Hex Walker",
        "NA1",
        tracked=True,
        profile_icon_id=4568,
        summoner_level=312,
        last_refreshed_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    await add_summoner(session, FRIEND, "Friend", "NA1", tracked=True)
    await add_model(session, "v1")
    friend = spec(FRIEND, "Friend", "NA1")
    matches = {
        "m1": make_match_json(
            "NA1_1",
            [
                spec(
                    ME,
                    "Hex Walker",
                    "NA1",
                    champion=AHRI,
                    position="MIDDLE",
                    kills=10,
                    deaths=2,
                    assists=5,
                ),
                friend,
            ],
            start=SEASON,
            winning_team=100,
        ),
        "m2": make_match_json(
            "NA1_2",
            [
                spec(
                    ME,
                    "Hex Walker",
                    "NA1",
                    champion=AHRI,
                    position="MIDDLE",
                    kills=3,
                    deaths=6,
                    assists=4,
                )
            ],
            queue_id=440,
            start=SEASON + timedelta(days=1),
            winning_team=200,
        ),
        "m3": make_match_json(
            "NA1_3",
            [
                spec(
                    ME,
                    "Hex Walker",
                    "NA1",
                    champion=LEE,
                    position="JUNGLE",
                    kills=6,
                    deaths=3,
                    assists=9,
                )
            ],
            start=SEASON + timedelta(days=2),
            winning_team=100,
        ),
        "remake": make_match_json(
            "NA1_4",
            [spec(ME, "Hex Walker", "NA1")],
            start=SEASON + timedelta(days=3),
            remake=True,
            duration_s=200,
        ),
        "short": make_match_json(
            "NA1_5",
            [spec(ME, "Hex Walker", "NA1")],
            start=SEASON + timedelta(days=4),
            duration_s=240,
        ),
        "preseason": make_match_json(
            "NA1_6", [spec(ME, "Hex Walker", "NA1")], start=PRESEASON, winning_team=100
        ),
        "aram": make_match_json(
            "NA1_7",
            [spec(ME, "Hex Walker", "NA1", champion=LEE)],
            queue_id=450,
            game_mode="ARAM",
            start=SEASON + timedelta(days=5),
        ),
    }
    await add_match(session, matches["m1"], scores={ME: 0.75, FRIEND: 0.6})
    # Scores from a non-active model version never enter the averages.
    await add_match(session, matches["m2"], scores={ME: 0.4}, model_version="v0")
    await add_match(session, matches["m3"], scores={ME: 0.55})
    for key in ("remake", "short", "preseason", "aram"):
        await add_match(session, matches[key])
    await add_rank(session, ME, "RANKED_SOLO_5x5", "GOLD", "II", 40, taken_at=SEASON)
    # The newest rows are what the poller wrote at the last refresh (a queue Riot still
    # reports gets a row at least every 24 h).
    await add_rank(
        session,
        ME,
        "RANKED_SOLO_5x5",
        "GOLD",
        "I",
        75,
        taken_at=datetime.now(UTC) - timedelta(minutes=5),
        wins=30,
        losses=20,
    )
    # Apex tiers have no division, even if a row stored Riot's placeholder "I".
    await add_rank(
        session,
        ME,
        "RANKED_FLEX_SR",
        "MASTER",
        "I",
        120,
        taken_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    await session.commit()
    return matches


# --- profile ---------------------------------------------------------------------------------


async def test_profile_season_aggregates(client, session):
    matches = await seed_profile(session)
    resp = await client.get(profile_url("Hex Walker", "NA1"))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["puuid"] == ME
    assert body["game_name"] == "Hex Walker" and body["tag_line"] == "NA1"
    assert body["platform"] == "na1"
    assert body["profile_icon_id"] == 4568 and body["summoner_level"] == 312
    assert body["is_tracked"] is True and body["tracked_since"] is not None

    counted = [matches["m1"], matches["m2"], matches["m3"]]
    stats = body["stats"]
    assert stats["games"] == 3 and stats["wins"] == 2 and stats["losses"] == 1
    assert stats["winrate"] == pytest.approx(2 / 3, abs=1e-4)
    assert stats["avg_kills"] == pytest.approx(19 / 3, abs=1e-4)
    assert stats["avg_deaths"] == pytest.approx(11 / 3, abs=1e-4)
    assert stats["avg_assists"] == pytest.approx(18 / 3, abs=1e-4)
    assert stats["kda"] == pytest.approx((19 + 18) / 11, abs=1e-4)
    expected_cs = [
        _per_min(m, _me(m)["totalMinionsKilled"] + _me(m)["neutralMinionsKilled"]) for m in counted
    ]
    assert stats["avg_cs_per_min"] == pytest.approx(sum(expected_cs) / 3, abs=1e-3)
    expected_dmg = [_per_min(m, _me(m)["totalDamageDealtToChampions"]) for m in counted]
    assert stats["avg_damage_per_min"] == pytest.approx(sum(expected_dmg) / 3, abs=1e-3)
    expected_vision = [_per_min(m, _me(m)["visionScore"]) for m in counted]
    assert stats["avg_vision_per_min"] == pytest.approx(sum(expected_vision) / 3, abs=1e-3)
    expected_kp = sum(_kill_participation(m) for m in counted) / 3
    assert stats["avg_kill_participation"] == pytest.approx(expected_kp, abs=1e-3)
    # v1 is active: only the two v1 scores count.
    assert stats["avg_ai_score"] == pytest.approx((0.75 + 0.55) / 2)
    assert stats["ai_scored_games"] == 2

    champs = body["top_champions"]
    assert [c["champion_name"] for c in champs] == ["Ahri", "LeeSin"]
    ahri = champs[0]
    assert ahri["champion_id"] == 103 and ahri["games"] == 2 and ahri["wins"] == 1
    assert ahri["winrate"] == 0.5
    assert ahri["kda"] == pytest.approx((13 + 9) / 8, abs=1e-4)
    assert ahri["avg_ai_score"] == pytest.approx(0.75)
    assert body["main_champion"] == "Ahri"

    assert body["roles"] == [
        {"position": "MIDDLE", "games": 2, "wins": 1, "winrate": 0.5},
        {"position": "JUNGLE", "games": 1, "wins": 1, "winrate": 1.0},
    ]
    # Ranked, non-remake, newest first; the preseason game counts for form.
    assert body["recent_form"] == [True, False, True, True]

    solo = body["solo"]
    assert solo["tier"] == "GOLD" and solo["rank"] == "I" and solo["lp"] == 75
    assert solo["wins"] == 30 and solo["losses"] == 20 and solo["winrate"] == 0.6
    assert solo["rank_value"] == 3 * 400 + 3 * 100 + 75
    flex = body["flex"]
    assert flex["tier"] == "MASTER" and flex["rank"] is None and flex["rank_value"] == 2920

    can_refresh = datetime.fromisoformat(body["can_refresh_at"])
    last = datetime.fromisoformat(body["last_refreshed_at"])
    assert can_refresh - last == timedelta(seconds=120)


async def test_profile_is_case_and_whitespace_insensitive(client, session):
    await seed_profile(session)
    for name, tag in (("hex walker", "na1"), ("HEX  WALKER ", "Na1"), (" Hex Walker", "NA1")):
        resp = await client.get(profile_url(name, tag))
        assert resp.status_code == 200, (name, tag, resp.text)
        assert resp.json()["puuid"] == ME


async def test_profile_unicode_riot_id(client, session):
    await add_summoner(session, "puuid-uni", "Ünïcode Náme", "ÉUW")
    await session.commit()
    resp = await client.get(profile_url("ünïcode náme", "éuw"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["puuid"] == "puuid-uni" and body["game_name"] == "Ünïcode Náme"
    # No games at all: zeros, no champion, never refreshed.
    assert body["stats"]["games"] == 0 and body["stats"]["kda"] == 0
    assert body["stats"]["avg_ai_score"] is None and body["stats"]["ai_scored_games"] == 0
    assert body["top_champions"] == [] and body["roles"] == [] and body["recent_form"] == []
    assert body["main_champion"] is None
    assert body["solo"] is None and body["flex"] is None
    assert body["can_refresh_at"] is None


async def test_profile_main_champion_falls_back_to_any_queue(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    raw = make_match_json(
        "NA1_9", [spec(ME, champion=(222, "Jinx"))], queue_id=450, game_mode="ARAM"
    )
    await add_match(session, raw)
    await session.commit()
    body = (await client.get(profile_url("Hex Walker", "NA1"))).json()
    assert body["stats"]["games"] == 0
    assert body["main_champion"] == "Jinx"


async def test_profile_unknown_resolves_through_ondemand(client, session, monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_resolve(ctx, s, game_name, tag_line):
        calls.append((game_name, tag_line))
        summoner = Summoner(puuid="puuid-new", game_name="New Guy", tag_line="NA1", platform="na1")
        s.add(summoner)
        await s.flush()
        return summoner

    monkeypatch.setattr(ondemand, "get_or_resolve_summoner", fake_resolve)
    resp = await client.get(profile_url("New  Guy", "na1"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["puuid"] == "puuid-new"
    assert calls == [("New Guy", "na1")]
    # The route committed the newly resolved summoner.
    assert await session.scalar(select(Summoner.game_name).where(Summoner.puuid == "puuid-new"))


async def test_profile_unknown_account_is_404(client, monkeypatch):
    async def not_found(ctx, s, game_name, tag_line):
        return None

    monkeypatch.setattr(ondemand, "get_or_resolve_summoner", not_found)
    resp = await client.get(profile_url("Nobody", "NA1"))
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


async def test_profile_riot_errors_propagate(client, monkeypatch):
    async def rate_limited(ctx, s, game_name, tag_line):
        raise RiotRateLimited(retry_after=4)

    monkeypatch.setattr(ondemand, "get_or_resolve_summoner", rate_limited)
    resp = await client.get(profile_url("Nobody", "NA1"))
    assert resp.status_code == 429 and resp.json()["code"] == "riot_rate_limited"
    assert resp.headers["Retry-After"] == "4"

    async def forbidden(ctx, s, game_name, tag_line):
        raise RiotForbidden("expired", status=403)

    monkeypatch.setattr(ondemand, "get_or_resolve_summoner", forbidden)
    resp = await client.get(profile_url("Nobody", "NA1"))
    assert resp.status_code == 503 and resp.json()["code"] == "riot_key"


async def test_profile_known_player_never_calls_riot(client, session, fake_riot, monkeypatch):
    await seed_profile(session)

    async def boom(*args, **kwargs):
        raise AssertionError("known players must be served from the database")

    monkeypatch.setattr(ondemand, "get_or_resolve_summoner", boom)
    assert (await client.get(profile_url("Hex Walker", "NA1"))).status_code == 200
    assert fake_riot.calls == []


async def test_profile_invalid_riot_id_is_400(client):
    resp = await client.get(profile_url("Hex Walker", "X"))
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_riot_id"
    resp = await client.get(profile_url("Hex#Walker", "NA1"))
    assert resp.status_code == 400


# --- refresh ---------------------------------------------------------------------------------


async def test_refresh_reports_outcome_and_fresh_profile(client, session, monkeypatch):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()
    refreshed_at = datetime.now(UTC)
    calls: list[str] = []

    async def fake_refresh(ctx, s, puuid):
        calls.append(puuid)
        await s.execute(
            update(Summoner)
            .where(Summoner.puuid == puuid)
            .values(last_refreshed_at=refreshed_at, summoner_level=321)
        )
        return RefreshOutcome(
            status="partial",
            new_matches=10,
            pending=4,
            next_allowed_at=refreshed_at + timedelta(seconds=120),
            message="Ingested 10 matches; 4 more queued",
        )

    monkeypatch.setattr(ondemand, "refresh_on_demand", fake_refresh)
    resp = await client.post(profile_url("hex walker", "NA1") + "/refresh")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert calls == [ME]
    assert body["status"] == "partial"
    assert body["new_matches"] == 10 and body["pending"] == 4
    assert body["message"].startswith("Ingested")
    assert datetime.fromisoformat(body["next_allowed_at"]) == refreshed_at + timedelta(seconds=120)
    profile = body["profile"]
    assert profile["summoner_level"] == 321
    assert datetime.fromisoformat(profile["can_refresh_at"]) == refreshed_at + timedelta(
        seconds=120
    )


async def test_refresh_unknown_is_404(client, monkeypatch):
    async def not_found(ctx, s, game_name, tag_line):
        return None, None

    monkeypatch.setattr(ondemand, "resolve_summoner", not_found)
    resp = await client.post(profile_url("Nobody", "NA1") + "/refresh")
    assert resp.status_code == 404


async def test_refresh_first_lookup_reports_initial_ingest_not_cooldown(
    client, fake_riot, monkeypatch
):
    """Update on a never-seen player: the resolve's first bounded refresh is the outcome."""
    account = fake_riot.add_account("Fresh Face", "NA1")
    fake_riot.add_league_entry(account.puuid, "RANKED_SOLO_5x5", "GOLD", "II", 40)

    async def must_not_run(ctx, s, puuid):
        raise AssertionError("refresh_on_demand must not run right after the first resolve")

    monkeypatch.setattr(ondemand, "refresh_on_demand", must_not_run)
    resp = await client.post(profile_url("fresh face", "na1") + "/refresh")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["pending"] == 0
    assert body["profile"]["puuid"] == account.puuid

    # The next click falls within the cooldown and is reported as such.
    monkeypatch.undo()
    resp = await client.post(profile_url("Fresh Face", "NA1") + "/refresh")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cooldown"


async def test_refresh_known_player_without_riot_key_serves_stored_profile(
    app, client, session, settings
):
    """No Riot key: the Update button on a stored player degrades to 200 "unavailable"."""
    from hextrack.riot.client import RiotClient

    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()
    install_fakes(app, riot=RiotClient(settings))  # the real client, with no key configured
    resp = await client.post(profile_url("Hex Walker", "NA1") + "/refresh")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["new_matches"] == 0 and body["pending"] == 0
    assert "not configured" in body["message"]
    assert body["profile"]["puuid"] == ME

    # A player HexTrack has never stored still needs Riot: 503 riot_key.
    resp = await client.post(profile_url("Nobody", "NA1") + "/refresh")
    assert resp.status_code == 503 and resp.json()["code"] == "riot_key"


async def test_refresh_known_player_with_rejected_key_is_unavailable(client, session, monkeypatch):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()

    async def forbidden(ctx, s, puuid):
        raise RiotForbidden("expired", status=403)

    monkeypatch.setattr(ondemand, "refresh_on_demand", forbidden)
    resp = await client.post(profile_url("Hex Walker", "NA1") + "/refresh")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "unavailable"


async def test_refresh_riot_error_propagates(client, session, monkeypatch):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()

    async def rate_limited(ctx, s, puuid):
        raise RiotRateLimited(retry_after=9)

    monkeypatch.setattr(ondemand, "refresh_on_demand", rate_limited)
    resp = await client.post(profile_url("Hex Walker", "NA1") + "/refresh")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "9"


# --- match history ---------------------------------------------------------------------------


def matches_url(puuid: str = ME, **params: Any) -> str:
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    return f"/api/v1/summoners/{puuid}/matches" + (f"?{query}" if query else "")


async def test_match_history_pagination(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    series = match_series(ME, 25, game_name="Hex Walker")
    for raw in series:
        await add_match(session, raw)
    await session.commit()

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 10}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get(matches_url(**params))
        assert resp.status_code == 200, resp.text
        page = resp.json()
        pages += 1
        seen += [item["match_id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    expected = [raw["metadata"]["matchId"] for raw in reversed(series)]
    assert seen == expected  # newest first, no duplicates, nothing skipped


async def test_match_history_exact_page_has_no_dangling_cursor(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    for raw in match_series(ME, 4):
        await add_match(session, raw)
    await session.commit()
    page = (await client.get(matches_url(limit=4))).json()
    assert len(page["items"]) == 4 and page["next_cursor"] is None


async def test_match_history_ties_on_game_start(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    for match_id in ("NA1_10", "NA1_11", "NA1_12"):
        await add_match(session, make_match_json(match_id, [spec(ME)], start=SEASON))
    await session.commit()
    first = (await client.get(matches_url(limit=2))).json()
    assert [i["match_id"] for i in first["items"]] == ["NA1_12", "NA1_11"]
    second = (await client.get(matches_url(limit=2, cursor=first["next_cursor"]))).json()
    assert [i["match_id"] for i in second["items"]] == ["NA1_10"]
    assert second["next_cursor"] is None


async def test_match_history_item_contents(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1", tracked=True)
    await add_summoner(session, FRIEND, "Friend", "NA1", tracked=True)
    raw = make_match_json(
        "NA1_42",
        [
            spec(ME, "Hex Walker", "NA1", kills=7, deaths=0, assists=8),
            spec(FRIEND, "Friend", "NA1"),
        ],
        start=SEASON,
        duration_s=1500,
    )
    scores = score_all(raw)
    await add_match(session, raw, scores=scores)
    await session.commit()

    page = (await client.get(matches_url())).json()
    assert page["next_cursor"] is None
    (item,) = page["items"]
    assert item["match_id"] == "NA1_42"
    assert item["queue_id"] == 420 and item["queue_label"] == "Ranked Solo/Duo"
    assert item["game_mode"] == "CLASSIC" and item["game_duration"] == 1500
    assert item["patch"] == "16.17" and item["remake"] is False
    assert datetime.fromisoformat(item["game_start"]) == SEASON

    teams = item["teams"]
    assert [t["team_id"] for t in teams] == [100, 200]
    assert all(len(t["participants"]) == 5 for t in teams)
    blue = raw["info"]["participants"][:5]
    assert teams[0]["win"] is True and teams[1]["win"] is False
    assert teams[0]["kills"] == sum(p["kills"] for p in blue)
    assert teams[0]["gold"] == sum(p["goldEarned"] for p in blue)
    assert teams[0]["damage_to_champions"] == sum(p["totalDamageDealtToChampions"] for p in blue)

    me = item["me"]
    raw_me = _me(raw)
    assert me["puuid"] == ME and me["game_name"] == "Hex Walker" and me["tag_line"] == "NA1"
    assert me["team_id"] == 100 and me["participant_id"] == 1 and me["team_position"] == "TOP"
    assert (me["kills"], me["deaths"], me["assists"]) == (7, 0, 8)
    assert me["kda"] == 15.0  # perfect game: k + a
    assert me["kill_participation"] == pytest.approx(_kill_participation(raw), abs=1e-4)
    cs = raw_me["totalMinionsKilled"] + raw_me["neutralMinionsKilled"]
    assert me["cs"] == cs
    assert me["cs_per_min"] == pytest.approx(cs / 25, abs=1e-4)
    assert me["gold"] == raw_me["goldEarned"]
    assert me["gold_per_min"] == pytest.approx(raw_me["goldEarned"] / 25, abs=1e-4)
    assert me["damage_per_min"] == pytest.approx(
        raw_me["totalDamageDealtToChampions"] / 25, abs=1e-4
    )
    assert me["control_wards"] == raw_me["visionWardsBoughtInGame"]
    assert me["items"] == [raw_me[f"item{i}"] for i in range(7)]
    assert me["summoner1_id"] == raw_me["summoner1Id"]
    assert me["largest_multikill"] == raw_me["largestMultiKill"]
    assert me["is_tracked"] is True
    # score_all gives slot i the score 0.3 + 0.05 i: slot 9 is best, slot 0 (me) worst.
    assert me["ai_score"] == pytest.approx(0.3) and me["ai_rank"] == 10
    red = teams[1]["participants"]
    assert red[-1]["ai_rank"] == 1
    everyone = teams[0]["participants"] + red
    assert sorted(p["ai_rank"] for p in everyone) == list(range(1, 11))
    tracked = {p["puuid"]: p["is_tracked"] for p in everyone}
    assert tracked[FRIEND] is True
    assert sum(tracked.values()) == 2


async def test_match_history_unscored_remakes_and_queue_filter(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await add_match(session, make_match_json("NA1_1", [spec(ME)], start=SEASON))
    await add_match(
        session,
        make_match_json(
            "NA1_2", [spec(ME)], queue_id=440, start=SEASON + timedelta(hours=1), remake=True
        ),
    )
    await add_match(
        session,
        make_match_json("NA1_3", [spec(ME)], start=SEASON + timedelta(hours=2), duration_s=250),
    )
    await session.commit()

    items = (await client.get(matches_url())).json()["items"]
    assert [i["match_id"] for i in items] == ["NA1_3", "NA1_2", "NA1_1"]
    assert [i["remake"] for i in items] == [True, True, False]
    assert all(
        p["ai_score"] is None and p["ai_rank"] is None for p in items[2]["teams"][0]["participants"]
    )

    flex = (await client.get(matches_url(queue=440))).json()["items"]
    assert [i["match_id"] for i in flex] == ["NA1_2"]
    assert flex[0]["queue_label"] == "Ranked Flex"


async def test_match_history_filters_on_several_queues(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    for i, queue_id in enumerate((420, 400, 430, 450)):
        raw = make_match_json(
            f"NA1_{i}", [spec(ME)], queue_id=queue_id, start=SEASON + timedelta(hours=i)
        )
        await add_match(session, raw)
    await session.commit()

    normals = await client.get(f"/api/v1/summoners/{ME}/matches?queue=400&queue=430")
    assert normals.status_code == 200, normals.text
    assert [i["match_id"] for i in normals.json()["items"]] == ["NA1_2", "NA1_1"]
    too_many = "&".join(f"queue={q}" for q in range(11))
    resp = await client.get(f"/api/v1/summoners/{ME}/matches?{too_many}")
    assert resp.status_code == 422


async def test_match_history_query_count_is_constant(app, client, session):
    """One query for the page and one for all participants, whatever the page size."""
    await add_summoner(session, ME, "Hex Walker", "NA1")
    for raw in match_series(ME, 20):
        await add_match(session, raw)
    await session.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sync_engine = app.state.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", record)
    try:
        await client.get(matches_url(limit=2))
        small = len(statements)
        statements.clear()
        page = (await client.get(matches_url(limit=20))).json()
        large = len(statements)
    finally:
        event.remove(sync_engine, "before_cursor_execute", record)
    assert len(page["items"]) == 20
    assert small == large
    participant_queries = [s for s in statements if "FROM match_participants LEFT OUTER" in s]
    assert len(participant_queries) == 1


async def test_match_history_errors(client, session):
    resp = await client.get(matches_url("puuid-unknown"))
    assert resp.status_code == 404 and resp.json()["code"] == "not_found"

    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()
    resp = await client.get(matches_url(cursor="not-a-cursor!"))
    assert resp.status_code == 400 and resp.json()["code"] == "invalid_cursor"
    empty = (await client.get(matches_url())).json()
    assert empty == {"items": [], "next_cursor": None}


def test_cursor_roundtrip_is_exact():
    cursor = MatchCursor(datetime(2026, 3, 1, 20, 0, 0, 123456, tzinfo=UTC), "NA1_5012345678")
    token = encode_cursor(cursor)
    assert "=" not in token and "/" not in token and "+" not in token
    assert decode_cursor(token) == cursor


# --- rank history ----------------------------------------------------------------------------


async def test_rank_history_ascending_per_queue(client, session):
    await add_summoner(session, ME, "Hex Walker", "NA1")
    t0 = SEASON
    await add_rank(session, ME, "RANKED_SOLO_5x5", "GOLD", "I", 90, taken_at=t0 + timedelta(days=2))
    await add_rank(session, ME, "RANKED_SOLO_5x5", "GOLD", "IV", 10, taken_at=t0)
    await add_rank(
        session, ME, "RANKED_SOLO_5x5", "MASTER", None, 15, taken_at=t0 + timedelta(days=5)
    )
    await add_rank(session, ME, "RANKED_FLEX_SR", "SILVER", "II", 50, taken_at=t0)
    await session.commit()

    body = (await client.get(f"/api/v1/summoners/{ME}/ranks")).json()
    assert body["puuid"] == ME and body["queue_type"] == "RANKED_SOLO_5x5"
    points = body["points"]
    assert [(p["tier"], p["rank"], p["lp"]) for p in points] == [
        ("GOLD", "IV", 10),
        ("GOLD", "I", 90),
        ("MASTER", None, 15),
    ]
    assert [p["rank_value"] for p in points] == [1210, 1590, 2815]
    times = [datetime.fromisoformat(p["taken_at"]) for p in points]
    assert times == sorted(times)

    flex = (await client.get(f"/api/v1/summoners/{ME}/ranks?queue=RANKED_FLEX_SR")).json()
    assert [(p["tier"], p["lp"]) for p in flex["points"]] == [("SILVER", 50)]


async def test_rank_history_errors(client, session):
    assert (await client.get("/api/v1/summoners/nope/ranks")).status_code == 404
    await add_summoner(session, ME, "Hex Walker", "NA1")
    await session.commit()
    body = (await client.get(f"/api/v1/summoners/{ME}/ranks")).json()
    assert body["points"] == []
    bad = await client.get(f"/api/v1/summoners/{ME}/ranks?queue=ARAM")
    assert bad.status_code == 422


async def test_profile_hides_a_rank_the_player_no_longer_holds(client, session):
    """league-v4 simply stops returning a queue when the player is unranked in it, so the
    newest snapshot stays behind. Last season's tier must not be shown as the current one."""
    await add_summoner(
        session,
        ME,
        "Hex Walker",
        "NA1",
        tracked=True,
        last_refreshed_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    # Ranked before the season started, and never seen in flex since.
    await add_rank(session, ME, "RANKED_SOLO_5x5", "BRONZE", "IV", 94, taken_at=PRESEASON)
    await add_rank(
        session,
        ME,
        "RANKED_FLEX_SR",
        "SILVER",
        "III",
        65,
        taken_at=datetime.now(UTC) - timedelta(days=30),
    )
    await session.commit()

    body = (await client.get(profile_url("Hex Walker", "NA1"))).json()

    assert body["solo"] is None and body["flex"] is None
    # The history endpoint still returns every snapshot ever taken.
    points = (await client.get(f"/api/v1/summoners/{ME}/ranks")).json()["points"]
    assert [p["tier"] for p in points] == ["BRONZE"]
