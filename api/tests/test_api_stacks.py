"""GET /squad/stacks and /squad/stacks/games: games the squad played together."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import update

from hextrack.db.models import MatchParticipant
from hextrack.stats.verdict import CARRY_TIERS, RAN_DOWN_TIERS
from tests.factories import filler_specs, make_match_json, spec
from tests.test_api_support import add_match, add_model, add_summoner

A, B, C, D, E, F, U = (
    "puuid-a",
    "puuid-b",
    "puuid-c",
    "puuid-d",
    "puuid-e",
    "puuid-f",
    "puuid-u",
)
FIVE_E, FIVE_F = [A, B, C, D, E], [A, B, C, D, F]
SEASON = datetime(2026, 3, 1, 20, tzinfo=UTC)
PRESEASON = datetime(2025, 12, 1, 20, tzinfo=UTC)
URL = "/api/v1/squad/stacks"
GAMES_URL = "/api/v1/squad/stacks/games"
LULU, SONA = (117, "Lulu"), (37, "Sona")


def _game(
    match_id: str,
    blue: Sequence[str],
    red: Sequence[str] = (),
    *,
    hour: int,
    blue_wins: bool = True,
    queue_id: int = 440,
    start: datetime | None = None,
    kills: Mapping[str, int] | None = None,
    champs: Mapping[str, tuple[int, str]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """A match with the given puuids in the blue (0-4) and red (5-9) slots.

    Default kills per slot (tests/factories.py): blue 2, 5, 8, 3, 6 (24), red 9, 4, 7, 2, 5
    (27). Default deaths / assists of slot 0: 1 / 3; slot 5: 5 / 5."""
    kills, champs = kills or {}, champs or {}

    def specs(puuids: Sequence[str]) -> list:
        return [spec(p, kills=kills.get(p), champion=champs.get(p)) for p in puuids]

    blue_specs, red_specs = specs(blue), specs(red)
    slots = blue_specs + filler_specs(match_id, 5 - len(blue_specs), offset=len(blue_specs))
    slots += red_specs + filler_specs(match_id, 5 - len(red_specs), offset=5 + len(red_specs))
    return make_match_json(
        match_id,
        slots,
        queue_id=queue_id,
        start=start or SEASON + timedelta(hours=hour),
        winning_team=100 if blue_wins else 200,
        **kwargs,
    )


def _scores(puuids: Sequence[str], *values: float) -> dict[str, float]:
    return dict(zip(puuids, values, strict=True))


async def seed_stacks(session) -> None:
    """Season ground truth (v1 active). 5-stacks, all Ranked Flex, blue unless noted:

    ====  ======  ====  =================================  ================================
    id    lineup  W/L   scores (v1)                        verdict
    ====  ======  ====  =================================  ================================
    S1    ABCDE   W     .95 .5 .45 .4 .3                   hardCarry A (45)
    S2    ABCDE   W     .5 .75 .45 .4 .35, 2700 s          carry B (25)
    S3    ABCDE   L     .3 .28 .26 .24 .02                 ranDown E (22)
    S4    ABCDE   L     .5 .2 .19 .18 .15                  tried A (30)
    S5    ABCDE   W     .6 .58 .57 .56 .55, RED side       winTogether (2)
    S6    ABCDF   L     .3 .3 .3 .3 .02, F on Lulu         ranDown F (28)
    S7    ABCDE   W     E unscored                         none
    S8    ABCDE   L     C scored by the inactive v0        none
    S9    ABCDF   W     .7 .58 .57 .56 .55, A 20 kills,    edge A (12)
                        F on Lulu
    S10   ABCDF   W     unscored, 1200 s, F on Sona        none
    S11   ABCDF   W     unscored, F on Sona                none
    S12   ABCDF   W     unscored                           none
    ====  ======  ====  =================================  ================================

    Only with smaller sizes: S13 (queue 400) ABCD + untracked U, loss, offDay D (13);
    S14 (Ranked Solo) ABC (blue, win, carry A 30) vs DEF (red, loss, ranDown F 25).
    Only with since=all: S0, a preseason ABCDE win (unscored).
    Never: an Arena game (ABCD on one side), a remake 5-stack, a custom-game 5-stack.
    """
    await add_summoner(session, A, "Alpha", "NA1", tracked=True, profile_icon_id=11)
    await add_summoner(session, B, "bravo", "NA1", tracked=True)
    await add_summoner(session, C, "Charlie", "NA1", tracked=True)
    await add_summoner(session, D, "Delta", "NA1", tracked=True)
    await add_summoner(session, E, "Echo", "NA1", tracked=True)
    await add_summoner(session, F, "Foxtrot", "NA1", tracked=True)
    await add_summoner(session, U, "Untracked", "NA1", tracked=False)
    await add_model(session, "v0", active=False)
    await add_model(session, "v1", active=True)

    await add_match(
        session, _game("NA1_1", FIVE_E, hour=1), scores=_scores(FIVE_E, 0.95, 0.5, 0.45, 0.4, 0.3)
    )
    await add_match(
        session,
        _game("NA1_2", FIVE_E, hour=2, duration_s=2700),
        scores=_scores(FIVE_E, 0.5, 0.75, 0.45, 0.4, 0.35),
    )
    await add_match(
        session,
        _game("NA1_3", FIVE_E, hour=3, blue_wins=False),
        scores=_scores(FIVE_E, 0.3, 0.28, 0.26, 0.24, 0.02),
    )
    await add_match(
        session,
        _game("NA1_4", FIVE_E, hour=4, blue_wins=False),
        scores=_scores(FIVE_E, 0.5, 0.2, 0.19, 0.18, 0.15),
    )
    await add_match(
        session,
        _game("NA1_5", [], FIVE_E, hour=5, blue_wins=False),
        scores=_scores(FIVE_E, 0.6, 0.58, 0.57, 0.56, 0.55),
    )
    await add_match(
        session,
        _game("NA1_6", FIVE_F, hour=6, blue_wins=False, champs={F: LULU}),
        scores=_scores(FIVE_F, 0.3, 0.3, 0.3, 0.3, 0.02),
    )
    await add_match(
        session, _game("NA1_7", FIVE_E, hour=7), scores=_scores([A, B, C, D], 0.6, 0.6, 0.6, 0.6)
    )
    await add_match(
        session,
        _game("NA1_8", FIVE_E, hour=8, blue_wins=False),
        scores=_scores(FIVE_E, 0.4, 0.4, 0.9, 0.4, 0.4),
    )
    await session.execute(
        update(MatchParticipant)
        .where(MatchParticipant.match_id == "NA1_8", MatchParticipant.puuid == C)
        .values(model_version="v0")
    )
    await add_match(
        session,
        _game("NA1_9", FIVE_F, hour=9, kills={A: 20}, champs={F: LULU}),
        scores=_scores(FIVE_F, 0.7, 0.58, 0.57, 0.56, 0.55),
    )
    await add_match(session, _game("NA1_10", FIVE_F, hour=10, duration_s=1200, champs={F: SONA}))
    await add_match(session, _game("NA1_11", FIVE_F, hour=11, champs={F: SONA}))
    await add_match(session, _game("NA1_12", FIVE_F, hour=12))
    await add_match(
        session,
        _game("NA1_13", [A, B, C, D, U], hour=13, blue_wins=False, queue_id=400),
        scores=_scores([A, B, C, D], 0.5, 0.5, 0.45, 0.32),
    )
    await add_match(
        session,
        _game("NA1_14", [A, B, C], [D, E, F], hour=14, queue_id=420),
        scores=_scores([A, B, C, D, E, F], 0.8, 0.5, 0.5, 0.3, 0.3, 0.05),
    )
    await add_match(session, _game("NA1_20", FIVE_E, hour=0, start=PRESEASON))
    # Excluded everywhere.
    await add_match(
        session, _game("NA1_15", [A, B, C, D], hour=15, queue_id=1700, game_mode="CHERRY")
    )
    await add_match(session, _game("NA1_16", FIVE_E, hour=16, remake=True, duration_s=200))
    await add_match(session, _game("NA1_17", FIVE_E, hour=17, queue_id=0))
    await session.commit()


async def _summary(client, **params: Any) -> dict[str, Any]:
    resp = await client.get(URL, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _all_games(client, **params: Any) -> tuple[list[dict[str, Any]], list[list[str]]]:
    """Every stack across all pages, plus the (match_id, team) keys of each page."""
    items: list[dict[str, Any]] = []
    pages: list[list[str]] = []
    cursor = None
    while True:
        query = dict(params, **({"cursor": cursor} if cursor else {}))
        resp = await client.get(GAMES_URL, params=query)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        items += body["items"]
        pages.append([f"{g['match_id']}/{g['team_id']}" for g in body["items"]])
        cursor = body["next_cursor"]
        if cursor is None:
            return items, pages
        assert len(pages) < 50


async def test_stack_summary_season_full_stacks(client, session, settings):
    await seed_stacks(session)
    body = await _summary(client)
    assert (body["since"], body["queue"], body["size"]) == ("season", "all", 5)
    assert body["model_version"] == "v1" and body["min_lineup_games"] == 5
    assert datetime.fromisoformat(body["season_start"]) == settings.season_start

    assert (body["games"], body["wins"]) == (12, 8)
    assert body["winrate"] == pytest.approx(8 / 12, abs=1e-4)
    # Newest first: S12 .. S1.
    assert body["recent_form"] == [
        True, True, True, True, False, True, False, True, False, False, True, True,
    ]  # fmt: skip
    assert body["avg_duration"] == pytest.approx((10 * 1800 + 2700 + 1200) / 12)
    # S9: A had 20 kills (42 - 27); S5 on red (27 - 24); the rest 24 - 27.
    assert body["avg_team_kills"] == pytest.approx((42 + 27 + 10 * 24) / 12)
    assert body["avg_enemy_kills"] == pytest.approx((24 + 11 * 27) / 12)
    assert body["verdict_games"] == 7

    players = body["players"]
    # Most games first, then Riot ID case-insensitively ("bravo" between Alpha and Charlie).
    assert [p["puuid"] for p in players] == [A, B, C, D, E, F]
    by_id = {p["puuid"]: p for p in players}
    a = by_id[A]
    assert (a["game_name"], a["tag_line"], a["profile_icon_id"]) == ("Alpha", "NA1", 11)
    assert (a["games"], a["wins"]) == (12, 8)
    # Scored by v1 in S1-S9 (S7 and S8 too: only E / C lacked a v1 score there).
    assert a["scored_games"] == 9
    assert a["avg_ai_score"] == pytest.approx(
        (0.95 + 0.5 + 0.3 + 0.5 + 0.6 + 0.3 + 0.6 + 0.4 + 0.7) / 9
    )
    # Slot 0 (2/1/3) in ten games, 20 kills in S9, red slot 5 (9/5/5) in S5.
    assert (a["kills"], a["deaths"], a["assists"]) == (20 + 9 + 20, 11 + 5, 33 + 5)
    assert a["kda"] == pytest.approx((49 + 38) / 16, abs=1e-4)
    assert (a["hard_carries"], a["carries"], a["ran_downs"], a["off_days"], a["tried"]) == (
        1,
        2,
        0,
        0,
        1,
    )
    assert (a["top_champion_id"], a["top_champion_name"], a["top_champion_games"]) == (
        266,
        "Aatrox",
        11,
    )
    # C's v0 score in S8 does not count.
    c = by_id[C]
    assert c["scored_games"] == 8
    assert c["avg_ai_score"] == pytest.approx(
        (0.45 + 0.45 + 0.26 + 0.19 + 0.57 + 0.3 + 0.6 + 0.57) / 8
    )
    e = by_id[E]
    assert (e["games"], e["wins"], e["scored_games"]) == (7, 4, 6)
    assert e["avg_ai_score"] == pytest.approx((0.3 + 0.35 + 0.02 + 0.15 + 0.55 + 0.4) / 6)
    assert (e["ran_downs"], e["carries"]) == (1, 0)
    assert by_id[B]["carries"] == 1 and by_id[B]["hard_carries"] == 0
    f = by_id[F]
    assert (f["games"], f["wins"], f["scored_games"], f["ran_downs"]) == (5, 4, 2, 1)
    # Lulu and Sona twice each: the more recent one (Sona, S11) wins the tie.
    assert (f["top_champion_id"], f["top_champion_name"], f["top_champion_games"]) == (
        37,
        "Sona",
        2,
    )
    assert by_id[D]["off_days"] == 0  # D's off day is a 4-stack

    abcde, abcdf = sorted(FIVE_E), sorted(FIVE_F)
    assert [(lu["puuids"], lu["games"], lu["wins"]) for lu in body["lineups"]] == [
        (abcde, 7, 4),
        (abcdf, 5, 4),
    ]
    assert body["most_played_lineup"]["puuids"] == abcde
    assert body["best_lineup"]["puuids"] == abcdf
    assert body["best_lineup"]["winrate"] == pytest.approx(0.8)
    last = datetime.fromisoformat(body["best_lineup"]["last_played"])
    assert last == SEASON + timedelta(hours=12)

    # ran_it_down: E and F both 1, F played fewer stacks.
    assert body["awards"] == [
        {"key": "carry_king", "puuid": A, "count": 2},
        {"key": "ran_it_down", "puuid": F, "count": 1},
        {"key": "tried_their_best", "puuid": A, "count": 1},
    ]

    highlights = {h["key"]: h for h in body["highlights"]}
    assert [h["key"] for h in body["highlights"]] == [
        "biggest_stomp",
        "worst_loss",
        "longest_game",
        "fastest_win",
        "most_team_kills",
    ]
    stomp = highlights["biggest_stomp"]
    assert (stomp["match_id"], stomp["team_kills"], stomp["enemy_kills"]) == ("NA1_9", 42, 27)
    assert stomp["member_puuids"] == FIVE_F and stomp["queue_label"] == "Ranked Flex"
    # Every loss is 24 - 27: the earliest one wins the tie.
    assert (highlights["worst_loss"]["match_id"], highlights["worst_loss"]["win"]) == (
        "NA1_3",
        False,
    )
    assert highlights["longest_game"]["match_id"] == "NA1_2"
    assert highlights["longest_game"]["game_duration"] == 2700
    assert highlights["fastest_win"]["match_id"] == "NA1_10"
    # S9 has the most kills but is already the stomp: next best is S5 (27, red side).
    assert highlights["most_team_kills"]["match_id"] == "NA1_5"
    assert highlights["most_team_kills"]["team_kills"] == 27
    assert len({h["match_id"] for h in body["highlights"]}) == 5


async def test_stack_summary_size_queue_and_since(client, session):
    await seed_stacks(session)

    four = await _summary(client, size=4)
    assert (four["size"], four["games"], four["wins"]) == (4, 13, 8)
    by_id = {p["puuid"]: p for p in four["players"]}
    assert by_id[D]["off_days"] == 1 and U not in by_id
    assert four["recent_form"][0] is False  # S13
    assert sorted([A, B, C, D]) in [lu["puuids"] for lu in four["lineups"]]

    three = await _summary(client, size=3)
    assert (three["games"], three["wins"]) == (15, 9)
    assert three["recent_form"][:2] == [True, False]  # S14 blue, then S14 red
    by_id = {p["puuid"]: p for p in three["players"]}
    assert (by_id[F]["games"], by_id[F]["ran_downs"]) == (6, 2)
    assert (by_id[A]["carries"], by_id[D]["games"]) == (3, 14)
    assert {"key": "ran_it_down", "puuid": F, "count": 2} in three["awards"]
    assert three["verdict_games"] == 7 + 3

    flex = await _summary(client, size=3, queue="flex")
    assert (flex["queue"], flex["games"], flex["wins"]) == ("flex", 12, 8)

    everything = await _summary(client, since="all")
    assert (everything["games"], everything["wins"]) == (13, 9)
    assert everything["verdict_games"] == 7
    assert everything["most_played_lineup"]["games"] == 8
    assert everything["recent_form"][-1] is True  # the preseason game is the oldest


async def test_stack_summary_empty(client, session):
    await add_summoner(session, A, "Alpha", "NA1", tracked=True)
    await add_match(session, _game("NA1_1", [A], hour=1))
    await session.commit()
    body = await _summary(client)
    assert (body["games"], body["wins"], body["winrate"], body["verdict_games"]) == (0, 0, 0, 0)
    assert body["avg_duration"] is None and body["avg_team_kills"] is None
    assert body["avg_enemy_kills"] is None and body["recent_form"] == []
    assert body["players"] == [] and body["lineups"] == [] and body["awards"] == []
    assert body["best_lineup"] is None and body["most_played_lineup"] is None
    assert body["highlights"] == [] and body["model_version"] is None


async def test_stack_games_first_page(client, session):
    await seed_stacks(session)
    resp = await client.get(GAMES_URL, params={"limit": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [g["match_id"] for g in body["items"]] == [f"NA1_{i}" for i in (12, 11, 10, 9, 8)]
    assert body["next_cursor"]

    s9 = body["items"][3]
    assert (s9["queue_id"], s9["queue_label"], s9["game_mode"]) == (440, "Ranked Flex", "CLASSIC")
    assert (s9["team_id"], s9["win"], s9["team_kills"], s9["enemy_kills"]) == (100, True, 42, 27)
    assert s9["game_duration"] == 1800 and s9["patch"]
    assert datetime.fromisoformat(s9["game_start"]) == SEASON + timedelta(hours=9)
    assert [m["puuid"] for m in s9["members"]] == FIVE_F
    assert s9["verdict"] == {"tier": "edge", "target_puuid": A, "gap": 12}
    a = s9["members"][0]
    assert (a["kills"], a["participant_id"], a["is_tracked"]) == (20, 1, True)
    assert a["kill_participation"] == pytest.approx((20 + 3) / 42, abs=1e-4)
    # Ranked against all ten players (fillers are unscored): A is the best score.
    assert a["ai_rank"] == 1 and a["ai_score"] == pytest.approx(0.7)
    # Unscored members / a v0 score: no verdict.
    assert body["items"][0]["verdict"] is None
    assert body["items"][4]["verdict"] is None


async def test_stack_games_pages_walk_everything(client, session):
    await seed_stacks(session)
    summary = await _summary(client, size=3, since="all")
    items, pages = await _all_games(client, size=3, since="all", limit=1)

    keys = [key for page in pages for key in page]
    assert len(keys) == len(set(keys)) == summary["games"] == 16
    # One match per page; the 3v3 match puts both stacks on the same page, blue first.
    assert len(pages) == 15
    assert ["NA1_14/100", "NA1_14/200"] in pages
    assert all(len(page) == 1 for page in pages if page[0][:6] != "NA1_14")
    assert keys[0] == "NA1_14/100" and keys[-1] == "NA1_20/100"
    red = next(g for g in items if g["match_id"] == "NA1_14" and g["team_id"] == 200)
    assert [m["puuid"] for m in red["members"]] == [D, E, F]
    assert (red["win"], red["team_kills"], red["enemy_kills"]) == (False, 27, 24)
    assert red["verdict"] == {"tier": "ranDown", "target_puuid": F, "gap": 25}

    # Every verdict across the pages adds up to the summary's per-player counts.
    tiers: Counter[tuple[str, str]] = Counter(
        (g["verdict"]["target_puuid"], g["verdict"]["tier"])
        for g in items
        if g["verdict"] and g["verdict"]["target_puuid"]
    )
    assert sum(1 for g in items if g["verdict"]) == summary["verdict_games"]
    for p in summary["players"]:
        mine = {tier: n for (puuid, tier), n in tiers.items() if puuid == p["puuid"]}
        assert p["hard_carries"] == mine.get("hardCarry", 0)
        assert p["carries"] == sum(mine.get(t, 0) for t in CARRY_TIERS)
        assert p["ran_downs"] == sum(mine.get(t, 0) for t in RAN_DOWN_TIERS)
        assert p["off_days"] == mine.get("offDay", 0)
        assert p["tried"] == mine.get("tried", 0)
    games_by_player = Counter(m["puuid"] for g in items for m in g["members"])
    assert {p["puuid"]: p["games"] for p in summary["players"]} == dict(games_by_player)


async def test_stack_games_filters(client, session):
    await seed_stacks(session)
    items, _ = await _all_games(client, limit=50)
    assert [g["match_id"] for g in items] == [f"NA1_{i}" for i in range(12, 0, -1)]
    assert [g["team_id"] for g in items if g["match_id"] == "NA1_5"] == [200]

    items, pages = await _all_games(client, size=4, limit=3)
    assert [g["match_id"] for g in items][:2] == ["NA1_13", "NA1_12"]
    assert len(items) == 13 and len(pages) == 5
    s13 = items[0]
    assert [m["puuid"] for m in s13["members"]] == [A, B, C, D]
    assert s13["verdict"] == {"tier": "offDay", "target_puuid": D, "gap": 13}
    assert s13["queue_label"] == "Normal Draft"

    items, _ = await _all_games(client, size=3, queue="flex", limit=50)
    assert len(items) == 12 and {g["queue_id"] for g in items} == {440}


async def test_stack_games_bad_cursor(client, session):
    await seed_stacks(session)
    resp = await client.get(GAMES_URL, params={"cursor": "not-a-cursor!"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_cursor"


RECENT_URL = "/api/v1/squad/recent"


async def test_recent_games_is_every_roster_game(client, session):
    await seed_stacks(session)
    items: list[dict] = []
    cursor = None
    while True:
        params = {"limit": 4} | ({"cursor": cursor} if cursor else {})
        resp = await client.get(RECENT_URL, params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        items += body["items"]
        cursor = body["next_cursor"]
        if not cursor:
            break

    keys = [f"{g['match_id']}/{g['team_id']}" for g in items]
    assert len(keys) == len(set(keys))
    starts = [g["game_start"] for g in items]
    assert starts == sorted(starts, reverse=True)
    # Every stack (any size, any period) is in the feed; so is any single roster player.
    stacks, _ = await _all_games(client, size=3, since="all", limit=50)
    assert {f"{g['match_id']}/{g['team_id']}" for g in stacks} <= set(keys)
    assert all(g["members"] and all(m["is_tracked"] for m in g["members"]) for g in items)
    assert not any(g["queue_id"] in (0, 1700, 1710, 3100) for g in items)


async def test_recent_games_limits(client, session):
    await seed_stacks(session)
    resp = await client.get(RECENT_URL, params={"cursor": "not-a-cursor!"})
    assert resp.status_code == 400 and resp.json()["code"] == "invalid_cursor"
    assert (await client.get(RECENT_URL, params={"limit": 21})).status_code == 422
    # Default page: 8 matches (plus the other team when both teams had roster players).
    assert len((await client.get(RECENT_URL)).json()["items"]) <= 8 + 1
