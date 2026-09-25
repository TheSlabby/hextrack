"""GET /live: the worker's live-games snapshot joined with roster, ranks and season numbers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from hextrack.db.repo.app_state import set_state
from hextrack.ingest.live import STATE_KEY
from hextrack.rank import RANKED_FLEX_SR, RANKED_SOLO_5x5, rank_value
from tests.factories import make_match_json, spec
from tests.test_api_support import add_match, add_model, add_rank, add_summoner

URL = "/api/v1/live"
A, B, U = "puuid-a", "puuid-b", "puuid-u"
AHRI, LEE, DARIUS, AATROX = (103, "Ahri"), (64, "LeeSin"), (122, "Darius"), (266, "Aatrox")
SEASON = datetime(2026, 3, 1, 20, tzinfo=UTC)
PRESEASON = datetime(2025, 12, 1, 20, tzinfo=UTC)


class ChampionDDragon:
    """Data Dragon stand-in with a small champion map (never touches the network)."""

    def __init__(self, champions: dict[int, str] | None = None) -> None:
        self.champions = (
            champions
            if champions is not None
            else {AHRI[0]: AHRI[1], LEE[0]: LEE[1], DARIUS[0]: DARIUS[1], AATROX[0]: AATROX[1]}
        )
        self.calls = 0

    async def champion_map(self) -> dict[int, str]:
        self.calls += 1
        return dict(self.champions)

    async def latest_version(self) -> str:
        return "16.19.1"

    async def aclose(self) -> None:
        return None


def _iso(value: datetime) -> str:
    return value.isoformat()


def _player(
    puuid: str | None,
    riot_id: str | None,
    team_id: int,
    champion_id: int,
    *,
    bot: bool = False,
    perks: bool = True,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "puuid": puuid,
        "teamId": team_id,
        "championId": champion_id,
        "spell1Id": 4,
        "spell2Id": 14,
        "riotId": riot_id,
        "profileIconId": 29,
        "bot": bot,
        "gameCustomizationObjects": [],
    }
    if perks:
        raw["perks"] = {"perkIds": [8112, 8126, 8138, 8135, 8233, 8237], "perkStyle": 8100}
        raw["perks"]["perkSubStyle"] = 8200
    return raw


def _fillers(prefix: str, team_id: int, count: int) -> list[dict[str, Any]]:
    return [
        _player(f"{prefix}-{team_id}-{i}", f"Filler {i}#F{team_id}", team_id, 1 + i)
        for i in range(count)
    ]


def _info(
    game_id: int,
    participants: Sequence[dict[str, Any]],
    *,
    started: datetime | None,
    queue_id: int | None = 420,
    platform: str | None = "NA1",
    game_mode: str = "CLASSIC",
    bans: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "gameId": game_id,
        "gameType": "MATCHED",
        "gameStartTime": int(started.timestamp() * 1000) if started else 0,
        "mapId": 11,
        "gameLength": 600 if started else 0,
        "gameMode": game_mode,
        "bannedChampions": list(bans),
        "observers": {"encryptionKey": "k"},
        "participants": list(participants),
    }
    if queue_id is not None:
        info["gameQueueConfigId"] = queue_id
    if platform is not None:
        info["platformId"] = platform
    return info


def _stored(
    info: dict[str, Any],
    *,
    first_seen: datetime,
    seen: datetime | None = None,
    ranks: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    return {
        "info": info,
        "ranks": ranks or {},
        "first_seen_at": _iso(first_seen),
        "seen_at": _iso(seen or first_seen),
    }


async def _save(session, checked_at: datetime | None, games: Sequence[dict[str, Any]]) -> None:
    value: dict[str, Any] = {"games": list(games)}
    if checked_at is not None:
        value["checked_at"] = _iso(checked_at)
    await set_state(session, STATE_KEY, value)
    await session.commit()


def _league(queue_type: str, tier: str, rank: str, lp: int, wins: int, losses: int) -> dict:
    return {
        "leagueId": "league-1",
        "queueType": queue_type,
        "tier": tier,
        "rank": rank,
        "puuid": U,
        "leaguePoints": lp,
        "wins": wins,
        "losses": losses,
        "veteran": False,
        "inactive": False,
        "freshBlood": False,
        "hotStreak": True,
    }


async def _seed_roster(session) -> None:
    await add_summoner(session, A, "Hex Walker", "NA1", tracked=True)
    await add_summoner(session, B, "Duo Buddy", "NA1", tracked=True)
    await add_summoner(session, U, "Known Rival", "EUW", tracked=False)
    await add_model(session, "v1", active=True)
    await add_model(session, "v0", active=False)
    a_ahri = spec(A, "Hex Walker", "NA1", champion=AHRI)
    games = [
        # A on Ahri: two wins scored by the active model, a loss scored by an old one.
        ("NA1_101", [a_ahri], 100, {A: 0.8}, "v1", SEASON),
        ("NA1_102", [a_ahri], 100, {A: 0.6}, "v1", SEASON + timedelta(hours=1)),
        ("NA1_103", [a_ahri], 200, {A: 0.1}, "v0", SEASON + timedelta(hours=2)),
        # A on another champion, won, not scored.
        ("NA1_104", [spec(A, "Hex Walker", "NA1", champion=DARIUS)], 100, {}, "v1", SEASON),
        # Before the season: not counted.
        ("NA1_105", [a_ahri], 100, {A: 0.9}, "v1", PRESEASON),
        # U, a known non-roster player, one unscored season game on Lee Sin (a loss).
        ("NA1_106", [spec(U, "Known Rival", "EUW", champion=LEE)], 200, {}, "v1", SEASON),
    ]
    for match_id, specs, winner, scores, version, start in games:
        raw = make_match_json(match_id, specs, start=start, winning_team=winner)
        await add_match(session, raw, scores=scores, model_version=version)
    # A normal (non-ranked) game with a great score: not counted.
    raw = make_match_json("NA1_107", [a_ahri], queue_id=400, start=SEASON)
    await add_match(session, raw, scores={A: 1.0}, model_version="v1")
    await session.flush()


async def test_no_state_is_empty(app, client, settings):
    app.state.ddragon = ChampionDDragon()
    body = (await client.get(URL)).json()
    assert body == {
        "checked_at": None,
        "interval_seconds": settings.poll_interval_seconds,
        "games": [],
    }
    assert app.state.ddragon.calls == 0


async def test_stale_snapshot_hides_games(app, client, session, settings):
    app.state.ddragon = ChampionDDragon()
    now = datetime.now(UTC)
    limit = 3 * settings.poll_interval_seconds + 60
    checked = now - timedelta(seconds=limit + 30)
    info = _info(1, _fillers("s", 100, 5) + _fillers("s", 200, 5), started=now)
    await _save(session, checked, [_stored(info, first_seen=checked)])
    body = (await client.get(URL)).json()
    assert body["games"] == []
    assert datetime.fromisoformat(body["checked_at"]) == checked

    # Just inside the window the game is shown.
    checked = now - timedelta(seconds=limit - 30)
    await _save(session, checked, [_stored(info, first_seen=checked)])
    body = (await client.get(URL)).json()
    assert [g["game_id"] for g in body["games"]] == [1]


async def test_disabled_feature_is_empty(app, client, session, settings):
    app.state.ddragon = ChampionDDragon()
    now = datetime.now(UTC)
    info = _info(1, _fillers("d", 100, 5) + _fillers("d", 200, 5), started=now)
    await _save(session, now, [_stored(info, first_seen=now)])
    app.state.settings = settings.model_copy(update={"live_games": False})
    body = (await client.get(URL)).json()
    assert body["checked_at"] is None and body["games"] == []


async def test_roster_duo_in_ranked_game(app, client, session, settings):
    app.state.ddragon = ChampionDDragon()
    await _seed_roster(session)
    now = datetime.now(UTC)
    await add_rank(
        session, A, RANKED_SOLO_5x5, "EMERALD", "IV", 12, taken_at=now - timedelta(hours=1)
    )
    started = now - timedelta(minutes=12)
    first_seen = now - timedelta(minutes=10)
    # Riot's order puts red first here; the API must list blue first, order kept per team.
    participants = [
        _player(U, "Known Rival#EUW", 200, LEE[0]),
        _player("p-odd", "Odd#Name#EUW", 200, 9999, perks=False),
        *_fillers("g", 200, 3),
        _player(A, "Hex Walker#NA1", 100, AHRI[0]),
        _player(B, "Duo Buddy#NA1", 100, AATROX[0]),
        *_fillers("g", 100, 3),
    ]
    bans = [
        {"championId": DARIUS[0], "teamId": 100, "pickTurn": 1},
        {"championId": -1, "teamId": 100, "pickTurn": 2},
        {"championId": 424242, "teamId": 200, "pickTurn": 6},
    ]
    info = _info(5_300_000_001, participants, started=started, bans=bans)
    ranks = {
        U: [
            _league(RANKED_SOLO_5x5, "GOLD", "II", 45, 30, 20),
            _league(RANKED_FLEX_SR, "MASTER", "I", 120, 5, 5),
        ],
        # Roster players use stored snapshots even when the worker saved entries.
        A: [_league(RANKED_SOLO_5x5, "DIAMOND", "I", 99, 1, 1)],
    }
    await _save(session, now, [_stored(info, first_seen=first_seen, seen=now, ranks=ranks)])

    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert datetime.fromisoformat(body["checked_at"]) == now
    assert body["interval_seconds"] == settings.poll_interval_seconds
    (game,) = body["games"]
    assert game["game_id"] == 5_300_000_001
    assert game["match_id"] == "NA1_5300000001"
    assert game["platform"] == "na1"
    assert game["queue_id"] == 420 and game["queue_label"] == "Ranked Solo/Duo"
    assert game["game_mode"] == "CLASSIC" and game["map_id"] == 11
    assert abs(datetime.fromisoformat(game["started_at"]) - started) < timedelta(milliseconds=2)
    assert datetime.fromisoformat(game["first_seen_at"]) == first_seen
    assert datetime.fromisoformat(game["seen_at"]) == now
    assert game["bans"] == [
        {"champion_id": DARIUS[0], "champion_name": "Darius", "team_id": 100},
        {"champion_id": 424242, "champion_name": None, "team_id": 200},
    ]

    people = game["participants"]
    assert [p["team_id"] for p in people] == [100] * 5 + [200] * 5
    assert [p["puuid"] for p in people[:2]] == [A, B]
    assert [p["puuid"] for p in people[5:7]] == [U, "p-odd"]
    by_puuid = {p["puuid"]: p for p in people}

    a = by_puuid[A]
    assert (a["game_name"], a["tag_line"]) == ("Hex Walker", "NA1")
    assert a["is_tracked"] is True and a["bot"] is False
    assert a["champion_id"] == AHRI[0] and a["champion_name"] == "Ahri"
    assert (a["spell1_id"], a["spell2_id"], a["profile_icon_id"]) == (4, 14, 29)
    assert (a["keystone_id"], a["primary_style_id"], a["secondary_style_id"]) == (8112, 8100, 8200)
    assert a["solo"]["tier"] == "EMERALD" and a["solo"]["rank"] == "IV"
    assert a["solo"]["lp"] == 12
    assert a["solo"]["rank_value"] == rank_value("EMERALD", "IV", 12)
    assert a["flex"] is None
    # Season ranked: 101, 102 (wins), 103 (loss), 104 (win on Darius).
    assert (a["season_games"], a["season_wins"]) == (4, 3)
    # Active model only: (0.8 + 0.6) / 2.
    assert abs(a["avg_ai_score"] - 0.7) < 1e-9
    assert (a["champion_games"], a["champion_wins"]) == (3, 2)

    b = by_puuid[B]
    assert b["is_tracked"] is True
    assert b["champion_name"] == "Aatrox"
    assert b["solo"] is None and b["flex"] is None
    assert (b["season_games"], b["season_wins"], b["avg_ai_score"]) == (0, 0, None)
    assert (b["champion_games"], b["champion_wins"]) == (0, 0)

    u = by_puuid[U]
    assert (u["game_name"], u["tag_line"]) == ("Known Rival", "EUW")
    assert u["is_tracked"] is False
    assert u["solo"] == {
        "queue_type": RANKED_SOLO_5x5,
        "tier": "GOLD",
        "rank": "II",
        "lp": 45,
        "wins": 30,
        "losses": 20,
        "winrate": 0.6,
        "rank_value": rank_value("GOLD", "II", 45),
        "taken_at": u["solo"]["taken_at"],
    }
    assert datetime.fromisoformat(u["solo"]["taken_at"]) == first_seen
    assert u["flex"]["tier"] == "MASTER" and u["flex"]["rank"] is None
    assert u["flex"]["rank_value"] == rank_value("MASTER", None, 120)
    assert (u["season_games"], u["season_wins"], u["avg_ai_score"]) == (1, 0, None)
    assert (u["champion_games"], u["champion_wins"]) == (1, 0)

    odd = by_puuid["p-odd"]
    assert (odd["game_name"], odd["tag_line"]) == ("Odd#Name", "EUW")
    assert odd["champion_name"] is None
    assert odd["keystone_id"] is None and odd["primary_style_id"] is None
    assert odd["solo"] is None and odd["season_games"] == 0 and odd["avg_ai_score"] is None


async def test_bots_loading_games_and_sort_order(app, client, session):
    app.state.ddragon = ChampionDDragon({})  # Data Dragon offline: names are None
    await add_summoner(session, A, "Hex Walker", "NA1", tracked=True)
    await add_summoner(session, B, "Duo Buddy", "NA1", tracked=True)
    now = datetime.now(UTC)
    bots = [
        _player(None, "Annie Bot", 200, 1, bot=True, perks=False),
        {"teamId": 200, "championId": 22, "bot": True, "spell1Id": 4, "spell2Id": 7},
        *[_player("", None, 200, 30 + i, bot=True, perks=False) for i in range(3)],
    ]
    coop = _info(
        3,
        [_player(A, "Hex Walker#NA1", 100, AHRI[0]), *_fillers("c", 100, 4), *bots],
        started=None,
        queue_id=870,
        platform=None,
    )
    older = _info(
        1,
        [_player(B, "Duo Buddy#NA1", 100, LEE[0]), *_fillers("o", 100, 4)],
        started=now - timedelta(minutes=30),
        queue_id=None,
        game_mode="ARAM",
    )
    newer = _info(
        2,
        [_player(B, "Duo Buddy#NA1", 200, LEE[0]), *_fillers("n", 100, 4)],
        started=now - timedelta(minutes=5),
        queue_id=440,
        platform="EUW1",
    )
    await _save(
        session,
        now,
        [
            _stored(older, first_seen=now - timedelta(minutes=29)),
            _stored(coop, first_seen=now - timedelta(minutes=1)),
            _stored(newer, first_seen=now - timedelta(minutes=4)),
        ],
    )
    body = (await client.get(URL)).json()
    games = body["games"]
    assert [g["game_id"] for g in games] == [3, 2, 1]

    loading = games[0]
    assert loading["started_at"] is None
    assert loading["match_id"] == "NA1_3" and loading["platform"] == "na1"
    assert loading["queue_label"] == "Co-op vs AI Intro"
    red = [p for p in loading["participants"] if p["team_id"] == 200]
    assert len(red) == 5
    assert all(p["bot"] and p["puuid"] is None for p in red)
    assert all(p["is_tracked"] is False and p["season_games"] == 0 for p in red)
    assert red[0]["game_name"] == "Annie Bot" and red[0]["tag_line"] is None
    assert red[1]["game_name"] is None and red[1]["keystone_id"] is None
    assert loading["participants"][0]["champion_name"] is None

    assert games[1]["match_id"] == "EUW1_2" and games[1]["platform"] == "euw1"
    assert games[1]["queue_label"] == "Ranked Flex"
    assert games[2]["queue_id"] is None and games[2]["queue_label"] == "ARAM"


async def test_malformed_games_are_skipped(app, client, session):
    app.state.ddragon = ChampionDDragon()
    now = datetime.now(UTC)
    good = _info(7, _fillers("m", 100, 5), started=now)
    await _save(
        session,
        now,
        [
            {"info": {"gameId": "nope"}, "first_seen_at": _iso(now), "seen_at": _iso(now)},
            {"info": good},  # no first_seen_at
            "garbage",
            _stored(good, first_seen=now),
        ],
    )
    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    assert [g["game_id"] for g in resp.json()["games"]] == [7]


async def test_failing_ddragon_leaves_names_empty(app, client, session):
    class BrokenDDragon(ChampionDDragon):
        async def champion_map(self) -> dict[int, str]:
            raise RuntimeError("offline")

    app.state.ddragon = BrokenDDragon()
    now = datetime.now(UTC)
    info = _info(8, [_player(A, "Hex Walker#NA1", 100, AHRI[0])], started=now)
    await _save(session, now, [_stored(info, first_seen=now)])
    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    (game,) = resp.json()["games"]
    assert game["participants"][0]["champion_name"] is None
