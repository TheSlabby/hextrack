"""GET /records: single-game records of the roster or one player, and pentakills."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest

from hextrack.api.schemas import RecordKey
from tests.factories import filler_specs, make_match_json, spec
from tests.test_api_support import add_match, add_model, add_summoner

A, B, U = "puuid-rec-a", "puuid-rec-b", "puuid-rec-u"
SEASON = datetime(2026, 3, 1, 20, tzinfo=UTC)
PRESEASON = datetime(2025, 12, 1, 20, tzinfo=UTC)
#: Fillers' default kills by slot (tests.factories: 2 + (index * 3) % 8).
FILLER_KILLS = {i: 2 + (i * 3) % 8 for i in range(10)}


def _game(
    match_id: str,
    blue: list,
    red: list | None = None,
    *,
    start: datetime,
    **kwargs: Any,
) -> dict[str, Any]:
    """``blue`` in slots 0.., ``red`` in slots 5.., untracked fillers elsewhere."""
    red = red or []
    slots = blue + filler_specs(match_id, 5 - len(blue), offset=len(blue))
    slots += red + filler_specs(match_id, 5 - len(red), offset=5 + len(red))
    return make_match_json(match_id, slots, start=start, **kwargs)


def _line(puuid: str, name: str, **stats: Any):
    """A tracked player's line; multikills default to none so they never leak into the
    pentakill / quadrakill lists unless a test asks for them."""
    stats.setdefault("pentaKills", 0)
    stats.setdefault("quadraKills", 0)
    return spec(puuid, name, "NA1", **stats)


async def _roster(session, *, untracked: bool = False) -> None:
    await add_summoner(session, A, "Alpha", "NA1", tracked=True)
    await add_summoner(session, B, "bravo", "NA1", tracked=True)
    if untracked:
        await add_summoner(session, U, "Stranger", "EUW", tracked=False)


async def _get(client, query: str = "") -> dict[str, Any]:
    resp = await client.get(f"/api/v1/records{query}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _category(body: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return next(c for c in body["categories"] if c["key"] == key)["entries"]


def _summary(entries: list[dict[str, Any]]) -> list[tuple[int, float, str, str]]:
    return [(e["rank"], e["value"], e["puuid"], e["match_id"]) for e in entries]


# --- shape -----------------------------------------------------------------------------------


async def test_every_category_in_order_even_without_games(client, session):
    await _roster(session)
    await session.commit()
    body = await _get(client)
    assert body["scope"] == "roster" and body["puuid"] is None
    assert body["since"] == "season" and body["queue"] == "all" and body["limit"] == 3
    assert body["model_version"] is None
    assert [c["key"] for c in body["categories"]] == list(get_args(RecordKey))
    assert all(c["entries"] == [] for c in body["categories"])
    assert [c["key"] for c in body["categories"] if not c["higher_is_better"]] == ["fastest_win"]
    units = {c["key"]: c["unit"] for c in body["categories"]}
    assert units["most_kills"] == "count" and units["most_damage"] == "count"
    assert units["best_kda"] == "number"
    assert units["highest_damage_per_min"] == units["highest_cs_per_min"] == "per_min"
    assert units["highest_kill_participation"] == "percent"
    assert units["longest_game"] == units["fastest_win"] == "duration"
    assert units["highest_ai_score"] == "score"
    assert all(c["label"] for c in body["categories"])
    assert body["pentakills"] == [] and body["quadrakills"] == []


async def test_empty_roster(client, session):
    body = await _get(client)
    assert len(body["categories"]) == len(get_args(RecordKey))
    assert all(c["entries"] == [] for c in body["categories"])


# --- values of every category -----------------------------------------------------------------


async def test_values_of_every_category(client, session):
    await _roster(session)
    await add_model(session, "v1", active=True)
    raw = _game(
        "NA1_1",
        [
            _line(
                A,
                "OldName",  # the Riot ID at game time; entries use the current one
                kills=10,
                deaths=2,
                assists=8,
                totalDamageDealtToChampions=30000,
                totalMinionsKilled=200,
                neutralMinionsKilled=25,
                goldEarned=15000,
                visionScore=40,
                largestKillingSpree=7,
                totalDamageTaken=25000,
                totalHeal=9000,
            )
        ],
        start=SEASON,
        duration_s=1500,
        winning_team=100,
    )
    await add_match(session, raw, scores={A: 0.723456})
    await session.commit()

    body = await _get(client)
    assert body["model_version"] == "v1"
    team_kills = 10 + sum(FILLER_KILLS[i] for i in range(1, 5))
    expected = {
        "most_kills": 10,
        "most_assists": 8,
        "most_deaths": 2,
        "best_kda": 9.0,
        "most_damage": 30000,
        "highest_damage_per_min": 1200.0,
        "most_cs": 225,
        "highest_cs_per_min": 9.0,
        "most_gold": 15000,
        "highest_vision": 40,
        "highest_kill_participation": round(18 / team_kills, 4),
        "longest_game": 1500,
        "fastest_win": 1500,
        "highest_ai_score": 0.723456,  # stored scores are returned as is (0..1)
        "largest_killing_spree": 7,
        "most_damage_taken": 25000,
        "most_healing": 9000,
    }
    for category in body["categories"]:
        (entry,) = category["entries"]
        assert entry["value"] == pytest.approx(expected[category["key"]]), category["key"]
        assert entry == {
            "rank": 1,
            "value": entry["value"],
            "puuid": A,
            "game_name": "Alpha",
            "tag_line": "NA1",
            "champion_name": "Aatrox",
            "match_id": "NA1_1",
            "game_start": entry["game_start"],
            "win": True,
        }
        assert datetime.fromisoformat(entry["game_start"]) == SEASON


# --- ordering, ties, limit ------------------------------------------------------------------


async def test_best_first_ties_go_to_the_earlier_game_and_zero_is_no_record(client, session):
    await _roster(session)
    games = [
        ("NA1_1", A, 12, SEASON),
        ("NA1_2", A, 15, SEASON + timedelta(days=2)),
        ("NA1_3", B, 12, SEASON + timedelta(days=1)),
        ("NA1_4", B, 0, SEASON + timedelta(days=3)),
    ]
    for match_id, puuid, kills, start in games:
        name = "Alpha" if puuid == A else "bravo"
        await add_match(session, _game(match_id, [_line(puuid, name, kills=kills)], start=start))
    await session.commit()

    body = await _get(client, "?limit=5")
    assert body["limit"] == 5
    assert _summary(_category(body, "most_kills")) == [
        (1, 15.0, A, "NA1_2"),
        (2, 12.0, A, "NA1_1"),  # tie on 12: A's game was a day earlier than B's
        (3, 12.0, B, "NA1_3"),
    ]  # B's 0-kill game is not a record
    body = await _get(client, "?limit=2")
    assert _summary(_category(body, "most_kills")) == [(1, 15.0, A, "NA1_2"), (2, 12.0, A, "NA1_1")]
    assert all(len(c["entries"]) <= 2 for c in body["categories"])


async def test_best_kda_needs_five_takedowns(client, session):
    await _roster(session)
    lines = [
        ("NA1_1", SEASON, dict(kills=4, deaths=0, assists=0)),  # KDA 4, only 4 takedowns
        ("NA1_2", SEASON + timedelta(days=2), dict(kills=3, deaths=1, assists=2)),  # 5.0
        ("NA1_3", SEASON + timedelta(days=1), dict(kills=2, deaths=0, assists=3)),  # 5.0
        ("NA1_4", SEASON + timedelta(days=3), dict(kills=6, deaths=4, assists=4)),  # 2.5
    ]
    for match_id, start, stats in lines:
        await add_match(session, _game(match_id, [_line(A, "Alpha", **stats)], start=start))
    await session.commit()
    assert _summary(_category(await _get(client), "best_kda")) == [
        (1, 5.0, A, "NA1_3"),  # deathless: (k + a) / max(d, 1)
        (2, 5.0, A, "NA1_2"),
        (3, 2.5, A, "NA1_4"),
    ]


async def test_kill_participation_needs_ten_team_kills(client, session):
    await _roster(session)

    def team(match_id: str, mate_kills: int, start: datetime, **mine: Any) -> dict[str, Any]:
        mates = [spec(f"{match_id}-mate{i}", kills=mate_kills) for i in range(1, 5)]
        return _game(match_id, [_line(A, "Alpha", **mine), *mates], start=start)

    # 5 + 4 x 1 = 9 team kills: a perfect 100% does not count.
    await add_match(session, team("NA1_1", 1, SEASON, kills=5, deaths=1, assists=4))
    # 6 + 4 x 1 = 10 team kills: 8 takedowns -> 80%.
    await add_match(
        session, team("NA1_2", 1, SEASON + timedelta(days=1), kills=6, deaths=1, assists=2)
    )
    # 4 + 4 x 4 = 20 team kills: 10 takedowns -> 50%.
    await add_match(
        session, team("NA1_3", 4, SEASON + timedelta(days=2), kills=4, deaths=1, assists=6)
    )
    await session.commit()
    assert _summary(_category(await _get(client), "highest_kill_participation")) == [
        (1, 0.8, A, "NA1_2"),
        (2, 0.5, A, "NA1_3"),
    ]


async def test_fastest_win_and_longest_game(client, session):
    await _roster(session)
    day = timedelta(days=1)
    games = [
        # (match id, blue lines, duration, blue wins, remake)
        ("NA1_1", [A], 900, False, False),  # a loss: never the fastest win
        ("NA1_2", [A], 250, True, False),  # under 5 minutes: a remake
        ("NA1_3", [A], 600, True, True),  # early surrender: a remake
        ("NA1_4", [A], 1000, True, False),
        ("NA1_5", [B], 1200, True, False),
        ("NA1_6", [A, B], 1100, True, False),  # both friends: listed once
    ]
    for i, (match_id, puuids, duration, won, remake) in enumerate(games):
        lines = [_line(p, "Alpha" if p == A else "bravo") for p in puuids]
        raw = _game(
            match_id,
            lines,
            start=SEASON + i * day,
            duration_s=duration,
            winning_team=100 if won else 200,
            remake=remake,
        )
        await add_match(session, raw)
    await session.commit()

    body = await _get(client, "?limit=5")
    assert _summary(_category(body, "fastest_win")) == [
        (1, 1000.0, A, "NA1_4"),
        (2, 1100.0, A, "NA1_6"),  # the lowest participant id of the match's friends
        (3, 1200.0, B, "NA1_5"),
    ]
    assert _summary(_category(body, "longest_game")) == [
        (1, 1200.0, B, "NA1_5"),
        (2, 1100.0, A, "NA1_6"),
        (3, 1000.0, A, "NA1_4"),
        (4, 900.0, A, "NA1_1"),
    ]
    assert _category(body, "longest_game")[3]["win"] is False
    # Remakes count nowhere, not even as someone's "most deaths".
    assert {e["match_id"] for c in body["categories"] for e in c["entries"]}.isdisjoint(
        {"NA1_2", "NA1_3"}
    )


async def test_highest_ai_score_uses_the_active_model_only(client, session):
    await _roster(session)
    await add_match(session, _game("NA1_1", [_line(A, "Alpha")], start=SEASON), scores={A: 0.9})
    await add_match(
        session,
        _game("NA1_2", [_line(A, "Alpha")], start=SEASON + timedelta(days=1)),
        scores={A: 0.6},
        model_version="v2",
    )
    await add_match(
        session,
        _game("NA1_3", [_line(B, "bravo")], start=SEASON + timedelta(days=2)),
        scores={B: 0.7},
        model_version="v2",
    )
    await session.commit()
    body = await _get(client)
    assert body["model_version"] is None and _category(body, "highest_ai_score") == []

    await add_model(session, "v2", active=True)
    await session.commit()
    body = await _get(client)
    assert body["model_version"] == "v2"
    assert _summary(_category(body, "highest_ai_score")) == [
        (1, 0.7, B, "NA1_3"),
        (2, 0.6, A, "NA1_2"),  # A's 0.9 is from another model version
    ]


# --- scope and filters -----------------------------------------------------------------------


async def test_roster_scope_versus_player_scope(client, session):
    await _roster(session, untracked=True)
    raw = _game(
        "NA1_1",
        [_line(A, "Alpha", kills=10), _line(U, "Stranger", kills=30)],
        [_line(B, "bravo", kills=5)],
        start=SEASON,
    )
    await add_match(session, raw)
    await session.commit()

    roster = await _get(client)
    kills = _category(roster, "most_kills")
    assert [(e["puuid"], e["value"]) for e in kills] == [(A, 10.0), (B, 5.0)]
    assert all(e["puuid"] != U for c in roster["categories"] for e in c["entries"])

    stranger = await _get(client, f"?puuid={U}")
    assert stranger["scope"] == "player" and stranger["puuid"] == U
    (entry,) = _category(stranger, "most_kills")
    assert (entry["puuid"], entry["game_name"], entry["tag_line"], entry["value"]) == (
        U,
        "Stranger",
        "EUW",
        30.0,
    )
    assert all(e["puuid"] == U for c in stranger["categories"] for e in c["entries"])

    bravo = await _get(client, f"?puuid={B}")
    assert [(e["puuid"], e["value"]) for e in _category(bravo, "most_kills")] == [(B, 5.0)]
    assert (await client.get("/api/v1/records?puuid=nobody")).status_code == 404


async def test_since_and_queue_filters(client, session):
    await _roster(session)
    games = [
        ("NA1_1", 20, PRESEASON, 420),
        ("NA1_2", 10, SEASON, 420),
        ("NA1_3", 14, SEASON + timedelta(days=1), 440),
        ("NA1_4", 25, SEASON + timedelta(days=2), 450),  # ARAM: never counted
        ("NA1_5", 26, SEASON + timedelta(days=3), 400),  # normal draft: never counted
    ]
    for match_id, kills, start, queue_id in games:
        raw = _game(match_id, [_line(A, "Alpha", kills=kills)], start=start, queue_id=queue_id)
        await add_match(session, raw)
    await session.commit()

    async def kills(query: str) -> list[float]:
        return [e["value"] for e in _category(await _get(client, query), "most_kills")]

    assert await kills("") == [14.0, 10.0]
    assert await kills("?since=all") == [20.0, 14.0, 10.0]
    assert await kills("?queue=solo") == [10.0]
    assert await kills("?queue=flex") == [14.0]
    assert await kills("?since=all&queue=solo") == [20.0, 10.0]
    body = await _get(client, "?since=all&queue=flex")
    assert body["since"] == "all" and body["queue"] == "flex"


async def test_pentakills_and_quadrakills(client, session):
    await _roster(session, untracked=True)
    games = [
        ("NA1_1", A, "Alpha", SEASON, dict(pentaKills=1, quadraKills=2)),
        # Riot's multikill counters nest: every pentakill also counts as a quadra kill.
        ("NA1_2", A, "Alpha", SEASON + timedelta(days=4), dict(pentaKills=2, quadraKills=2)),
        ("NA1_3", B, "bravo", SEASON + timedelta(days=2), dict(pentaKills=1, quadraKills=1)),
        ("NA1_4", B, "bravo", PRESEASON, dict(pentaKills=1, quadraKills=3)),
        ("NA1_5", U, "Stranger", SEASON + timedelta(days=5), dict(pentaKills=1, quadraKills=4)),
        ("NA1_6", A, "Alpha", SEASON + timedelta(days=6), dict(quadraKills=1)),
    ]
    for match_id, puuid, name, start, stats in games:
        await add_match(session, _game(match_id, [_line(puuid, name, **stats)], start=start))
    await session.commit()

    body = await _get(client)
    assert _summary(body["pentakills"]) == [
        (1, 2.0, A, "NA1_2"),  # newest first; value = pentakills in that game
        (2, 1.0, B, "NA1_3"),
        (3, 1.0, A, "NA1_1"),
    ]
    assert body["pentakills"][0]["game_name"] == "Alpha"
    # Quadra kills that did not become pentakills: Alpha 1 (NA1_1) + 0 (NA1_2) + 1 (NA1_6);
    # bravo's only multikill this season is a pentakill, so bravo is not listed.
    assert body["quadrakills"] == [
        {"puuid": A, "game_name": "Alpha", "tag_line": "NA1", "count": 2},
    ]

    everything = await _get(client, "?since=all")
    assert [e["match_id"] for e in everything["pentakills"]] == ["NA1_2", "NA1_3", "NA1_1", "NA1_4"]
    assert [(q["puuid"], q["count"]) for q in everything["quadrakills"]] == [(A, 2), (B, 2)]

    stranger = await _get(client, f"?puuid={U}")
    assert _summary(stranger["pentakills"]) == [(1, 1.0, U, "NA1_5")]
    assert stranger["quadrakills"] == [
        {"puuid": U, "game_name": "Stranger", "tag_line": "EUW", "count": 3}
    ]


async def test_quadrakill_ties_are_ordered_by_name(client, session):
    await _roster(session)
    await add_match(session, _game("NA1_1", [_line(B, "bravo", quadraKills=2)], start=SEASON))
    await add_match(
        session,
        _game("NA1_2", [_line(A, "Alpha", quadraKills=2)], start=SEASON + timedelta(days=1)),
    )
    await session.commit()
    body = await _get(client)
    assert [q["game_name"] for q in body["quadrakills"]] == ["Alpha", "bravo"]


def test_scope_filters_are_rendered_into_the_sql():
    """Queue ids, the season cutoff and the puuids are literals, not bind parameters: with
    asyncpg's cached statements a generic plan misjudges them and runs several times slower
    (the player-scope records went from ~30 to ~110 ms after the fifth request)."""
    from sqlalchemy.dialects import postgresql

    from hextrack.stats.records import Scope, quadrakill_statement, records_statement

    scope = Scope(
        players={A: ("Alpha", "NA1")}, queues=(420, 440), since=SEASON, single_player=True
    )
    dialect = postgresql.asyncpg.dialect()  # type: ignore[attr-defined]
    for statement in (
        records_statement(scope, limit=3, model_version="v1"),
        quadrakill_statement(scope),
    ):
        compiled = statement.compile(dialect=dialect, compile_kwargs={"render_postcompile": True})
        sql = str(compiled)
        assert "IN (420, 440)" in sql
        assert "'2026-03-01 20:00:00+00:00'" in sql
        assert f"IN ('{A}')" in sql
        assert SEASON not in compiled.params.values()
        assert 420 not in compiled.params.values()
