"""GET /summoners/{puuid}/insights/{sessions,schedule,matchups,luck}.

Input validation, the unknown-summoner 404 and the bad-time-zone 400 are covered by
``test_api_contract_routes``; this module checks each endpoint's rules and edge cases.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from tests.factories import ParticipantSpec, filler_specs, make_match_json, spec
from tests.test_api_support import add_match, add_model, add_summoner

ME = "puuid-me"
BASE = "/api/v1/summoners/puuid-me/insights"
#: A Monday well inside the default season (2026-01-08T20:00Z onwards).
DAY = datetime(2026, 4, 6, 18, tzinfo=UTC)
PRESEASON = datetime(2025, 12, 1, 20, tzinfo=UTC)
ME_CHAMP = (103, "Ahri")
ORIANNA = (61, "Orianna")
ZED = (238, "Zed")

_ids = itertools.count(1)
Edit = Callable[[list[ParticipantSpec]], None]


async def game(
    session,
    start: datetime,
    *,
    win: bool = True,
    score: float | None = None,
    model_version: str = "v1",
    queue_id: int = 420,
    duration_s: int = 1800,
    remake: bool = False,
    opponent: tuple[int, str] | None = None,
    my_gold: int | None = None,
    opp_gold: int | None = None,
    edit: Edit | None = None,
) -> str:
    """One match with ME in blue slot 2 (MIDDLE, Ahri) and the lane opponent in red slot 7
    (MIDDLE, Orianna unless ``opponent``); ``edit`` may change the specs before building."""
    match_id = f"NA1_{7_000_000_000 + next(_ids)}"
    slots = filler_specs(match_id, 10)
    slots[2] = spec(ME, "Me", "NA1", champion=ME_CHAMP, position="MIDDLE")
    slots[7] = spec(f"opp-{match_id}", "Opp", "NA1", champion=opponent or ORIANNA)
    if my_gold is not None:
        slots[2].overrides["goldEarned"] = my_gold
    if opp_gold is not None:
        slots[7].overrides["goldEarned"] = opp_gold
    if edit is not None:
        edit(slots)
    raw = make_match_json(
        match_id,
        slots,
        queue_id=queue_id,
        duration_s=duration_s,
        start=start,
        winning_team=100 if win else 200,
        remake=remake,
    )
    scores = {ME: score} if score is not None else None
    await add_match(session, raw, scores=scores, model_version=model_version)
    return match_id


async def setup_me(session, *, model: bool = True) -> None:
    await add_summoner(session, ME, "Me", "NA1", tracked=True)
    if model:
        await add_model(session, "v1", active=True)


async def get(client, path: str, **params) -> dict:
    resp = await client.get(f"{BASE}/{path}", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def chain(start: datetime, results: list[bool], *, break_min: int = 5, duration_s: int = 1800):
    """Start times of back-to-back games ``break_min`` minutes apart (end to start)."""
    step = timedelta(seconds=duration_s) + timedelta(minutes=break_min)
    return [(start + step * i, win) for i, win in enumerate(results)]


# --- sessions (tilt detector) ----------------------------------------------------------------


async def test_sessions_split_exactly_on_the_gap(client, session):
    await setup_me(session)
    t0 = DAY
    t1 = t0 + timedelta(minutes=30 + 45)  # starts exactly 45 min after t0's game ended
    t2 = t1 + timedelta(minutes=30 + 45, seconds=1)  # one second more than the gap
    for t in (t0, t1, t2):
        await game(session, t, duration_s=1800)
    await session.commit()

    body = await get(client, "sessions")
    assert body["gap_minutes"] == 45 and body["min_games"] == 5
    assert body["model_version"] == "v1"
    assert body["sessions"] == 2 and body["games"] == 3
    assert body["longest_session_games"] == 2
    assert body["avg_session_games"] == pytest.approx(1.5)
    assert [b["games"] for b in body["by_game_number"]] == [2, 1, 0, 0, 0, 0]

    # A 10-minute gap splits every game; a 75-minute gap joins all three.
    assert (await get(client, "sessions", gap_minutes=10))["sessions"] == 3
    joined = await get(client, "sessions", gap_minutes=75)
    assert joined["sessions"] == 1 and joined["longest_session_games"] == 3


async def test_sessions_bucket_six_means_sixth_or_later(client, session):
    await setup_me(session)
    for start, win in chain(DAY, [True, False] * 4):
        await game(session, start, win=win)
    await session.commit()

    body = await get(client, "sessions")
    assert body["sessions"] == 1 and body["longest_session_games"] == 8
    buckets = body["by_game_number"]
    assert [b["n"] for b in buckets] == [1, 2, 3, 4, 5, 6]
    assert [b["games"] for b in buckets] == [1, 1, 1, 1, 1, 3]
    # Games 6, 7, 8 = loss, win, loss.
    assert buckets[5]["wins"] == 1
    assert buckets[5]["winrate"] == pytest.approx(1 / 3, abs=1e-4)


async def test_session_states_look_back_within_the_session_only(client, session):
    await setup_me(session)
    first = chain(DAY, [True, False, False, False, True])
    second = chain(DAY + timedelta(hours=8), [False, False])
    # The loss that ends session 1 is not carried into session 2.
    for start, win in first + second:
        await game(session, start, win=win)
    await session.commit()

    body = await get(client, "sessions")
    assert body["sessions"] == 2
    states = {b["state"]: b for b in body["by_state"]}
    assert [b["state"] for b in body["by_state"]] == [
        "first_game",
        "after_win",
        "after_one_loss",
        "after_two_plus_losses",
    ]
    counts = {state: (b["games"], b["wins"]) for state, b in states.items()}
    assert counts == {
        "first_game": (2, 1),
        "after_win": (1, 0),
        # Session 1 game 3 and session 2 game 2.
        "after_one_loss": (2, 0),
        # Session 1 games 4 (after L, L) and 5 (after L, L, L).
        "after_two_plus_losses": (2, 1),
    }
    assert states["after_two_plus_losses"]["winrate"] == pytest.approx(0.5)


async def test_sessions_average_only_active_model_scores(client, session):
    await setup_me(session)
    starts = chain(DAY, [True, True, True, True])
    await game(session, starts[0][0], score=0.8)
    await game(session, starts[1][0], score=0.1, model_version="v0")  # inactive model
    await game(session, starts[2][0])  # not scored
    await game(session, starts[3][0], score=0.6)
    await session.commit()

    body = await get(client, "sessions")
    scores = [b["avg_ai_score"] for b in body["by_game_number"]]
    assert scores[:4] == [pytest.approx(0.8), None, None, pytest.approx(0.6)]
    assert scores[4:] == [None, None]
    states = {b["state"]: b for b in body["by_state"]}
    assert states["first_game"]["avg_ai_score"] == pytest.approx(0.8)
    assert states["after_win"]["games"] == 3
    assert states["after_win"]["avg_ai_score"] == pytest.approx(0.6)
    assert states["after_one_loss"]["avg_ai_score"] is None


async def test_sessions_filters_and_excluded_games(client, session):
    await setup_me(session)
    await game(session, PRESEASON)
    await game(session, DAY)  # solo, ends DAY + 30m
    # A remake in between does not bridge the gap: the next counted game starts 70 minutes
    # after the first one ended.
    await game(session, DAY + timedelta(minutes=35), remake=True, duration_s=200)
    await game(session, DAY + timedelta(minutes=100), queue_id=440)
    await game(session, DAY + timedelta(minutes=140), queue_id=450)  # ARAM: never counted
    await session.commit()

    season = await get(client, "sessions")
    assert (season["games"], season["sessions"]) == (2, 2)
    assert season["since"] == "season" and season["queue"] == "all"
    everything = await get(client, "sessions", since="all")
    assert (everything["games"], everything["sessions"]) == (3, 3)
    solo = await get(client, "sessions", queue="solo")
    assert (solo["games"], solo["queue"]) == (1, "solo")
    flex = await get(client, "sessions", queue="flex", since="all")
    assert flex["games"] == 1


# --- schedule (best time to play) ------------------------------------------------------------


async def test_schedule_converts_to_local_time_across_dst(client, session):
    await setup_me(session)
    # Both are Friday 19:30 in Chicago: CST (UTC-6) before 2026-03-08, CDT (UTC-5) after.
    await game(session, datetime(2026, 3, 7, 1, 30, tzinfo=UTC), score=0.7)
    await game(session, datetime(2026, 3, 14, 0, 30, tzinfo=UTC), win=False, score=0.3)
    await session.commit()

    chicago = await get(client, "schedule")
    assert chicago["tz"] == "America/Chicago" and chicago["min_games"] == 5
    assert chicago["cells"] == [
        {"dow": 4, "hour": 19, "games": 2, "wins": 1, "avg_ai_score": pytest.approx(0.5)}
    ]
    assert len(chicago["by_dow"]) == 7 and len(chicago["by_hour"]) == 24
    assert [d["dow"] for d in chicago["by_dow"]] == list(range(7))
    assert [h["hour"] for h in chicago["by_hour"]] == list(range(24))
    friday = chicago["by_dow"][4]
    assert (friday["games"], friday["wins"], friday["winrate"]) == (2, 1, 0.5)
    assert chicago["by_hour"][19]["games"] == 2
    assert sum(d["games"] for d in chicago["by_dow"]) == 2
    assert chicago["best_window"] is None and chicago["worst_window"] is None

    utc = await get(client, "schedule", tz="UTC")
    assert utc["tz"] == "UTC"
    assert [(c["dow"], c["hour"]) for c in utc["cells"]] == [(5, 0), (5, 1)]
    tokyo = await get(client, "schedule", tz="Asia/Tokyo")
    assert [(c["dow"], c["hour"]) for c in tokyo["cells"]] == [(5, 9), (5, 10)]


async def test_schedule_best_and_worst_windows(client, session):
    await setup_me(session)
    # April 2026: Chicago is UTC-5. Monday 20:xx local = Tuesday 01:xx UTC.
    monday_8pm = datetime(2026, 4, 7, 1, tzinfo=UTC)
    for i, win in enumerate([True, True, True, True, False]):
        await game(session, monday_8pm + timedelta(minutes=5 * i), win=win)
    # Tuesday 10:xx local: 6 games, 1 win.
    tuesday_10am = datetime(2026, 4, 7, 15, tzinfo=UTC)
    for i in range(6):
        await game(session, tuesday_10am + timedelta(minutes=5 * i), win=i == 0)
    # Wednesday 23:xx + Thursday 00:xx local: 3 + 3 losses. Windows never cross midnight, so
    # neither day reaches 5 games and this 0% stretch is not a window.
    wednesday_11pm = datetime(2026, 4, 9, 4, tzinfo=UTC)
    for i in range(3):
        await game(session, wednesday_11pm + timedelta(minutes=5 * i), win=False)
        await game(session, wednesday_11pm + timedelta(hours=1, minutes=5 * i), win=False)
    await session.commit()

    body = await get(client, "schedule")
    assert [(c["dow"], c["hour"], c["games"]) for c in body["cells"]] == [
        (0, 20, 5),
        (1, 10, 6),
        (2, 23, 3),
        (3, 0, 3),
    ]
    # 18-21, 19-22 and 20-23 hold the same five games: the one starting at 20:00 wins.
    assert body["best_window"] == {
        "dow": 0,
        "start_hour": 20,
        "end_hour": 23,
        "games": 5,
        "winrate": 0.8,
    }
    assert body["worst_window"] == {
        "dow": 1,
        "start_hour": 10,
        "end_hour": 13,
        "games": 6,
        "winrate": pytest.approx(1 / 6, abs=1e-4),
    }


async def test_schedule_worst_window_needs_a_lower_winrate(client, session):
    await setup_me(session)
    monday_8pm = datetime(2026, 4, 7, 1, tzinfo=UTC)
    for i in range(5):
        await game(session, monday_8pm + timedelta(minutes=5 * i), win=True)
    await session.commit()

    body = await get(client, "schedule")
    assert body["best_window"]["start_hour"] == 20 and body["best_window"]["winrate"] == 1.0
    assert body["worst_window"] is None


async def test_schedule_scores_and_empty_cells(client, session):
    await setup_me(session)
    monday_8pm = datetime(2026, 4, 7, 1, tzinfo=UTC)
    await game(session, monday_8pm, score=0.9)
    await game(session, monday_8pm + timedelta(minutes=40), score=0.2, model_version="v0")
    await session.commit()

    body = await get(client, "schedule")
    assert body["cells"] == [{"dow": 0, "hour": 20, "games": 2, "wins": 2, "avg_ai_score": 0.9}]
    assert body["by_dow"][1] == {
        "dow": 1,
        "games": 0,
        "wins": 0,
        "winrate": 0.0,
        "avg_ai_score": None,
    }


# --- matchups (nemesis champions) ------------------------------------------------------------


async def test_matchups_record_gold_and_own_score(client, session):
    await setup_me(session)
    t = DAY
    for i, (win, score, gold) in enumerate([(True, 0.2, 10_000), (False, 0.4, 9_000)]):
        await game(
            session,
            t + timedelta(hours=i),
            win=win,
            score=score,
            my_gold=gold,
            opp_gold=11_000,
        )
    # Third Orianna game: scored by an old model, so it has no score.
    await game(session, t + timedelta(hours=2), win=False, score=0.9, model_version="v0")
    for i in range(3):
        await game(
            session, t + timedelta(hours=3 + i), opponent=ZED, my_gold=12_000, opp_gold=9_000
        )
    await session.commit()

    body = await get(client, "matchups")
    assert body["min_games"] == 3 and body["total_matchups"] == 6
    assert body["model_version"] == "v1"
    [orianna] = body["nemeses"]
    assert orianna["champion_id"] == 61 and orianna["champion_name"] == "Orianna"
    assert (orianna["games"], orianna["wins"], orianna["losses"]) == (3, 1, 2)
    assert orianna["winrate"] == pytest.approx(1 / 3, abs=1e-4)
    assert orianna["avg_ai_score"] == pytest.approx(0.3)
    [zed] = body["favorites"]
    assert (zed["champion_name"], zed["games"], zed["wins"], zed["losses"]) == ("Zed", 3, 3, 0)
    assert zed["avg_gold_diff"] == pytest.approx(3000.0)
    assert zed["avg_ai_score"] is None


async def test_matchups_gold_diff_is_player_minus_opponent(client, session):
    await setup_me(session)
    await game(session, DAY, my_gold=10_000, opp_gold=11_000)
    await game(session, DAY + timedelta(hours=1), my_gold=9_000, opp_gold=11_500)
    await session.commit()

    body = await get(client, "matchups", min_games=1)
    [orianna] = body["favorites"]
    assert orianna["avg_gold_diff"] == pytest.approx((-1000 - 2500) / 2)


def _second_blue_mid(slots: list[ParticipantSpec]) -> None:
    slots[3].team_position = "MIDDLE"


def _second_red_mid(slots: list[ParticipantSpec]) -> None:
    slots[8].team_position = "MIDDLE"


def _no_red_mid(slots: list[ParticipantSpec]) -> None:
    slots[7].team_position = "TOP"


def _unknown_positions(slots: list[ParticipantSpec]) -> None:
    slots[2].overrides["teamPosition"] = ""
    slots[7].overrides["teamPosition"] = ""


@pytest.mark.parametrize(
    "edit",
    [_second_blue_mid, _second_red_mid, _no_red_mid, _unknown_positions],
    ids=["two-mids-on-my-team", "two-enemy-mids", "no-enemy-mid", "unknown-position"],
)
async def test_matchups_skip_games_without_one_clear_opponent(client, session, edit):
    await setup_me(session)
    await game(session, DAY, opponent=ZED, edit=edit)
    await game(session, DAY + timedelta(hours=1), win=False)  # the only clear matchup
    await session.commit()

    body = await get(client, "matchups", min_games=1)
    assert body["total_matchups"] == 1
    assert body["favorites"] == []
    assert [m["champion_name"] for m in body["nemeses"]] == ["Orianna"]


async def test_matchups_order_threshold_and_even_records(client, session):
    await setup_me(session)
    records = {
        (1, "Aa"): [False, False],  # 0/2
        (2, "Bb"): [False],  # 0/1
        (3, "Cc"): [True, False, False],  # 1/3
        (4, "Dd"): [True, False],  # 1/2: even, in neither list
        (5, "Ee"): [True, True],  # 2/2
        (6, "Ff"): [True, True, False],  # 2/3
    }
    t = DAY
    for champion, results in records.items():
        for win in results:
            t += timedelta(hours=1)
            await game(session, t, win=win, opponent=champion)
    await session.commit()

    loose = await get(client, "matchups", min_games=1)
    assert loose["total_matchups"] == 13
    assert [m["champion_name"] for m in loose["nemeses"]] == ["Aa", "Bb", "Cc"]
    assert [m["champion_name"] for m in loose["favorites"]] == ["Ee", "Ff"]

    default = await get(client, "matchups")
    assert default["total_matchups"] == 13
    assert [m["champion_name"] for m in default["nemeses"]] == ["Cc"]
    assert [m["champion_name"] for m in default["favorites"]] == ["Ff"]


async def test_matchups_lists_hold_at_most_eight(client, session):
    await setup_me(session)
    for i in range(9):
        await game(session, DAY + timedelta(hours=i), win=False, opponent=(900 + i, f"C{i}"))
    await session.commit()

    body = await get(client, "matchups", min_games=1)
    assert body["total_matchups"] == 9
    assert len(body["nemeses"]) == 8 and body["favorites"] == []


async def test_matchups_filters(client, session):
    await setup_me(session)
    await game(session, PRESEASON, opponent=ZED)
    await game(session, DAY, opponent=ZED, queue_id=440)
    await game(session, DAY + timedelta(hours=1), opponent=ZED)
    await game(session, DAY + timedelta(hours=2), opponent=ZED, remake=True, duration_s=200)
    await session.commit()

    assert (await get(client, "matchups", min_games=1))["total_matchups"] == 2
    assert (await get(client, "matchups", min_games=1, since="all"))["total_matchups"] == 3
    solo = await get(client, "matchups", min_games=1, queue="solo")
    assert solo["total_matchups"] == 1 and solo["queue"] == "solo"
    assert (await get(client, "matchups", min_games=1, queue="flex"))["total_matchups"] == 1


# --- luck (unlucky losses / lucky wins) ------------------------------------------------------


async def test_luck_thresholds_are_inclusive_and_active_model_only(client, session):
    await setup_me(session)
    t = DAY
    losses = [(0.6, "v1"), (0.59, "v1"), (0.9, "v1"), (0.75, "v0"), (None, "v1")]
    wins = [(0.4, "v1"), (0.41, "v1"), (0.05, "v1"), (0.2, "v0"), (None, "v1")]
    ids: dict[float | None, str] = {}
    for win, rows in ((False, losses), (True, wins)):
        for score, version in rows:
            t += timedelta(hours=1)
            match_id = await game(session, t, win=win, score=score, model_version=version)
            if version == "v1":
                ids[score] = match_id
    await session.commit()

    body = await get(client, "luck")
    assert body["model_version"] == "v1"
    assert body["high_threshold"] == 0.6 and body["low_threshold"] == 0.4
    assert (body["losses_scored"], body["unlucky_count"]) == (3, 2)
    assert (body["wins_scored"], body["lucky_count"]) == (3, 2)
    assert [g["ai_score"] for g in body["unlucky_losses"]] == [0.9, 0.6]
    assert [g["match_id"] for g in body["unlucky_losses"]] == [ids[0.9], ids[0.6]]
    assert [g["ai_score"] for g in body["lucky_wins"]] == [0.05, 0.4]

    first = body["unlucky_losses"][0]
    assert first["queue_id"] == 420 and first["duration"] == 1800
    assert first["champion_name"] == "Ahri" and first["team_position"] == "MIDDLE"
    assert {"kills", "deaths", "assists", "game_start"} <= first.keys()
    # Score within role: the MIDDLE population is the six v1-scored rows above (0.05, 0.4,
    # 0.41, 0.59, 0.6, 0.9); a percentile is the share of it strictly below the score.
    unlucky_pct = [g["ai_role_percentile"] for g in body["unlucky_losses"]]
    lucky_pct = [g["ai_role_percentile"] for g in body["lucky_wins"]]
    assert unlucky_pct == [pytest.approx(500 / 6, abs=0.01), pytest.approx(400 / 6, abs=0.01)]
    assert lucky_pct == [0.0, pytest.approx(100 / 6, abs=0.01)]


async def test_luck_role_percentile_is_none_for_unknown_position(client, session):
    await setup_me(session)

    def unknown(slots: list[ParticipantSpec]) -> None:
        slots[2].overrides["teamPosition"] = ""

    await game(session, DAY, win=False, score=0.9, edit=unknown)
    await session.commit()

    [loss] = (await get(client, "luck"))["unlucky_losses"]
    assert loss["team_position"] == "UNKNOWN" and loss["ai_role_percentile"] is None


async def test_luck_ties_newest_first_and_limit(client, session):
    await setup_me(session)
    ids = [await game(session, DAY + timedelta(hours=i), win=False, score=0.7) for i in range(3)]
    await session.commit()

    body = await get(client, "luck", limit=2)
    assert body["unlucky_count"] == 3
    assert [g["match_id"] for g in body["unlucky_losses"]] == [ids[2], ids[1]]
    assert body["lucky_wins"] == []


async def test_luck_filters(client, session):
    await setup_me(session)
    await game(session, PRESEASON, win=False, score=0.8)
    await game(session, DAY, win=False, score=0.8, queue_id=440)
    await game(session, DAY + timedelta(hours=1), win=True, score=0.1)
    await session.commit()

    season = await get(client, "luck")
    assert (season["unlucky_count"], season["lucky_count"]) == (1, 1)
    assert (await get(client, "luck", since="all"))["unlucky_count"] == 2
    solo = await get(client, "luck", queue="solo")
    assert (solo["unlucky_count"], solo["lucky_count"], solo["losses_scored"]) == (0, 1, 0)


async def test_luck_without_any_scores(client, session):
    await setup_me(session, model=False)
    await game(session, DAY, win=False)
    await session.commit()

    body = await get(client, "luck")
    assert body["model_version"] is None
    assert (body["losses_scored"], body["unlucky_count"]) == (0, 0)
    assert body["unlucky_losses"] == [] and body["lucky_wins"] == []


# --- players without games -------------------------------------------------------------------


async def test_empty_player_gets_valid_empty_responses(client, session):
    await setup_me(session)
    await session.commit()

    sessions = await get(client, "sessions")
    assert (sessions["sessions"], sessions["games"], sessions["avg_session_games"]) == (0, 0, 0.0)
    assert sessions["longest_session_games"] == 0
    assert len(sessions["by_game_number"]) == 6 and len(sessions["by_state"]) == 4
    assert all(
        b["games"] == 0 and b["avg_ai_score"] is None
        for b in sessions["by_game_number"] + sessions["by_state"]
    )

    schedule = await get(client, "schedule")
    assert schedule["cells"] == []
    assert len(schedule["by_dow"]) == 7 and len(schedule["by_hour"]) == 24
    assert schedule["best_window"] is None and schedule["worst_window"] is None

    matchups = await get(client, "matchups")
    assert matchups["total_matchups"] == 0
    assert matchups["nemeses"] == [] and matchups["favorites"] == []

    luck = await get(client, "luck")
    assert luck["losses_scored"] == 0 and luck["wins_scored"] == 0
    assert luck["unlucky_losses"] == [] and luck["lucky_wins"] == []
